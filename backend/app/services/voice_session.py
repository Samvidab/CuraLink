"""Interruption-aware voice turn manager (TRD §16 VoiceTurn state machine).

IDLE -> LISTENING -> THINKING -> SPEAKING; SPEAKING -> INTERRUPTED -> LISTENING;
any -> ERROR -> TEXT_FALLBACK. Every outbound assistant message carries the
turn_version it was produced for; a barge-in bumps the version, cancels
synthesis and drops anything still in flight for older versions.
"""

import asyncio
import base64
import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from app.services.cartesia import SttStream, TtsStream
from app.timeutil import utcnow

log = logging.getLogger("curalink.voice")

Send = Callable[[dict], Awaitable[None]]
# (transcript, history) -> reply dict (IntakeReplyOut-shaped)
Respond = Callable[[str, list[dict]], Awaitable[dict]]


class VoiceSession:
    def __init__(self, session_id: str, send: Send, respond: Respond, stt: SttStream, tts: TtsStream):
        self.session_id = session_id
        self._send = send
        self.respond = respond
        self.stt = stt
        self.tts = tts
        self.state = "IDLE"
        self.turn_version = 0
        self.turn_id: str | None = None
        self.history: list[dict] = []  # in memory only, discarded at session end
        self._speaking: asyncio.Task | None = None
        self._context: str | None = None
        self._partials: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._turn_started: float | None = None
        self._last_final: tuple[str, float] | None = None

    def set_history(self, items: list[dict]) -> None:
        """Carry over the text conversation so switching text -> voice keeps context."""
        self.history = [{"role": i["role"], "text": str(i["text"])[:2000]} for i in items if i.get("role") in ("user", "assistant") and i.get("text")][-20:]

    async def emit(self, type_: str, **data) -> None:
        await self._send({"type": type_, "session_id": self.session_id, "turn_id": self.turn_id, "turn_version": self.turn_version, "ts": utcnow().isoformat(), **data})

    async def _set(self, state: str) -> None:
        self.state = state
        await self.emit("state", state=state)

    async def start(self) -> None:
        self._partials = asyncio.create_task(self._forward_partials())
        await self.emit("session.started")
        await self._set("LISTENING")

    async def _forward_partials(self) -> None:
        async for text in self.stt.partials():
            if text:
                await self.emit("transcript.partial", text=text)

    async def audio(self, pcm: bytes) -> None:
        if self.state in ("LISTENING", "SPEAKING", "INTERRUPTED"):
            await self.stt.send_audio(pcm)

    async def barge_in(self) -> None:
        """New user speech while the assistant is talking (or thinking)."""
        if self.state not in ("SPEAKING", "THINKING"):
            return
        if self.state == "SPEAKING" and self.history and self.history[-1]["role"] == "assistant":
            # Don't treat a cut-off reply as fully delivered in later context.
            self.history[-1] = {"role": "assistant", "text": self.history[-1]["text"] + " [interrupted by the student before finishing]"}
        self.turn_version += 1
        if self._context:
            await self.tts.cancel(self._context)
        if self._speaking and not self._speaking.done():
            self._speaking.cancel()
        await self.emit("assistant.cancelled")
        await self._set("INTERRUPTED")
        await self._set("LISTENING")

    async def end_of_utterance(self) -> None:
        self._turn_started = time.perf_counter()
        text = await self.stt.finalize()
        if not text:
            return
        await self.user_turn(text)

    async def user_turn(self, text: str) -> None:
        now = time.perf_counter()
        norm = " ".join(text.lower().split())
        if self._last_final and self._last_final[0] == norm and now - self._last_final[1] < 3.0:
            return  # duplicate speech-recognition final for the same utterance
        self._last_final = (norm, now)
        async with self._lock:
            if self._turn_started is None:
                self._turn_started = time.perf_counter()
            self.turn_version += 1
            self.turn_id = f"turn_{uuid4().hex[:8]}"
            my_version = self.turn_version
            await self.emit("transcript.final", text=text)
            await self._set("THINKING")
            try:
                reply = await self.respond(text, list(self.history))
            except Exception:
                log.exception("voice turn failed")
                await self.emit("audio.error", message="Something went wrong. You can keep typing instead.")
                await self._set("TEXT_FALLBACK")
                return
            if my_version != self.turn_version:
                return  # superseded by a barge-in while thinking
            self.history += [{"role": "user", "text": text}, {"role": "assistant", "text": reply["assistant_message"]}]
            self.history = self.history[-20:]
            await self.emit("assistant.text", text=reply["assistant_message"], reply=reply)
            if reply.get("safety_state") == "EMERGENCY_GUIDANCE":
                await self.emit("safety", state="EMERGENCY_GUIDANCE", category=reply.get("safety_category"))
            self._context = f"ctx_{uuid4().hex[:10]}"
            self._speaking = asyncio.create_task(self._speak(reply["assistant_message"], self._context, my_version))

    async def _speak(self, text: str, context_id: str, version: int) -> None:
        await self._set("SPEAKING")
        seq = 0
        try:
            async for chunk in self.tts.speak(text, context_id):
                if version != self.turn_version:
                    return  # late chunk from a cancelled turn: never forwarded
                extra = {}
                if seq == 0 and self._turn_started is not None:
                    # Measured locally: end of student speech -> first synthesized audio sent.
                    extra["ttfa_ms"] = round((time.perf_counter() - self._turn_started) * 1000)
                    self._turn_started = None
                await self.emit("assistant.audio.chunk", seq=seq, data=base64.b64encode(chunk).decode(), **extra)
                seq += 1
            if version == self.turn_version:
                await self.emit("assistant.audio.done", chunks=seq)
                await self._set("LISTENING")
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("tts failed")
            await self.emit("audio.error", message="Voice playback failed; the reply is shown as text.")
            await self._set("LISTENING")

    async def close(self) -> None:
        if self._partials:
            self._partials.cancel()
        if self._speaking and not self._speaking.done():
            self._speaking.cancel()
        self.history.clear()
        for closer in (self.stt.close, self.tts.close):
            try:
                await closer()
            except Exception:
                pass
        await self.emit("session.ended")
