// Voice turn controller (TRD §16): IDLE → REQUESTING_MIC → LISTENING → THINKING → SPEAKING,
// SPEAKING → INTERRUPTED → LISTENING, any → ERROR/TEXT_FALLBACK.
//
// Two engines share the same states and rules:
//  - "cartesia": 16 kHz PCM is streamed to our backend WebSocket, which relays to Cartesia STT/TTS.
//    Every audio chunk carries turn_version; chunks older than the last barge-in are dropped.
//  - "browser": no Cartesia key on the server. Uses the browser's SpeechRecognition/speechSynthesis
//    where available; transcripts go to POST /intake/messages. Audio never leaves the device.
// No API keys exist in the frontend in either mode.

import { api } from './api'
import type { IntakeReply, VoiceSessionInfo } from './types'

export type VoiceState = 'IDLE' | 'REQUESTING_MIC' | 'LISTENING' | 'THINKING' | 'SPEAKING' | 'INTERRUPTED' | 'RECONNECTING' | 'TEXT_FALLBACK' | 'ERROR'

export interface VoiceEvents {
  onState: (s: VoiceState) => void
  onPartial: (text: string) => void
  onUserFinal: (text: string) => void
  onReply: (reply: IntakeReply) => void
  onLevel: (level: number) => void
  onNotice: (message: string) => void
  onMetric?: (m: { ttfa_ms?: number; interrupt_ms?: number }) => void
}

