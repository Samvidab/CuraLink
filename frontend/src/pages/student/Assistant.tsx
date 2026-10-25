import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, Card, Icon } from '../../components/ui'
import { HandoffDialog, IntakeDrawer, KnowsCard, PhotoOfferCard, TemperatureCard, useIntake } from '../../components/IntakePanel'
import { api, ApiError } from '../../lib/api'
import { newTurnId, VoiceController, type VoiceState } from '../../lib/voice'
import { ClinicianCard, SlotConfirmDialog } from '../../components/ClinicianSlots'
import { fmtDay, fmtRange, fmtTime } from '../../lib/format'
import type { Health, IntakeReply, IntakeSnapshot, ScheduleResult, ScheduleSlot, ToolEvent } from '../../lib/types'

type Msg = { from: 'ai' | 'user'; text: string; actions?: string[]; tools?: ToolEvent[]; mode?: IntakeReply['mode']; interrupted?: boolean; schedule?: ScheduleResult | null; form?: { fields: string[] } | null }

// Shown until the personalized greeting (GET /assistant/greeting, from the signed-in profile) arrives.
const GREETING: Msg = { from: 'ai', text: 'Hi! I’m CuraLink, your campus healthcare navigator. I can help organize care, not diagnose. How can I help you today?' }
const PROMPTS = ['I feel sick and need a doctor’s appointment', 'I might miss class this week', 'Where can I find mental health support?', 'What should I bring to my appointment?']
const STATE_LABEL: Record<VoiceState, string> = { IDLE: 'Start voice conversation', REQUESTING_MIC: 'Requesting microphone…', LISTENING: 'Listening…', THINKING: 'Thinking…', SPEAKING: 'Speaking — talk to interrupt', INTERRUPTED: 'Interrupted', RECONNECTING: 'Reconnecting…', TEXT_FALLBACK: 'Text mode', ERROR: 'Voice error' }
const ACTIONS: Record<string, { label: string; to?: string }> = {
  REVIEW_INTAKE: { label: 'Review my information' },
  FIND_CARE: { label: 'Find an appointment', to: '/student/appointments' },
  OPEN_INTAKE_FORM: { label: 'Open the details form' },
  ADD_MORE: { label: 'Add more information' },
  END_CONVERSATION: { label: 'End this conversation' },
  IMPORT_CALENDAR: { label: 'Import calendar', to: '/student/import' },
  START_CASE: { label: 'Go to My Cases', to: '/student/cases' },
}
// Visible progress through the stateful intake (see backend/app/services/dialog.py).
const STEPS = ['Your concern', 'A few details', 'Review', 'Next steps']
// Why Claude wasn't used, from the backend's classified error (never a generic "key rejected").
const LLM_REASON: Record<string, string> = {
  authentication: 'Claude API key not accepted (401)',
  permission: 'Claude access denied for this key (403)',
  billing: 'Claude billing / credit issue',
  model_unavailable: 'Claude model unavailable to this key',
  rate_limited: 'Claude rate limit reached',
  service_unavailable: 'Claude temporarily unavailable',
  connection: "Can't reach Claude (network)",
  refusal: 'Claude declined this request',
  request_error: 'Claude request error',
}
const STEP_OF: Record<string, number> = { GREETING: 0, COLLECTING_INITIAL_CONCERN: 0, CLARIFYING_INFORMATION: 1, OPTIONAL_CONTEXTUAL_INPUT: 1, OFFERING_NEXT_STEPS: 2, REVIEWING_INTAKE: 2, COORDINATING_APPOINTMENT: 3, COMPLETED: 3 }

/** Real availability returned by the scheduling backend for this turn; selecting a time opens explicit confirmation. */
function ScheduleInChat({ r, onPick }: { r: ScheduleResult; onPick: (s: ScheduleSlot) => void }) {
  const cards = r.clinicians.filter(c => c.slots.length > 0)
  const alts = [...r.alternatives.same_clinician, ...r.alternatives.other_clinicians]
  return <div className="mt-2 space-y-2" aria-label="Appointment options">
    {r.notice&&<p className="rounded-xl border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">{r.notice}</p>}
    {cards.map(c=><ClinicianCard key={c.clinician_id} c={c} onPick={onPick} compact maxSlots={4}/>)}
    {alts.length>0&&<div className="rounded-xl border border-slate-200 bg-white p-3"><p className="text-xs font-semibold text-slate-500">Other options</p><div className="mt-1 flex flex-wrap gap-2">{alts.map(s=><button key={s.id} onClick={()=>onPick(s)} className="min-h-9 rounded-lg border border-slate-200 px-3 text-xs font-semibold hover:border-teal-300">{s.clinician_name} · {fmtDay(s.starts_at,undefined,{weekday:'short',month:'short',day:'numeric'})} {fmtRange(s.starts_at,s.ends_at).split('–')[0]}</button>)}</div></div>}
  </div>
}

