import asyncio

import pytest
from starlette.websockets import WebSocketDisconnect

from app.routers import voice as voice_router
from app.services.voice_session import VoiceSession


class FakeStt:
    def __init__(self, transcripts):
        self.transcripts = list(transcripts)
        self.audio = 0
        self.q: asyncio.Queue = asyncio.Queue()

    async def send_audio(self, pcm):
        self.audio += len(pcm)
        await self.q.put("partial words")

    async def finalize(self):
        return self.transcripts.pop(0) if self.transcripts else ""

    async def partials(self):
        while True:
            yield await self.q.get()

    async def close(self):
        pass


class SlowTts:
    """Simulates delayed streaming synthesis: 20 chunks, 20 ms apart."""

    def __init__(self):
        self.cancelled: list[str] = []

    async def speak(self, text, context_id):
        for i in range(20):
            await asyncio.sleep(0.02)
            yield bytes([i]) * 4

    async def cancel(self, context_id):
        self.cancelled.append(context_id)

    async def close(self):
        pass


def test_barge_in_cancels_speech_and_drops_stale_chunks():
    """AT-21 (simulated): no audio from the interrupted turn is emitted after barge-in."""

    async def scenario():
        out: list[dict] = []
        tts = SlowTts()

        async def send(m):
            out.append(m)

        async def respond(text, history):
            return {"assistant_message": f"reply to {text}", "safety_state": "GENERAL_SUPPORT"}

        v = VoiceSession("ins_1", send, respond, FakeStt(["first question", "second question"]), tts)
        await v.start()
        await v.audio(b"\x00" * 3200)
        await v.end_of_utterance()
        await asyncio.sleep(0.07)  # a few chunks play
        interrupted_version = v.turn_version
        await v.barge_in()
        await asyncio.sleep(0.3)  # the old synthesis would have finished by now
        stale = [m for m in out if m["type"] == "assistant.audio.chunk" and m["turn_version"] == interrupted_version and out.index(m) > next(i for i, x in enumerate(out) if x["type"] == "assistant.cancelled")]
        assert stale == []
        assert tts.cancelled and v.state == "LISTENING"
        states = [m["state"] for m in out if m["type"] == "state"]
        assert states[:5] == ["LISTENING", "THINKING", "SPEAKING", "INTERRUPTED", "LISTENING"]
        # Next turn proceeds normally and completes.
        await v.end_of_utterance()
        await asyncio.sleep(0.6)
        done = [m for m in out if m["type"] == "assistant.audio.done"]
        assert len(done) == 1 and done[0]["turn_version"] == v.turn_version
        assert [m["text"] for m in out if m["type"] == "transcript.final"] == ["first question", "second question"]
        await v.close()
        assert v.history == []  # transcript memory discarded at session end

    asyncio.run(scenario())


def test_barge_in_while_thinking_discards_the_pending_reply():
    async def scenario():
        out: list[dict] = []
        gate = asyncio.Event()

        async def send(m):
            out.append(m)

        async def respond(text, history):
            await gate.wait()
            return {"assistant_message": "too late", "safety_state": "GENERAL_SUPPORT"}

        v = VoiceSession("ins_1", send, respond, FakeStt(["hello"]), SlowTts())
        await v.start()
        task = asyncio.create_task(v.end_of_utterance())
        await asyncio.sleep(0.02)
        await v.barge_in()
        gate.set()
        await task
        assert not [m for m in out if m["type"] in ("assistant.text", "assistant.audio.chunk")]

    asyncio.run(scenario())


def test_voice_session_without_key_uses_browser_mode(student):
    assert student.post("/api/v1/voice/sessions", json={"voice_consent": False}).status_code == 400
    r = student.post("/api/v1/voice/sessions", json={"voice_consent": True}).json()
    assert r["mode"] == "browser" and r["stream_path"] is None
    assert student.get("/api/v1/intake/sessions/current").json()["voice_consent"] is True


@pytest.fixture()
def live_voice(monkeypatch):
    monkeypatch.setattr(voice_router, "cartesia_enabled", lambda: True)

    async def stt():
        return FakeStt(["I have a sore throat since yesterday"])

    async def tts():
        return SlowTts()

    monkeypatch.setattr(voice_router, "stt_factory", stt)
    monkeypatch.setattr(voice_router, "tts_factory", tts)


def test_websocket_runs_full_turn_through_intake_pipeline(student, live_voice):
    student.post("/api/v1/voice/sessions", json={"voice_consent": True})
    with student.websocket_connect("/api/v1/voice/stream") as ws:
        assert ws.receive_json()["type"] == "session.started"
        ws.send_bytes(b"\x00" * 3200)
        ws.send_json({"type": "utterance.end"})
        seen = []
        while True:
            m = ws.receive_json()
            seen.append(m["type"])
            if m["type"] == "assistant.text":
                assert m["reply"]["mode"] == "scripted" and "symptoms_free_text" in m["reply"]["field_updates"]
            if m["type"] == "assistant.audio.done":
                break
        assert "transcript.final" in seen and "assistant.audio.chunk" in seen
        ws.send_json({"type": "session.end"})
    fields = {f["key"]: f for f in student.get("/api/v1/intake/sessions/current").json()["fields"]}
    assert fields["symptoms_free_text"]["provenance"] == "voice" and not fields["symptoms_free_text"]["confirmed_by_student"]


def test_websocket_rejects_wrong_role_missing_consent_and_foreign_origin(student, clinician, live_voice):
    for client, headers, code in [(clinician, {}, 4403), (student, {}, 4401), (student, {"origin": "https://evil.example"}, 4403)]:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/v1/voice/stream", headers=headers) as ws:
                ws.receive_json()
        assert exc.value.code == code
