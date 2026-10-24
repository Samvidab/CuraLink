import pytest

from app.services import llm_gateway, safety


def _say(client, text, **kw):
    r = client.post("/api/v1/intake/messages", json={"message": text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _snap(client):
    return client.get("/api/v1/intake/sessions/current").json()


# ---- safety ------------------------------------------------------------------

@pytest.mark.parametrize("text,category", [
    ("I have crushing chest pain and need an appointment", "emergency"),
    ("I can't breathe properly", "emergency"),
    ("bleeding that won't stop after a cut", "emergency"),
    ("I want to kill myself", "crisis"),
])
def test_high_risk_messages_halt_routine_flow(student, text, category):
    """AT-12."""
    r = _say(student, text)
    assert r["safety_state"] == "EMERGENCY_GUIDANCE" and r["safety_category"] == category
    assert r["next_actions"] == ["EMERGENCY_HELP"] and "FIND_CARE" not in r["next_actions"]
    assert ("988" if category == "crisis" else "911") in r["assistant_message"]
    assert r["field_updates"] == []  # nothing extracted while the safety notice is up
    assert _snap(student)["safety_state"] == "EMERGENCY_GUIDANCE"


def test_safety_acknowledgement_is_explicit_and_audited(student):
    sid = _say(student, "chest pain")["session_id"]
    # Routine requests stay paused (any channel) until acknowledged.
    assert _say(student, "ok can I book an appointment")["mode"] == "safety"
    assert student.post(f"/api/v1/intake/sessions/{sid}/safety/acknowledge").json()["safety_state"] == "GENERAL_SUPPORT"
    acts = [a["event_type"] for a in student.get("/api/v1/students/me/activity").json()]
    assert "SAFETY_ESCALATION_SHOWN" in acts and "SAFETY_NOTICE_ACKNOWLEDGED" in acts
    # The log never carries the student's words.
    assert "chest" not in str(student.get("/api/v1/students/me/activity").json()).lower()


def test_output_guard_blocks_diagnosis_and_reassurance():
    for bad in ["It sounds like you have strep throat.", "You probably have the flu.", "Take 400 mg of ibuprofen.", "This is probably not serious."]:
        assert safety.guard_output(bad)[1]
    for ok in ["I can show demo appointment times that fit your classes.", "When did it start?"]:
        assert not safety.guard_output(ok)[1]


# ---- never invent ------------------------------------------------------------

def test_scripted_extraction_uses_students_words_and_stays_unconfirmed(student):
    r = _say(student, "I've had a sore throat and a fever of 101.2 F since yesterday")
    assert r["mode"] == "scripted" and set(r["field_updates"]) == {"temperature", "onset_text", "symptoms_free_text"}
    fields = {f["key"]: f for f in _snap(student)["fields"]}
    assert fields["temperature"]["value"] == {"value": 101.2, "unit": "F"}
    assert fields["onset_text"]["display"] == "since yesterday"
    assert fields["symptoms_free_text"]["provenance"] == "text"
    assert not any(f["confirmed_by_student"] for f in fields.values())


def test_missing_unit_is_asked_not_guessed(student):
    """AT-22."""
    r = _say(student, "my temperature was 101 and I feel awful")
    assert "°F or °C" in r["assistant_message"]
    snap = _snap(student)
    assert "temperature" not in {f["key"] for f in snap["fields"]}
    assert "temperature" in snap["missing_fields"]
    sid = snap["session_id"]
    assert "temperature" not in student.post(f"/api/v1/intake/sessions/{sid}/skip", json={"key": "temperature"}).json()["missing_fields"]


@pytest.mark.parametrize("value,code", [({"value": 101}, "INVALID_FIELD"), ({"value": 250, "unit": "F"}, "INVALID_FIELD"), ({"value": "warm", "unit": "C"}, "INVALID_FIELD")])
def test_form_temperature_validation(student, value, code):
    sid = _snap(student)["session_id"]
    r = student.patch(f"/api/v1/intake/sessions/{sid}/fields", json={"fields": [{"key": "temperature", "value": value}]})
    assert r.status_code == 422 and r.json()["code"] == code


def test_form_entries_are_confirmed_and_corrections_reset_confirmation(student):
    sid = _snap(student)["session_id"]
    snap = student.patch(f"/api/v1/intake/sessions/{sid}/fields", json={"fields": [{"key": "temperature", "value": {"value": 38.1, "unit": "c", "measured_at": "this morning"}}]}).json()
    t = snap["fields"][0]
    assert t["confirmed_by_student"] and t["provenance"] == "form" and t["display"] == "38.1°C (measured this morning)"
    _say(student, "actually it was 38.6 C")
    t = next(f for f in _snap(student)["fields"] if f["key"] == "temperature")
    assert t["value"]["value"] == 38.6 and not t["confirmed_by_student"]


def test_voice_messages_require_voice_consent(student):
    r = student.post("/api/v1/intake/messages", json={"message": "hello", "channel": "voice"})
    assert r.status_code == 403 and r.json()["code"] == "VOICE_CONSENT_REQUIRED"
    sid = _snap(student)["session_id"]
    student.patch(f"/api/v1/intake/sessions/{sid}/consent", json={"voice_consent": True})
    assert _say(student, "hello", channel="voice")["safety_state"] == "GENERAL_SUPPORT"


def test_appointment_intent_offers_actions(student):
    assert "IMPORT_CALENDAR" in _say(student, "I need a doctor's appointment")["next_actions"]
    student.post("/api/v1/calendars/import-sample")
    r = _say(student, "can I book an appointment")
    assert "FIND_CARE" in r["next_actions"] and "IMPORT_CALENDAR" not in r["next_actions"]


# ---- Claude path (stubbed: no network in tests) ------------------------------

def test_model_proposals_are_validated_and_never_guessed(student, monkeypatch):
    calls = {}

    async def fake_turn(history, text, context, handle_tool):
        calls["ctx"] = context
        slots = await handle_tool("get_ranked_slots", {"appointment_type": "routine_checkup"})
        calls["slots"] = slots
        return llm_gateway.LlmTurn(
            text="It sounds like you have the flu.",
            tool_events=[{"tool": "get_ranked_slots", "label": "Comparing eligible slots", "status": "ok"}],
            proposed_fields=[
                {"key": "temperature", "text": "", "temperature_value": 39.0, "temperature_unit": "unstated"},
                {"key": "symptoms_free_text", "text": "achy and tired", "temperature_value": None, "temperature_unit": "unstated"},
                {"key": "not_a_field", "text": "x", "temperature_value": None, "temperature_unit": "unstated"},
            ],
        )

    monkeypatch.setattr(llm_gateway, "available", lambda: True)
    monkeypatch.setattr(llm_gateway, "run_turn", fake_turn)
    student.post("/api/v1/calendars/import-sample")
    r = _say(student, "I'm achy and tired, temp 39")
    assert r["mode"] == "claude"
    assert r["assistant_message"] == safety.SAFE_REPLACEMENT  # diagnosis replaced
    assert r["field_updates"] == ["symptoms_free_text"]  # unit-less temperature and unknown key dropped
    assert '"source_mode": "demo"' in calls["slots"] and "Demo Student Health Clinic" in calls["slots"]
    assert "LLM_OUTPUT_GUARDED" in [a["event_type"] for a in student.get("/api/v1/students/me/activity").json()]


def test_model_failure_falls_back_to_scripted(student, monkeypatch):
    async def boom(*a, **k):
        raise llm_gateway.LlmUnavailable("status_500")

    monkeypatch.setattr(llm_gateway, "available", lambda: True)
    monkeypatch.setattr(llm_gateway, "run_turn", boom)
    assert _say(student, "I have a headache since this morning")["mode"] == "scripted"


def test_safety_runs_before_the_model(student, monkeypatch):
    monkeypatch.setattr(llm_gateway, "available", lambda: True)

    async def never(*a, **k):
        raise AssertionError("model must not be called for emergencies")

    monkeypatch.setattr(llm_gateway, "run_turn", never)
    assert _say(student, "I think I'm having a stroke")["mode"] == "safety"


def test_unknown_tools_are_not_offered_to_the_model():
    assert llm_gateway.ALLOWED_TOOLS == {"propose_intake_fields", "get_ranked_slots", "list_calendar_events", "request_ui_action"}
    assert not {"book_appointment", "send_email", "sign_document", "approve_provider", "grant_excuse"} & llm_gateway.ALLOWED_TOOLS


# ---- handoff -----------------------------------------------------------------

def _book(student):
    student.post("/api/v1/calendars/import-sample")
    student.post("/api/v1/appointments/confirm", json={"slot_id": "slot_04", "student_approved": True, "idempotency_key": "handoff-key-1"})
    return student.get("/api/v1/students/me/encounters").json()[0]


def test_handoff_requires_confirmation_and_is_scoped(student, clinician, login):
    """AT-23/AT-24: only confirmed, explicitly selected fields reach only the assigned clinician."""
    enc = _book(student)
    sid = _snap(student)["session_id"]
    _say(student, "sore throat since yesterday, 100.4 F")
    body = {"student_authorized": True, "field_keys": ["symptoms_free_text", "temperature"]}
    r = student.post(f"/api/v1/encounters/{enc['id']}/handoff", json=body)
    assert r.status_code == 409 and r.json()["code"] == "FIELD_NOT_CONFIRMED"
    for k in ("symptoms_free_text", "temperature", "onset_text"):
        student.post(f"/api/v1/intake/sessions/{sid}/fields/{k}/confirm", json={"confirmed": True})
    assert student.post(f"/api/v1/encounters/{enc['id']}/handoff", json={**body, "student_authorized": False}).status_code == 400
    pkt = student.post(f"/api/v1/encounters/{enc['id']}/handoff", json=body).json()
    assert pkt["version"] == 1 and pkt["field_keys"] == ["symptoms_free_text", "temperature"]

    view = clinician.get(f"/api/v1/clinician/encounters/{enc['id']}/intake").json()
    assert view["status"] == "SHARED" and {f["key"] for f in view["fields"]} == {"symptoms_free_text", "temperature"}  # onset not selected
    assert view["consent"]["photo_shared"] is False and view["consent"]["voice_transcript_shared"] is False
    rows = {e["id"]: e for e in clinician.get("/api/v1/clinician/encounters").json()}
    assert rows[enc["id"]]["status"] == "CLINICIAN_REVIEW"
    # Not Dr. Hale's patient; and students can't use clinician endpoints.
    hale, _ = login("dr.hale@clinic.example.com")
    assert hale.get(f"/api/v1/clinician/encounters/{enc['id']}/intake").status_code == 403
    assert student.get(f"/api/v1/clinician/encounters/{enc['id']}/intake").status_code == 403

    # Withdrawal hides the packet from the clinician.
    assert student.post(f"/api/v1/handoffs/{pkt['packet_id']}/withdraw").json()["status"] == "WITHDRAWN"
    assert clinician.get(f"/api/v1/clinician/encounters/{enc['id']}/intake").json() == {
        "encounter_id": enc["id"], "status": "WITHDRAWN", "packet_id": pkt["packet_id"], "version": 1, "shared_at": None, "fields": [], "consent": {},
        "attachments": [], "annotations": {},
    }


def test_shared_session_is_closed_to_edits(student):
    enc = _book(student)
    sid = _snap(student)["session_id"]
    student.patch(f"/api/v1/intake/sessions/{sid}/fields", json={"fields": [{"key": "symptoms_free_text", "value": {"text": "cough"}}]})
    student.post(f"/api/v1/encounters/{enc['id']}/handoff", json={"student_authorized": True, "field_keys": ["symptoms_free_text"]})
    r = student.patch(f"/api/v1/intake/sessions/{sid}/fields", json={"fields": [{"key": "requests", "value": {"text": "x"}}]})
    assert r.status_code == 409
    assert _snap(student)["session_id"] != sid  # a fresh session starts for new details