export default function Assistant() {
  const go = useNavigate()
  const qc = useQueryClient()
  const health = useQuery({ queryKey: ['health'], queryFn: () => api.get<Health>('/health') })
  const intake = useIntake()
  const greeting = useQuery({ queryKey: ['assistant-greeting'], queryFn: () => api.get<{ text: string }>('/assistant/greeting') })
  const opening = (): Msg => ({ from: 'ai', text: greeting.data?.text ?? GREETING.text })
  const [messages, setMessages] = useState<Msg[]>([GREETING])
  // Personalize the opening line in place while the conversation hasn't started.
  useEffect(() => { if (greeting.data) setMessages(ms => (ms[0]?.text === GREETING.text ? [{ from: 'ai', text: greeting.data.text }, ...ms.slice(1)] : ms)) }, [greeting.data])
  const [booking, setBooking] = useState<ScheduleSlot | null>(null)
  const [ended, setEnded] = useState(false)
  const [resumedFrom, setResumedFrom] = useState<string | null>(null)
  // Reopening Talk to CuraLink shows the open conversation as it actually was (no silent carry-over).
  const restored = useRef(false)
  useEffect(() => {
    const t = intake.data?.transcript
    if (restored.current || !intake.data) return
    restored.current = true
    if (!t?.length) return
    setMessages(ms => [greeting.data ? { from: 'ai', text: greeting.data.text } : ms[0], ...t.map((x, i): Msg => ({ from: x.from, text: x.from === 'ai' && x.had_schedule ? `${x.text} (Appointment options were shown here — ask again to see current times.)` : x.text, actions: i === t.length - 1 ? x.actions : undefined, form: i === t.length - 1 ? x.form ?? null : null }))])
    setResumedFrom(intake.data.started_at ?? null)
    if (intake.data.conversation_state) setConvState(intake.data.conversation_state)
  }, [intake.data])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [emergency, setEmergency] = useState<{ category: string | null; text: string } | null>(null)
  const [drawer, setDrawer] = useState(false)
  const [drawerFocus, setDrawerFocus] = useState<string[] | null>(null)
  const [convState, setConvState] = useState<string>('GREETING')
  const [lastMode, setLastMode] = useState<IntakeReply['mode'] | null>(null)
  const [fallbackReason, setFallbackReason] = useState<IntakeReply['fallback_reason']>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const openDrawer = (focus: string[] | null) => { setDrawerFocus(focus); setDrawer(true) }
  const [handoff, setHandoff] = useState(false)
  // voice
  const [voiceState, setVoiceState] = useState<VoiceState>('IDLE')
  const [consentOpen, setConsentOpen] = useState(false)
  const [consentChecked, setConsentChecked] = useState(false)
  const [caption, setCaption] = useState('')
  const [level, setLevel] = useState(0)
  const [muted, setMuted] = useState(false)
  const [notice, setNotice] = useState('')
  const [metric, setMetric] = useState<{ ttfa_ms?: number; interrupt_ms?: number }>({})
  const lastReply = useRef('')
  const listRef = useRef<HTMLDivElement>(null)
  const voiceRef = useRef<VoiceController | null>(null)

  const history = useMemo(() => messages.slice(1).map(m => ({ role: m.from === 'user' ? 'user' as const : 'assistant' as const, text: m.text })), [messages])
  const applyReply = (reply: IntakeReply) => {
    lastReply.current = reply.assistant_message
    setMessages(m => [...m, { from: 'ai', text: reply.assistant_message, actions: reply.next_actions, tools: reply.tool_events, mode: reply.mode, schedule: reply.schedule, form: reply.form }])
    if (reply.field_updates.length === 0 && reply.form) qc.invalidateQueries({ queryKey: ['intake'] })
    if (reply.safety_state === 'EMERGENCY_GUIDANCE') setEmergency({ category: reply.safety_category, text: reply.assistant_message })
    if (reply.field_updates.length || reply.safety_state === 'EMERGENCY_GUIDANCE') qc.invalidateQueries({ queryKey: ['intake'] })
    if (reply.conversation_state) setConvState(reply.conversation_state)
    if (reply.mode !== 'safety') { setLastMode(reply.mode); setFallbackReason(reply.fallback_reason ?? null) }
    if (reply.mode === 'scripted') qc.invalidateQueries({ queryKey: ['health'] })
    // In voice mode the relevant form opens by itself; voice keeps listening while it's open.
    if (reply.form && voiceRef.current && voiceRef.current.state !== 'IDLE') openDrawer(reply.form.fields)
  }
  const runAction = (a: string, m: Msg) => {
    if (a === 'REVIEW_INTAKE') setHandoff(true)
    else if (a === 'OPEN_INTAKE_FORM') openDrawer(m.form?.fields ?? null)
    else if (a === 'ADD_MORE') inputRef.current?.focus()
    else if (a === 'END_CONVERSATION') void endConversation()
    else if (ACTIONS[a]?.to) go(ACTIONS[a].to!)
  }
  // A new conversation is a new intake session: nothing (symptoms, photos, answers) carries over.
  const startOver = async () => {
    voiceRef.current?.stop()
    qc.setQueryData(['intake'], await api.post<IntakeSnapshot>('/intake/sessions/new'))
    qc.invalidateQueries({ queryKey: ['photos'] })
    setMessages([opening()]); setConvState('GREETING'); setEmergency(null); setInput(''); setEnded(false); setResumedFrom(null)
  }
  const endConversation = async () => {
    await send("That's all for now")
    const sid = intake.data?.session_id
    if (sid) qc.setQueryData(['intake'], await api.post<IntakeSnapshot>(`/intake/sessions/${sid}/end`))
    voiceRef.current?.stop()
    setEnded(true)
  }
  const applyRef = useRef(applyReply)
  applyRef.current = applyReply
  if (!voiceRef.current) voiceRef.current = new VoiceController({
    onState: setVoiceState,
    onPartial: setCaption,
    onUserFinal: text => { setCaption(''); setMessages(m => [...m, { from: 'user', text }]) },
    onReply: r => applyRef.current(r),
    onLevel: setLevel,
    onNotice: setNotice,
    onMetric: m => setMetric(x => ({ ...x, ...m })),
    onGreeting: text => setMessages(ms => (ms.length === 1 && ms[0].from === 'ai' ? [{ from: 'ai', text }] : ms)),
    onCancelled: () => setMessages(ms => { const i = ms.map(x => x.from).lastIndexOf('ai'); return i < 0 ? ms : ms.map((x, j) => (j === i ? { ...x, interrupted: true } : x)) }),
  })
  const voice = voiceRef.current
  useEffect(() => () => voiceRef.current?.stop(), [])
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' }) }, [messages])
  useEffect(() => { if (intake.data?.conversation_state && messages.length === 1) setConvState(intake.data.conversation_state) }, [intake.data?.conversation_state]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (intake.data?.safety_state === 'EMERGENCY_GUIDANCE' && !emergency) setEmergency({ category: null, text: 'Earlier in this conversation you mentioned something that could be an emergency.' }) }, [intake.data]) // eslint-disable-line react-hooks/exhaustive-deps

  const voiceOn = !['IDLE', 'TEXT_FALLBACK', 'ERROR'].includes(voiceState)
  const send = async (q: string) => {
    if (!q.trim() || busy || emergency) return
    setError('')
    if (ended) await startOver() // typing after ending starts a fresh conversation
    if (voiceOn) { voice.sendText(q.trim()); setInput(''); return }
    setBusy(true)
    setMessages(m => [...m, { from: 'user', text: q.trim() }])
    try {
      const reply = await api.post<IntakeReply>('/intake/messages', { message: q.trim(), channel: 'text', history: history.slice(-12), client_turn_id: newTurnId() })
      setInput('')
      applyReply(reply)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Message failed. Your text is still in the box.')
      setMessages(m => m.slice(0, -1))
    } finally { setBusy(false) }
  }
  const startVoice = () => {
    if (voiceOn) { voice.stop(); return }
    setNotice('')
    if (!intake.data?.voice_consent) { setConsentChecked(false); setConsentOpen(true); return }
    void voice.start(history, opening().text)
  }
  const acknowledge = async () => {
    const sid = intake.data?.session_id
    if (sid) qc.setQueryData(['intake'], await api.post<IntakeSnapshot>(`/intake/sessions/${sid}/safety/acknowledge`))
    setEmergency(null)
  }
  const liveVoice = health.data?.integrations.voice === 'live'
  const llm = health.data?.integrations.llm
  const claudeLive = llm === 'live' && lastMode !== 'scripted'
  const reason = fallbackReason ?? health.data?.llm_detail ?? null
  const llmLabel = claudeLive ? 'Claude · live' : llm === 'fallback' ? 'Scripted assistant (no Claude key)' : `${LLM_REASON[reason?.category ?? ''] ?? 'Claude unavailable'} · scripted fallback`
  const llmTitle = reason ? `${reason.error_type ?? reason.category}${reason.http_status ? ` (HTTP ${reason.http_status})` : ''}: ${reason.message}` : undefined
  const step = STEP_OF[convState] ?? 0

  return <div className="grid min-h-[calc(100vh-9rem)] gap-5 xl:grid-cols-[1fr_340px]"><Card className="relative flex min-h-[650px] flex-col overflow-hidden"><div className="border-b border-slate-100 p-5"><div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-3"><div className="grid size-11 place-items-center rounded-xl bg-teal-700 text-white"><Icon name="AI Health Assistant"/></div><div><h1 className="font-semibold">Talk to CuraLink</h1><p className="text-sm text-slate-500">Navigation, not medical advice</p></div></div><div className="flex items-center gap-2"><span title={llmTitle}><Badge tone={claudeLive?'teal':'amber'}>{llmLabel}</Badge></span><Button variant="ghost" className="min-h-9 py-1 text-xs" onClick={startOver}>Start new conversation</Button></div></div>
      <ol className="mt-3 flex gap-1.5" aria-label="Conversation progress">{STEPS.map((label,i)=><li key={label} className="flex-1"><div className={`h-1.5 rounded-full ${i<=step?'bg-teal-600':'bg-slate-200'}`}/><span className={`mt-1 block text-[11px] ${i===step?'font-semibold text-teal-800':'text-slate-400'}`} aria-current={i===step?'step':undefined}>{label}</span></li>)}</ol><p className="mt-3 text-xs text-slate-500">CuraLink helps coordinate care and academic paperwork. It doesn’t diagnose conditions or decide medical urgency.</p>{resumedFrom&&!ended&&<p className="mt-2 rounded-lg bg-teal-50 p-2 text-xs text-teal-900" role="status">Continuing your conversation from {fmtDay(resumedFrom)}, {fmtTime(resumedFrom)}. <button className="font-semibold underline" onClick={startOver}>Start a new conversation</button> to begin fresh — earlier ones stay saved.</p>}</div>
    <div ref={listRef} className="flex-1 space-y-4 overflow-y-auto bg-slate-50/60 p-5" aria-live="polite">{messages.map((m,i)=><div key={i} className={`max-w-[85%] ${m.from==='user'?'ml-auto':''}`}><div className={`rounded-2xl px-4 py-3 text-sm leading-6 ${m.from==='user'?'bg-teal-700 text-white':'border border-slate-200 bg-white text-slate-700'}`}>{m.text}{m.interrupted&&<span className="ml-1 text-xs italic text-slate-400">(interrupted)</span>}</div>{m.tools&&m.tools.length>0&&<div className="mt-2 flex flex-wrap gap-1.5">{m.tools.map((t,j)=><span key={j} className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600">✓ {t.label}</span>)}</div>}{m.schedule&&<ScheduleInChat r={m.schedule} onPick={setBooking}/>}{i===messages.length-1&&!ended&&intake.data&&m.actions?.includes('OFFER_TEMPERATURE_INPUT')&&!intake.data.fields.some(f=>f.key==='temperature')&&<TemperatureCard snap={intake.data} onSay={t=>void send(t)} disabled={busy}/>}{i===messages.length-1&&!ended&&m.actions?.includes('OFFER_PHOTO_UPLOAD')&&<PhotoOfferCard onAdd={()=>openDrawer(['photo'])} onSay={t=>void send(t)} disabled={busy}/>}{m.actions&&m.actions.filter(a=>ACTIONS[a]).length>0&&<div className="mt-2 flex flex-wrap gap-2">{m.actions.filter(a=>ACTIONS[a]).map(a=><Button key={a} variant="secondary" className="min-h-9 py-1.5" disabled={busy&&a==='END_CONVERSATION'} onClick={()=>runAction(a,m)}>{ACTIONS[a].label}</Button>)}</div>}</div>)}{busy&&<div className="w-fit rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500" role="status">Thinking…</div>}{caption&&<div className="ml-auto max-w-[85%] rounded-2xl border border-dashed border-teal-300 px-4 py-3 text-sm italic text-teal-800">{caption}</div>}</div>
    <div className="border-t border-slate-100 p-4"><div className="mb-3 flex gap-2 overflow-x-auto">{PROMPTS.map(p=><button key={p} disabled={busy||!!emergency} onClick={()=>send(p)} className="shrink-0 rounded-full border border-slate-200 px-3 py-2 text-xs font-medium hover:border-teal-300 disabled:opacity-50">{p}</button>)}</div>{error&&<p role="alert" className="mb-2 text-sm text-rose-600">{error}</p>}{ended?<p className="mb-2 text-xs text-slate-500" role="status">This conversation has ended and is saved. Typing starts a new conversation, or <button className="font-semibold text-teal-700 underline" onClick={startOver}>start a new conversation</button>.</p>:convState==='COMPLETED'&&<p className="mb-2 text-xs text-slate-500" role="status">Wrapping up. You can still type to add something, or <button className="font-semibold text-teal-700 underline" onClick={startOver}>start a new conversation</button>.</p>}<form className="flex gap-2" onSubmit={e=>{e.preventDefault();send(input)}}><Button variant="secondary" className="shrink-0 px-3" disabled={!!emergency} onClick={()=>openDrawer(['photo'])}><span className="sr-only">Add a photo</span><Icon name="upload" size={18}/></Button><input ref={inputRef} value={input} onChange={e=>setInput(e.target.value)} disabled={!!emergency} className="input" placeholder={emergency?'Paused while safety guidance is shown':'Describe what’s going on, in your own words…'} aria-label="Message"/><Button type="submit" disabled={busy||!!emergency||!input.trim()}>Send</Button></form></div>
    {emergency&&<div role="alertdialog" aria-modal="true" aria-labelledby="sos-title" className="absolute inset-0 z-10 grid place-items-center bg-white/90 p-5 backdrop-blur-sm"><div className="max-w-md rounded-2xl border-2 border-rose-300 bg-white p-6 shadow-xl"><Badge tone="rose">{emergency.category==='crisis'?'CRISIS SUPPORT':'EMERGENCY GUIDANCE'}</Badge><h2 id="sos-title" className="mt-4 text-xl font-semibold text-rose-800">Please get help now</h2><p className="mt-3 text-sm leading-6 text-slate-700">{emergency.text}</p><ul className="mt-4 space-y-2 text-sm"><li><b>Emergency:</b> call <b>911</b> or go to the nearest emergency department</li><li><b>Suicide & Crisis Lifeline:</b> call or text <b>988</b></li></ul><p className="mt-4 text-xs text-slate-500">Routine scheduling is paused. This prototype’s safety screen is not clinically validated.</p><Button variant="secondary" className="mt-5 w-full" onClick={acknowledge}>I’m not in an emergency — continue</Button></div></div>}
  </Card>
    <div className="space-y-5"><Card className="overflow-hidden"><div className="bg-[#0c2f3b] p-5 text-white"><div className="flex items-center justify-between"><Badge>VOICE ACCESS</Badge><span className="text-[11px] font-semibold text-teal-200">{liveVoice?'Cartesia · live':'Browser speech · fallback'}</span></div><h2 className="mt-4 text-xl font-semibold">Talk to CuraLink</h2><p className="mt-2 text-sm leading-6 text-slate-300">Hands-free campus care navigation with live captions. Talk over CuraLink anytime to interrupt.</p><button onClick={startVoice} aria-label={voiceOn?'End voice conversation':'Start voice conversation'} aria-pressed={voiceOn} className={`relative mx-auto mt-6 grid size-20 place-items-center rounded-full border-4 transition focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-teal-300 ${voiceOn?'border-teal-300 bg-teal-500':'border-white/20 bg-white/10 hover:bg-white/20'}`}>{voiceOn&&<span className="absolute inset-0 rounded-full bg-teal-300/40" style={{ transform: `scale(${1 + level * 0.6})` }} aria-hidden="true"/>}<span className="relative"><Icon name="mic" size={34}/></span></button><p className="mt-3 text-center text-sm font-semibold" role="status" aria-live="polite">{voiceOn?`${STATE_LABEL[voiceState]} · tap to end`:STATE_LABEL[voiceState]}</p></div>{notice&&<div className="border-b border-slate-100 bg-amber-50 p-3 text-xs text-amber-900" role="status">{notice}</div>}{voiceOn&&(metric.ttfa_ms!==undefined||metric.interrupt_ms!==undefined)&&<p className="border-b border-slate-100 px-4 py-2 text-[11px] text-slate-500">{metric.ttfa_ms!==undefined&&`Last reply: first audio ${metric.ttfa_ms} ms after you stopped`}{metric.interrupt_ms!==undefined&&` · interrupt stopped playback in ${metric.interrupt_ms} ms`}</p>}{voiceOn&&<div className="border-b border-slate-100 bg-teal-50 p-4 text-sm" aria-live="polite"><b>Live caption</b><p className="mt-1 text-slate-600">{caption||(voiceState==='SPEAKING'?lastReply.current:'…')}</p></div>}<div className="grid grid-cols-2 gap-2 p-4"><Button variant="secondary" disabled={!voiceOn} onClick={()=>{voice.setMuted(!muted);setMuted(!muted)}}>{muted?'Unmute':'Mute audio'}</Button><Button variant="secondary" disabled={!voiceOn} onClick={()=>voice.stop()}>Switch to text</Button><Button variant="ghost" disabled={voiceState!=='SPEAKING'&&voiceState!=='THINKING'} onClick={()=>voice.interrupt()}>Interrupt</Button><Button variant="ghost" disabled={!lastReply.current||typeof speechSynthesis==='undefined'} onClick={()=>{speechSynthesis.cancel();speechSynthesis.speak(new SpeechSynthesisUtterance(lastReply.current))}}>Repeat (device voice)</Button></div></Card>
      {intake.data&&<KnowsCard snap={intake.data} onEdit={()=>openDrawer(null)} onShare={()=>setHandoff(true)}/>}
      <Card className="p-5"><h2 className="font-semibold">Official resources</h2><p className="mt-2 text-sm leading-6 text-slate-500">Demo links should be verified on Purdue’s official website before relying on hours or policies.</p><a href="https://www.purdue.edu/push/" target="_blank" rel="noreferrer" className="mt-4 block text-sm font-semibold text-teal-700 underline">Purdue University Student Health Center ↗</a></Card></div>
    {intake.data&&<IntakeDrawer snap={intake.data} open={drawer} focus={drawerFocus} onClose={()=>{setDrawer(false);qc.invalidateQueries({queryKey:['intake']})}}/>}
    {booking&&<SlotConfirmDialog slot={booking} intakeSessionId={intake.data?.session_id} purpose={intake.data?.purpose} absence={intake.data?.absence_requested} onClose={()=>setBooking(null)} onBooked={r=>{setBooking(null);setMessages(m=>[...m,{from:'ai',text:`Booked (demo): ${r.appointment.clinician_name}, ${fmtDay(r.appointment.starts_at)} ${fmtRange(r.appointment.starts_at,r.appointment.ends_at)} at ${r.appointment.clinic_name}. ${r.appointment.clinician_name} will see this appointment on their schedule.`}])}} onStale={msg=>{setBooking(null);setMessages(m=>[...m,{from:'ai',text:msg}])}}/>}
    {intake.data&&handoff&&<HandoffDialog snap={intake.data} onClose={()=>setHandoff(false)}/>}
    {consentOpen&&<div role="dialog" aria-modal="true" aria-labelledby="vc-title" className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-5"><Card className="max-w-md p-6"><Badge tone="blue">VOICE CONSENT</Badge><h2 id="vc-title" className="mt-4 text-xl font-semibold">Use your microphone?</h2><ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm leading-6 text-slate-600">{liveVoice?<li>Your speech is streamed through CuraLink’s server to Cartesia for transcription and voice replies.</li>:<li>Your browser’s built-in speech recognition turns speech into text. Depending on your browser, that may use its vendor’s service.</li>}<li>CuraLink doesn’t store raw audio or the full transcript — only details you review in “What CuraLink knows”.</li><li>Nothing spoken is confirmed until you check it. You can switch to text at any time.</li></ul><label className="mt-4 flex items-start gap-3 text-sm"><input type="checkbox" checked={consentChecked} onChange={e=>setConsentChecked(e.target.checked)} className="mt-0.5 size-5 accent-teal-700"/><span>I agree to use voice for this conversation.</span></label><div className="mt-6 flex justify-end gap-2"><Button variant="ghost" onClick={()=>setConsentOpen(false)}>Keep typing</Button><Button disabled={!consentChecked} onClick={()=>{setConsentOpen(false);void voice.start(history, opening().text).then(()=>qc.invalidateQueries({queryKey:['intake']}))}}>Start voice</Button></div></Card></div>}
  </div>
}