type SpeechRecognitionLike = {
  continuous: boolean; interimResults: boolean; lang: string
  onresult: ((e: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null
  onerror: ((e: { error: string }) => void) | null
  onend: (() => void) | null
  start: () => void; stop: () => void; abort: () => void
}

const WORKLET = `
class PcmCapture extends AudioWorkletProcessor {
  constructor() { super(); this.buf = []; this.n = 0 }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (ch) {
      let sum = 0
      const out = new Int16Array(ch.length)
      for (let i = 0; i < ch.length; i++) { const s = Math.max(-1, Math.min(1, ch[i])); out[i] = s < 0 ? s * 0x8000 : s * 0x7fff; sum += s * s }
      this.buf.push(out); this.n += out.length
      this.port.postMessage({ level: Math.sqrt(sum / ch.length) })
      if (this.n >= 1600) { // 100 ms at 16 kHz
        const joined = new Int16Array(this.n); let o = 0
        for (const b of this.buf) { joined.set(b, o); o += b.length }
        this.port.postMessage({ pcm: joined.buffer }, [joined.buffer]); this.buf = []; this.n = 0
      }
    }
    return true
  }
}
registerProcessor('pcm-capture', PcmCapture)`

const SPEECH_LEVEL = 0.035 // RMS threshold for "user is talking"
const SPEECH_START_MS = 180
// Ordinary mid-sentence pauses are often 0.5–1 s; wait longer before ending the turn.
const SPEECH_END_MS = 1300
const MIN_UTTERANCE_MS = 400

export class VoiceController {
  state: VoiceState = 'IDLE'
  mode: 'cartesia' | 'browser' | null = null
  private ev: VoiceEvents
  private info: VoiceSessionInfo | null = null
  private ws: WebSocket | null = null
  private micStream: MediaStream | null = null
  private inCtx: AudioContext | null = null
  private outCtx: AudioContext | null = null
  private sources: AudioBufferSourceNode[] = []
  private playhead = 0
  private acceptedVersion = 0
  private talkingSince = 0
  private silentSince = 0
  private userTalking = false
  private utteranceStart = 0
  private preroll: ArrayBuffer[] = [] // mic audio captured before the socket opens (otherwise the first word is lost)
  private muted = false
  private rec: SpeechRecognitionLike | null = null
  private turn = 0
  private active = false
  private history: { role: 'user' | 'assistant'; text: string }[] = []

  constructor(events: VoiceEvents) { this.ev = events }

  private set(s: VoiceState) { this.state = s; this.ev.onState(s) }

  /** Caller must have obtained explicit voice consent first. */
  async start(history: { role: 'user' | 'assistant'; text: string }[]) {
    this.history = history.slice(-10)
    this.active = true
    this.set('REQUESTING_MIC')
    try {
      this.info = await api.post<VoiceSessionInfo>('/voice/sessions', { voice_consent: true })
    } catch (e) {
      this.fail(e instanceof Error ? e.message : 'Voice is unavailable.')
      return
    }
    this.mode = this.info.mode
    if (this.info.mode === 'cartesia') await this.startCartesia()
    else this.startBrowser()
  }

  stop() {
    this.active = false
    try { this.ws?.send(JSON.stringify({ type: 'session.end' })) } catch { /* closing anyway */ }
    this.ws?.close(); this.ws = null; this.preroll = []
    this.rec?.abort(); this.rec = null
    if (typeof speechSynthesis !== 'undefined') speechSynthesis.cancel()
    this.stopPlayback()
    this.micStream?.getTracks().forEach(t => t.stop()); this.micStream = null
    this.inCtx?.close().catch(() => undefined); this.inCtx = null
    this.outCtx?.close().catch(() => undefined); this.outCtx = null
    this.ev.onLevel(0)
    this.set('IDLE')
  }

  setMuted(muted: boolean) {
    this.muted = muted
    if (this.outCtx) this.outCtx.resume()
    if (muted) { this.stopPlayback(); if (typeof speechSynthesis !== 'undefined') speechSynthesis.cancel() }
  }

  /** Manual "Interrupt" button; speech barge-in calls the same path. */
  interrupt() {
    if (this.state !== 'SPEAKING' && this.state !== 'THINKING') return
    if (this.mode === 'cartesia') {
      this.stopPlayback()
      this.ws?.send(JSON.stringify({ type: 'barge_in' }))
    } else {
      this.turn += 1 // any reply still in flight is now stale
      speechSynthesis.cancel()
      this.set('INTERRUPTED'); this.set('LISTENING')
    }
  }

  /** Typed message while in voice mode; same pipeline as speech. */
  sendText(text: string) {
    if (this.mode === 'cartesia' && this.ws?.readyState === WebSocket.OPEN) {
      this.stopPlayback()
      this.ws.send(JSON.stringify({ type: 'text', text }))
    } else void this.browserTurn(text)
  }

  private fail(message: string) {
    this.ev.onNotice(message)
    this.stop()
    this.set('TEXT_FALLBACK')
  }

  // ---- Cartesia engine ------------------------------------------------------

  private async startCartesia() {
    try {
      this.micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } })
    } catch {
      this.fail('Microphone permission was denied. You can keep going by typing.')
      return
    }
    this.inCtx = new AudioContext({ sampleRate: this.info!.input.sample_rate })
    this.outCtx = new AudioContext({ sampleRate: this.info!.output.sample_rate })
    const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }))
    await this.inCtx.audioWorklet.addModule(url)
    URL.revokeObjectURL(url)
    const node = new AudioWorkletNode(this.inCtx, 'pcm-capture')
    this.inCtx.createMediaStreamSource(this.micStream).connect(node)

    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    this.ws = new WebSocket(`${proto}://${location.host}${this.info!.stream_path}`)
    this.ws.binaryType = 'arraybuffer'
    this.ws.onopen = () => {
      this.ws?.send(JSON.stringify({ type: 'history', items: this.history }))
      for (const chunk of this.preroll) this.ws?.send(chunk)
      this.preroll = []
    }
    this.ws.onmessage = e => this.onServer(JSON.parse(e.data as string))
    this.ws.onclose = ev => {
      if (!this.active) return
      this.fail(ev.code === 4401 ? 'Voice consent is required.' : 'Voice connection closed. Switched to text.')
    }
    node.port.onmessage = (e: MessageEvent<{ level?: number; pcm?: ArrayBuffer }>) => {
      if (e.data.level !== undefined) this.vad(e.data.level)
      if (!e.data.pcm || this.state === 'THINKING') return
      if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(e.data.pcm)
      else if (this.ws?.readyState === WebSocket.CONNECTING && this.preroll.length < 30) this.preroll.push(e.data.pcm) // ≤3 s
    }
  }

  private vad(level: number) {
    this.ev.onLevel(Math.min(1, level * 8))
    const now = performance.now()
    // While the assistant talks, require louder speech so echo doesn't self-interrupt.
    const threshold = this.state === 'SPEAKING' ? SPEECH_LEVEL * 2 : SPEECH_LEVEL
    if (level > threshold) {
      this.silentSince = 0
      if (!this.talkingSince) this.talkingSince = now
      if (!this.userTalking && now - this.talkingSince > SPEECH_START_MS) {
        this.userTalking = true
        this.utteranceStart = this.talkingSince
        if (this.state === 'SPEAKING' || this.state === 'THINKING') {
          const t0 = performance.now()
          this.interrupt() // barge-in: playback stops locally before the server even hears about it
          this.ev.onMetric?.({ interrupt_ms: Math.round(performance.now() - t0) })
        }
      }
    } else {
      this.talkingSince = 0
      if (this.userTalking) {
        if (!this.silentSince) this.silentSince = now
        if (now - this.silentSince > SPEECH_END_MS) {
          this.userTalking = false
          this.silentSince = 0
          if (now - this.utteranceStart - SPEECH_END_MS >= MIN_UTTERANCE_MS) this.ws?.send(JSON.stringify({ type: 'utterance.end' }))
        }
      }
    }
  }

  private onServer(m: { type: string; turn_version: number; state?: VoiceState; text?: string; data?: string; reply?: IntakeReply; message?: string; ttfa_ms?: number }) {
    if (m.ttfa_ms !== undefined) this.ev.onMetric?.({ ttfa_ms: m.ttfa_ms })
    switch (m.type) {
      case 'state': if (m.state) this.set(m.state); break
      case 'transcript.partial': this.ev.onPartial(m.text ?? ''); break
      case 'transcript.final': this.acceptedVersion = m.turn_version; this.ev.onUserFinal(m.text ?? ''); break
      case 'assistant.text': if (m.reply && m.turn_version >= this.acceptedVersion) this.ev.onReply(m.reply); break
      case 'assistant.cancelled': this.acceptedVersion = m.turn_version; this.stopPlayback(); break
      case 'assistant.audio.chunk': if (m.turn_version >= this.acceptedVersion && m.data) this.play(m.data); break
      case 'audio.error': this.ev.onNotice(m.message ?? 'Voice error.'); break
    }
  }

  private play(b64: string) {
    if (this.muted || !this.outCtx) return
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0))
    const pcm = new Int16Array(bytes.buffer, 0, bytes.byteLength >> 1)
    const buf = this.outCtx.createBuffer(1, pcm.length, this.outCtx.sampleRate)
    const ch = buf.getChannelData(0)
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 0x8000
    const src = this.outCtx.createBufferSource()
    src.buffer = buf
    src.connect(this.outCtx.destination)
    this.playhead = Math.max(this.playhead, this.outCtx.currentTime + 0.03)
    src.start(this.playhead)
    this.playhead += buf.duration
    src.onended = () => { this.sources = this.sources.filter(s => s !== src) }
    this.sources.push(src)
  }

  private stopPlayback() {
    for (const s of this.sources) { try { s.stop() } catch { /* already stopped */ } }
    this.sources = []
    this.playhead = 0
  }

  // ---- Browser fallback engine ---------------------------------------------

  private startBrowser() {
    const w = window as unknown as { SpeechRecognition?: new () => SpeechRecognitionLike; webkitSpeechRecognition?: new () => SpeechRecognitionLike }
    const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition
    if (!Ctor || typeof speechSynthesis === 'undefined') {
      this.fail('This browser has no built-in speech recognition, and Cartesia voice isn’t configured on the server. Text mode works the same way.')
      return
    }
    this.ev.onNotice(this.info?.note ?? '')
    const rec = new Ctor()
    rec.continuous = true
    rec.interimResults = true
    rec.lang = 'en-US'
    rec.onresult = e => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i]
        const text = r[0].transcript.trim()
        if (!text) continue
        if (!r.isFinal) {
          if (this.state === 'SPEAKING') this.interrupt() // barge-in on detected speech
          this.ev.onPartial(text)
        } else void this.browserTurn(text, true)
      }
    }
    rec.onerror = e => { if (e.error === 'not-allowed' || e.error === 'service-not-allowed') this.fail('Microphone permission was denied. You can keep going by typing.') }
    rec.onend = () => { if (this.active && this.rec === rec) { try { rec.start() } catch { /* restarting */ } } }
    this.rec = rec
    try { rec.start() } catch { this.fail('Could not start speech recognition.'); return }
    this.set('LISTENING')
  }

  private async browserTurn(text: string, spoken = false) {
    if (this.state === 'SPEAKING' || this.state === 'THINKING') this.interrupt()
    const mine = ++this.turn
    this.ev.onUserFinal(text)
    this.set('THINKING')
    let reply: IntakeReply
    try {
      reply = await api.post<IntakeReply>('/intake/messages', { message: text, channel: spoken ? 'voice' : 'text', history: this.history })
    } catch (e) {
      this.ev.onNotice(e instanceof Error ? e.message : 'Message failed.')
      if (mine === this.turn) this.set('LISTENING')
      return
    }
    if (mine !== this.turn || !this.active) return // superseded: never spoken or shown as current
    this.history = [...this.history, { role: 'user' as const, text }, { role: 'assistant' as const, text: reply.assistant_message }].slice(-10)
    this.ev.onReply(reply)
    if (this.muted) { this.set('LISTENING'); return }
    const u = new SpeechSynthesisUtterance(reply.assistant_message)
    u.onend = () => { if (mine === this.turn && this.active) this.set('LISTENING') }
    this.set('SPEAKING')
    speechSynthesis.speak(u)
  }
}
