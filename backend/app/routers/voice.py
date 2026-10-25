"""Voice: consent-gated session setup and the streaming WebSocket.

mode="cartesia": browser streams 16 kHz PCM to /api/v1/voice/stream; the server
relays it to Cartesia STT, runs the same intake pipeline as text, and streams
Cartesia TTS audio back tagged with turn_version (stale audio is dropped).
mode="browser": no Cartesia key configured; the client uses the browser's own
speech APIs where available and POSTs transcripts to /intake/messages.
"""

import json
import logging
import secrets
import threading
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app import db as dbmod
from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import User
from app.routers.intake import tool_handler_for
from app.schemas import IntakeReplyOut, VoiceSessionIn, VoiceSessionOut
from app.security import require_student, user_for_token
from app.services import audit, intake_service, names
from app.services.cartesia import CartesiaStt, CartesiaTts
from app.services.voice_session import VoiceSession

log = logging.getLogger("curalink.voice")
router = APIRouter(prefix="/api/v1", tags=["voice"])

# Swappable in tests (no network).
stt_factory = CartesiaStt.open
tts_factory = CartesiaTts.open


def cartesia_enabled() -> bool:
    return bool(get_settings().cartesia_api_key)


# Single-use, 60-second tickets for the voice WebSocket when the page is served from another host (e.g. Vercel,
# which can't proxy WebSockets, so the browser connects to the API host directly and the session cookie isn't sent).
_tickets: dict[str, tuple[str, float]] = {}
_tickets_lock = threading.Lock()
TICKET_TTL = 60


def issue_ticket(user_id: str) -> str:
    t = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _tickets_lock:
        for k in [k for k, (_, exp) in _tickets.items() if exp < now]:
            _tickets.pop(k, None)
        _tickets[t] = (user_id, now + TICKET_TTL)
    return t


def redeem_ticket(t: str | None) -> str | None:
    if not t:
        return None
    with _tickets_lock:
        entry = _tickets.pop(t, None)
    return entry[0] if entry and entry[1] >= time.monotonic() else None


@router.post("/voice/sessions", response_model=VoiceSessionOut)
def create_voice_session(body: VoiceSessionIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> VoiceSessionOut:
    if not body.voice_consent:
        raise ApiError(400, "VOICE_CONSENT_REQUIRED", "Voice mode needs your consent. You can keep using text instead.")
    s = get_settings()
    sess = intake_service.current_session(db, user)
    if not sess.voice_consent:
        sess.voice_consent = True
        audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="CONSENT_GRANTED", object_type="intake_session", object_id=sess.id, detail="voice_consent")
        db.commit()
    live = cartesia_enabled()
    return VoiceSessionOut(
        session_id=sess.id,
        mode="cartesia" if live else "browser",
        stream_path="/api/v1/voice/stream" if live else None,
        stream_url=(f"{s.public_api_url.rstrip('/').replace('https://', 'wss://', 1).replace('http://', 'ws://', 1)}/api/v1/voice/stream?ticket={issue_ticket(user.id)}"
                    if live and s.public_api_url else None),
        input={"encoding": "pcm_s16le", "sample_rate": s.voice_input_sample_rate, "chunk_ms": 100},
        output={"encoding": "pcm_s16le", "sample_rate": s.voice_output_sample_rate},
        note="Cartesia streaming voice." if live else "Cartesia isn't configured on this server; using your browser's speech features where available. Audio stays on your device.",
    )


def _origin_allowed(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if origin is None:
        return True  # non-browser client; still needs a valid session cookie
    host = ws.headers.get("host", "")
    return origin in get_settings().cors_origin_list or origin.split("://", 1)[-1] == host


@router.websocket("/voice/stream")
async def voice_stream(ws: WebSocket) -> None:
    gen = dbmod.get_db()
    db = next(gen)
    try:
        user = user_for_token(db, ws.cookies.get(get_settings().session_cookie_name))
        if user is None:
            uid = redeem_ticket(ws.query_params.get("ticket"))
            user = db.get(User, uid) if uid else None
        if not _origin_allowed(ws) or user is None or user.role != "student":
            await ws.close(code=4403)
            return
        sess = intake_service.current_session(db, user)
        if not sess.voice_consent:
            await ws.close(code=4401)
            return
        if not cartesia_enabled():
            await ws.close(code=4404)
            return
        await ws.accept()
        try:
            stt, tts = await stt_factory(), await tts_factory()
        except Exception:
            log.exception("cartesia connect failed")
            await ws.send_json({"type": "audio.error", "message": "Voice service unavailable. Switched to text.", "fallback": "text"})
            await ws.close()
            return

        async def respond(text: str, history: list[dict]) -> dict:
            current = intake_service.current_session(db, user)
            reply = await intake_service.handle_message(db, user, current, text, "voice", history, tool_handler_for(db, user), f"v{uuid4().hex[:10]}")
            return IntakeReplyOut(**reply.__dict__).model_dump()

        voice = VoiceSession(sess.id, ws.send_json, respond, stt, tts)
        await voice.start()
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    await voice.audio(msg["bytes"])
                    continue
                data = json.loads(msg.get("text") or "{}")
                kind = data.get("type")
                if kind == "barge_in":
                    await voice.barge_in()
                elif kind == "utterance.end":
                    await voice.end_of_utterance()
                elif kind == "text" and data.get("text"):
                    await voice.barge_in()
                    await voice.user_turn(str(data["text"])[:2000])
                elif kind == "history" and isinstance(data.get("items"), list):
                    voice.set_history(data["items"])
                elif kind == "greet":
                    await voice.greet(names.greeting(user))
                elif kind == "session.end":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            try:
                await voice.close()
            except Exception:
                pass
    finally:
        gen.close()
