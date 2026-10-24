"""Regression tests for the repetitive / stalled assistant (scripted fallback + Claude guards)."""

import asyncio

import pytest

from app.services import llm_gateway
from app.services.voice_session import VoiceSession


def say(c, text, **kw):
    r = c.post("/api/v1/intake/messages", json={"message": text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_conversation_advances_and_never_repeats(student):
    student.post("/api/v1/calendars/import-sample")
    msgs = ["hi", "I have a fever", "I don't know", "since yesterday", "my skin also feels really dry", "no thanks", "ok what now?", "thanks"]
    replies = [say(student, m) for m in msgs]
    texts = [r["assistant_message"] for r in replies]
    assert all(a != b for a, b in zip(texts, texts[1:])), texts
    assert len(set(texts)) == len(texts)
    states = [r["conversation_state"] for r in replies]
    assert states[0] == "COLLECTING_INITIAL_CONCERN" and "GREETING" not in states[1:]
    assert "OFFERING_NEXT_STEPS" in states
    assert {"REVIEW_INTAKE", "FIND_CARE", "ADD_MORE", "END_CONVERSATION"} <= set(replies[6]["next_actions"])


def test_fever_asks_for_temperature_once_and_respects_dont_know(student):
    r = say(student, "I have a fever")
    assert "start" in r["assistant_message"].lower() or "begin" in r["assistant_message"].lower()  # onset first
    r = say(student, "since last night")
    assert "temperature" in r["assistant_message"].lower() and r["form"] == {"fields": ["temperature"]}
    r = say(student, "I don't know, I didn't measure it")
    assert "leave out your temperature" in r["assistant_message"]
    for follow in ["still feel bad", "my head hurts too", "what now?"]:
        assert "temperature" not in say(student, follow)["assistant_message"].lower()
    snap = student.get("/api/v1/intake/sessions/current").json()
    assert "temperature" in snap["declined"] and "temperature" not in {f["key"] for f in snap["fields"]}


def test_dry_skin_offers_optional_photo_not_temperature(student):
    rs = [say(student, m) for m in ["My skin feels unusually dry", "a few days ago", "it's mostly on my hands"]]
    assert "temperature" not in " ".join(r["assistant_message"] for r in rs).lower()
    offers = [x for x in rs if "OFFER_PHOTO" in x["next_actions"]]
    assert len(offers) == 1 and "optional" in offers[0]["assistant_message"].lower()
    onset = {f["key"]: f for f in student.get("/api/v1/intake/sessions/current").json()["fields"]}["onset_text"]
    assert onset["display"] == "a few days ago" and not onset["confirmed_by_student"]


def test_bruise_offers_photo_once_and_decline_is_remembered(student):
    say(student, "I bruised my leg")
    r = say(student, "yesterday")
    assert "OFFER_PHOTO" in r["next_actions"] and r["form"] == {"fields": ["photo"]}
    r = say(student, "no thanks")
    assert "leave out a photo" in r["assistant_message"]
    for follow in ["it's a bit purple", "anything else?"]:
        rr = say(student, follow)
        assert "OFFER_PHOTO" not in rr["next_actions"] and "photo" not in rr["assistant_message"].lower()


def test_just_an_appointment_goes_straight_to_scheduling(student):
    student.post("/api/v1/calendars/import-sample")
    r = say(student, "I just need an appointment")
    assert r["conversation_state"] == "COORDINATING_APPOINTMENT" and r["next_actions"][0] == "FIND_CARE"
    assert "?" not in r["assistant_message"]  # no extra intake questions


def test_end_and_review_intents(student):
    say(student, "I have a sore throat")
    assert say(student, "can you review what you have")["conversation_state"] == "REVIEWING_INTAKE"
    assert say(student, "that's all")["conversation_state"] == "COMPLETED"


def test_state_persists_across_text_and_voice(student):
    say(student, "I have a fever")
    sid = student.get("/api/v1/intake/sessions/current").json()["session_id"]
    student.patch(f"/api/v1/intake/sessions/{sid}/consent", json={"voice_consent": True})
    r = say(student, "since Monday", channel="voice")
    assert r["conversation_state"] == "CLARIFYING_INFORMATION" and "temperature" in r["assistant_message"].lower()


def test_duplicate_turn_ids_are_processed_once(student):
    a = say(student, "I have a headache", client_turn_id="turn-abc-1")
    b = say(student, "I have a headache", client_turn_id="turn-abc-1")
    assert a == b
    fields = student.get("/api/v1/intake/sessions/current").json()["fields"]
    assert [f["display"] for f in fields if f["key"] == "symptoms_free_text"] == ["I have a headache"]


def test_new_session_restarts_cleanly(student):
    say(student, "I have a fever")
    snap = student.post("/api/v1/intake/sessions/new").json()
    assert snap["conversation_state"] == "GREETING" and snap["fields"] == []


def test_claude_duplicate_reply_is_replaced_and_context_carries_state(student, monkeypatch):
    seen = []

    async def fake(history, text, context, handle):
        seen.append(context)
        return llm_gateway.LlmTurn(text="Could you tell me more?")

    monkeypatch.setattr(llm_gateway, "available", lambda: True)
    monkeypatch.setattr(llm_gateway, "run_turn", fake)
    a = say(student, "I have a fever")
    b = say(student, "I don't know")
    assert a["mode"] == b["mode"] == "claude" and a["assistant_message"] != b["assistant_message"]
    assert "declined" in seen[-1] and "Do NOT ask" in seen[-1]


def test_rejected_key_reports_error_and_stops_calling(student, monkeypatch):
    from app.config import get_settings

    calls = []

    async def rejected(*a, **k):
        calls.append(1)
        llm_gateway.STATUS["auth_failed"] = True
        raise llm_gateway.LlmUnavailable("auth_failed")

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "bad-key")
    monkeypatch.setattr(llm_gateway, "run_turn", rejected)
    assert say(student, "hello")["mode"] == "scripted"
    assert student.get("/api/v1/health").json()["integrations"]["llm"] == "error"
    say(student, "I have a fever")
    assert len(calls) == 1  # not retried every turn


def test_voice_ignores_duplicate_finals_and_marks_interruptions():
    from tests.test_voice import FakeStt, SlowTts

    async def scenario():
        out, calls = [], []

        async def send(m):
            out.append(m)

        async def respond(text, history):
            calls.append((text, list(history)))
            return {"assistant_message": f"reply {len(calls)}", "safety_state": "GENERAL_SUPPORT"}

        v = VoiceSession("ins_1", send, respond, FakeStt([]), SlowTts())
        await v.start()
        await v.user_turn("I have a cough")
        await v.user_turn("I have a cough")  # duplicate STT final
        assert len(calls) == 1
        await asyncio.sleep(0.05)
        await v.barge_in()
        await v.user_turn("wait, also a fever")
        await asyncio.sleep(0.05)
        assert calls[1][1][-1]["text"].endswith("[interrupted by the student before finishing]")

    asyncio.run(scenario())
