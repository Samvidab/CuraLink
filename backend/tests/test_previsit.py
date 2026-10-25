"""Contextual intake, conversational scheduling, session-based pre-visit summaries (regression + acceptance)."""

from datetime import UTC, datetime

from app import db as dbmod
from app.models import Appointment, ClinicianProfile, HandoffPacket, IntakeSession
from app.services import availability, llm_gateway
from tests.conftest import RIVERA_MON_1030, _client, slot

ME = "/api/v1/intake/sessions/current"


def say(c, text, **kw):
    r = c.post("/api/v1/intake/messages", json={"message": text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def snap(c):
    return c.get(ME).json()


def new_conversation(c):
    return c.post("/api/v1/intake/sessions/new").json()["session_id"]


def confirm_all(c):
    s = snap(c)
    for f in s["fields"]:
        c.post(f"/api/v1/intake/sessions/{s['session_id']}/fields/{f['key']}/confirm", json={"confirmed": True})
    return snap(c)


def submit(c, **kw):
    s = snap(c)
    body = {"student_authorized": True, "field_keys": [f["key"] for f in s["fields"] if f["confirmed_by_student"]], **kw}
    r = c.post(f"/api/v1/intake/sessions/{s['session_id']}/summary", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def book(c, slot_id=RIVERA_MON_1030, key="previsit-book-01", **kw):
    r = c.post("/api/v1/appointments/confirm", json={"slot_id": slot_id, "student_approved": True, "idempotency_key": key, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def set_started(session_id, when):
    db = next(dbmod.get_db())
    db.get(IntakeSession, session_id).created_at = when
    db.commit()


# ---- contextual intake ---------------------------------------------------------------------------------------

def test_fever_offers_temperature_input_and_stores_only_confirmed_measurements(student):
    r = say(student, "I've been feeling feverish since yesterday")
    assert "OFFER_TEMPERATURE_INPUT" in r["next_actions"] and r["form"] == {"fields": ["temperature"]}
    assert "temperature" not in {f["key"] for f in snap(student)["fields"]}  # "feeling feverish" is not a measurement
    sid = snap(student)["session_id"]
    student.patch(f"/api/v1/intake/sessions/{sid}/fields", json={"fields": [{"key": "temperature", "value": {"value": 100.8, "unit": "F"}}]})
    t = {f["key"]: f for f in snap(student)["fields"]}["temperature"]
    assert t["display"] == "100.8°F" and t["confirmed_by_student"] and t["provenance"] == "form"
    assert "OFFER_TEMPERATURE_INPUT" not in say(student, "what now?")["next_actions"]


def test_skin_concern_offers_optional_photo_immediately(student):
    r = say(student, "I have a rash on my arm")
    assert "OFFER_PHOTO_UPLOAD" in r["next_actions"] and "OFFER_TEMPERATURE_INPUT" not in r["next_actions"]
    assert "optional" in r["assistant_message"].lower()


def test_injury_asks_relevant_question_and_offers_photo_only_for_visible_change(student):
    r = say(student, "I twisted my ankle")
    assert r["conversation_state"] == "CLARIFYING_INFORMATION" and not ({"OFFER_TEMPERATURE_INPUT", "OFFER_PHOTO_UPLOAD"} & set(r["next_actions"]))
    r = say(student, "it's swollen and bruised")
    assert "OFFER_PHOTO_UPLOAD" in r["next_actions"] and "temperature" not in r["assistant_message"].lower()
    assert "onset_text" not in {f["key"] for f in snap(student)["fields"]}  # a description isn't a start time


def test_general_appointment_goes_straight_to_scheduling(student):
    student.post("/api/v1/calendars/import-sample")
    r = say(student, "I just want to book a checkup")
    assert r["schedule"] and r["form"] is None and r["next_actions"] == ["FIND_CARE"]
    assert r["schedule"]["appointment_type"] == "routine_checkup"


def test_symptom_after_browsing_times_is_not_swallowed_by_scheduling(student):
    """Regression (ee5ce0c): COORDINATING_APPOINTMENT made every later day/time word a slot search."""
    student.post("/api/v1/calendars/import-sample")
    assert say(student, "Which doctors are available?")["schedule"]
    r = say(student, "I have had a fever since this morning")
    assert r["schedule"] is None and "OFFER_TEMPERATURE_INPUT" in r["next_actions"]


def test_dont_know_and_skip_are_remembered_separately(student):
    say(student, "I have a fever")
    say(student, "I haven't measured it")
    say(student, "I have a rash too")
    say(student, "skip")  # the follow-up asked next
    s = snap(student)
    assert s["unknown"] == ["temperature"] and s["declined"]
    assert all("OFFER_TEMPERATURE_INPUT" not in say(student, m)["next_actions"] for m in ["still hot", "what now?"])


def test_claude_mode_gets_the_same_components_and_is_told_what_is_on_screen(student, monkeypatch):
    seen = {}

    async def fake_turn(history, text, context, handle_tool):
        seen["ctx"] = context
        return llm_gateway.LlmTurn(text="Have you been able to take your temperature?", tool_events=[], proposed_fields=[])

    monkeypatch.setattr(llm_gateway, "available", lambda: True)
    monkeypatch.setattr(llm_gateway, "run_turn", fake_turn)
    r = say(student, "I've been feeling feverish since yesterday")
    assert r["mode"] == "claude" and "OFFER_TEMPERATURE_INPUT" in r["next_actions"] and r["form"] == {"fields": ["temperature"]}
    assert "ON SCREEN under your reply: a temperature entry card" in seen["ctx"]
    r = say(student, "I also have a rash on my arm")
    assert "OFFER_PHOTO_UPLOAD" in r["next_actions"] and "optional photo upload card" in seen["ctx"]


def test_reopening_shows_the_transcript_and_does_not_repeat_or_duplicate(app, student):
    say(student, "I have a fever")
    sid = snap(student)["session_id"]
    again = _client(app)
    again.post("/api/v1/auth/demo/login", json={"persona": "student"})  # new login, same conversation
    s = snap(again)
    assert s["session_id"] == sid and [t["from"] for t in s["transcript"]] == ["user", "ai"]
    assert "OFFER_TEMPERATURE_INPUT" not in say(again, "hello again")["next_actions"]
    db = next(dbmod.get_db())
    assert db.query(IntakeSession).filter(IntakeSession.student_id == "demo-student-1").count() == 1


# ---- conversational scheduling -------------------------------------------------------------------------------

def test_conversational_scheduling_requests_use_real_availability(student):
    student.post("/api/v1/calendars/import-sample")
    names = lambda r: {c["name"] for c in r["schedule"]["clinicians"] if c["slots"]}  # noqa: E731
    for msg in ["Show me all clinicians.", "Which doctors are available?"]:
        assert {"Dr. Avery Rivera", "Dr. Morgan Hale"} <= names(say(student, msg))
    assert names(say(student, "When is Dr. Hale free?")) == {"Dr. Morgan Hale"}
    assert names(say(student, "Can I see Dr. Rivera?")) == {"Dr. Avery Rivera"}
    r = say(student, "Who has the earliest appointment?")
    assert r["schedule"]["sort"] == "earliest" and r["schedule"]["options"][0]["starts_at"] == min(o["starts_at"] for o in r["schedule"]["options"])
    r = say(student, "Can I get an appointment tomorrow afternoon?")
    assert all(s["starts_at"].startswith("2026-10-27") and int(s["starts_at"][11:13]) >= 12 for c in r["schedule"]["clinicians"] for s in c["slots"])


def test_absence_note_request_is_recorded_as_a_request_on_the_booking(student, clinician):
    student.post("/api/v1/calendars/import-sample")
    r = say(student, "I need to see a doctor about an absence note")
    assert r["schedule"]
    out = book(student)
    assert out["absence_requested"] and out["purpose"] == "I need to see a doctor about an absence note" and out["intake_session_id"] == snap(student)["session_id"]
    detail = clinician.get(f"/api/v1/clinician/encounters/{out['case_id']}").json()
    assert detail["absence_requested"] and detail["purpose"].startswith("I need to see a doctor")
    assert clinician.get("/api/v1/clinician/absence-cases").json() == [] or all(c["student_name"] != "Sam Lee" for c in clinician.get("/api/v1/clinician/absence-cases").json())


def test_booking_persists_across_logout_and_repeated_confirms_do_not_duplicate(app, student):
    student.post("/api/v1/calendars/import-sample")
    a = book(student, key="dup-check-0001")
    b = book(student, key="dup-check-0001")
    assert a["appointment_id"] == b["appointment_id"]
    other = student.post("/api/v1/appointments/confirm", json={"slot_id": RIVERA_MON_1030, "student_approved": True, "idempotency_key": "dup-check-0002"})
    assert other.status_code == 409  # same time again from another card: already booked, nothing duplicated
    student.post("/api/v1/auth/logout")
    again = _client(app)
    again.post("/api/v1/auth/demo/login", json={"persona": "student"})
    mine = [x for x in again.get("/api/v1/appointments/me").json() if x["state"] == "DEMO_CONFIRMED"]
    assert [(x["id"], x["clinician_name"]) for x in mine] == [(a["appointment_id"], "Dr. Avery Rivera")]


def test_old_demo_database_without_clinician_hours_is_upgraded_safely(student):
    """Regression: databases created before clinician-aware scheduling had no profiles, so no cards could appear."""
    db = next(dbmod.get_db())
    student.post("/api/v1/calendars/import-sample")
    book(student)
    from app.models import AvailabilityException, AvailabilityRule, CalendarEvent

    events = db.query(CalendarEvent).count()
    db.query(AvailabilityException).delete()
    db.query(AvailabilityRule).delete()
    db.query(ClinicianProfile).delete()
    db.query(Appointment).update({Appointment.clinician_id: None})
    db.commit()
    assert say(student, "Which doctors are available?")["schedule"]["clinicians"] == []
    out = availability.ensure_demo_data(db)
    assert set(out["clinicians_configured"]) >= {"demo-clinician-1", "demo-clinician-2"} and out["appointments_backfilled"] == 4  # Sam's + 3 seeded
    assert availability.ensure_demo_data(db) == {"clinicians_configured": [], "appointments_backfilled": 0}  # idempotent
    assert db.query(CalendarEvent).count() == events  # student calendars untouched
    assert {c["name"] for c in say(student, "Show me all clinicians")["schedule"]["clinicians"]} >= {"Dr. Avery Rivera", "Dr. Morgan Hale"}


# ---- pre-visit summaries & session history -------------------------------------------------------------------

def _two_sessions(student):
    """Session 1: rash + photo (approved before booking). Session 2: fever 100.8°F + absence request, booked with Rivera."""
    student.post("/api/v1/calendars/import-sample")
    s1 = new_conversation(student)
    say(student, "I have a rash on my arm")
    photo = student.post("/api/v1/vision/demo-images/red_area?consent=true").json()
    confirm_all(student)
    p1 = submit(student, attachment_ids=[photo["id"]])
    assert p1["encounter_id"] is None  # approved before booking: waits for the next appointment
    student.post(f"/api/v1/intake/sessions/{s1}/end")
    s2 = new_conversation(student)
    say(student, "I've had a fever and headache since yesterday. I missed class and want to discuss an absence note.")
    student.patch(f"/api/v1/intake/sessions/{s2}/fields", json={"fields": [{"key": "temperature", "value": {"value": 100.8, "unit": "F"}}]})
    confirm_all(student)
    p2 = submit(student, include_purpose=True, include_absence_request=True)
    out = book(student, key="two-sessions-01")
    return s1, s2, p1, p2, photo, out


def test_summaries_are_per_session_and_attach_when_booking(student, clinician):
    s1, s2, p1, p2, photo, out = _two_sessions(student)
    assert s1 != s2 and out["intake_session_id"] == s2
    view = clinician.get(f"/api/v1/clinician/encounters/{out['case_id']}/intake").json()
    assert view["status"] == "SHARED" and view["session"]["session_id"] == s2  # latest approved summary, prominently
    summ = view["summary"]
    assert summ["measurements"][0]["display"] == "100.8°F" and summ["absence_documentation"] == "REQUESTED"
    assert summ["photos"] == [] and "rash" not in " ".join(summ["symptoms"]).lower()  # nothing leaks from session 1
    hist = clinician.get(f"/api/v1/clinician/encounters/{out['case_id']}/previsit-history").json()
    sessions = [s for g in hist["groups"] for s in g["sessions"]]
    assert [s["session_id"] for s in sessions] == [s2, s1] and hist["latest_session_id"] == s2  # newest first, both kept
    assert [s["label"] for s in sessions] == ["Session 2", "Session 1"]
    one = sessions[1]["summary"]
    assert [p["attachment_id"] for p in one["photos"]] == [photo["id"]] and one["measurements"] == []  # photo stays with session 1
    assert clinician.get(f"/api/v1/clinician/encounters/{out['case_id']}/attachments/{photo['id']}").status_code == 200


def test_sessions_group_by_local_start_date_newest_first(student, clinician):
    s1, s2, *_rest, out = _two_sessions(student)
    s3 = new_conversation(student)
    say(student, "I have a sore throat")
    confirm_all(student)
    submit(student, encounter_id=out["case_id"])  # explicitly for the existing appointment
    set_started(s1, datetime(2026, 10, 22, 19, 15, tzinfo=UTC))  # Oct 22, 3:15 PM Indianapolis
    set_started(s2, datetime(2026, 10, 24, 15, 30, tzinfo=UTC))  # Oct 24, 11:30 AM
    set_started(s3, datetime(2026, 10, 25, 1, 30, tzinfo=UTC))  # Oct 24, 9:30 PM local (already Oct 25 in UTC)
    hist = clinician.get(f"/api/v1/clinician/encounters/{out['case_id']}/previsit-history").json()
    assert [(g["date"], [s["session_id"] for s in g["sessions"]]) for g in hist["groups"]] == [("2026-10-24", [s3, s2]), ("2026-10-22", [s1])]


def test_unconfirmed_and_declined_details_are_never_shared(student, clinician):
    student.post("/api/v1/calendars/import-sample")
    say(student, "I have a fever")
    say(student, "I haven't measured it")
    s = snap(student)
    r = student.post(f"/api/v1/intake/sessions/{s['session_id']}/summary", json={"student_authorized": True, "field_keys": ["symptoms_free_text"]})
    assert r.status_code == 409 and r.json()["code"] == "FIELD_NOT_CONFIRMED"
    confirm_all(student)
    submit(student)
    out = book(student, key="declined-01")
    summ = clinician.get(f"/api/v1/clinician/encounters/{out['case_id']}/intake").json()["summary"]
    assert summ["measurements"] == [] and summ["not_known"] == ["Temperature"]


def test_only_assigned_clinicians_and_the_owner_see_summaries(app, student, clinician, login):
    s1, s2, p1, p2, photo, out = _two_sessions(student)
    hale, _ = login("dr.hale@clinic.example.com")
    assert hale.get(f"/api/v1/clinician/encounters/{out['case_id']}/intake").status_code == 403
    assert hale.get(f"/api/v1/clinician/encounters/{out['case_id']}/previsit-history").status_code == 403
    jordan, _ = login("jordan.kim@students.example.com")
    assert jordan.post(f"/api/v1/intake/sessions/{s2}/summary", json={"student_authorized": True, "field_keys": []}).status_code == 404
    assert jordan.get("/api/v1/students/me/previsit-summaries").json() == []
    assert jordan.post(f"/api/v1/handoffs/{p2['packet_id']}/withdraw").status_code == 404
    assert {x["session_id"] for x in student.get("/api/v1/students/me/previsit-summaries").json()} == {s1, s2}


def test_withdrawal_applies_to_subsequent_access_and_is_audited(student, clinician):
    s1, s2, p1, p2, photo, out = _two_sessions(student)
    assert student.post(f"/api/v1/handoffs/{p1['packet_id']}/withdraw").json()["status"] == "WITHDRAWN"
    assert clinician.get(f"/api/v1/clinician/encounters/{out['case_id']}/attachments/{photo['id']}").status_code == 403
    hist = clinician.get(f"/api/v1/clinician/encounters/{out['case_id']}/previsit-history").json()
    one = next(s for g in hist["groups"] for s in g["sessions"] if s["session_id"] == s1)
    assert one["status"] == "WITHDRAWN" and one["summary"] is None
    assert "INTAKE_WITHDRAWN" in [a["event_type"] for a in student.get("/api/v1/students/me/activity").json()]


def test_clinician_view_matches_latest_authorized_version_exactly(student, clinician):
    *_ignored, out = _two_sessions(student)
    s = snap(student)
    student.patch(f"/api/v1/intake/sessions/{s['session_id']}/fields", json={"fields": [{"key": "temperature", "value": {"value": 101.2, "unit": "F"}}]})
    before = clinician.get(f"/api/v1/clinician/encounters/{out['case_id']}/intake").json()
    assert before["summary"]["measurements"][0]["display"] == "100.8°F"  # an unsubmitted correction is invisible
    v2 = submit(student, include_purpose=True, include_absence_request=True)
    after = clinician.get(f"/api/v1/clinician/encounters/{out['case_id']}/intake").json()
    db = next(dbmod.get_db())
    stored = db.get(HandoffPacket, v2["packet_id"])
    assert after["version"] == 2 and after["summary"] == stored.summary and after["summary"]["measurements"][0]["display"] == "101.2°F"


def test_logging_in_again_does_not_create_or_merge_intake_sessions(app, student):
    s1, s2, *_rest = _two_sessions(student)
    again = _client(app)
    again.post("/api/v1/auth/demo/login", json={"persona": "student"})
    assert snap(again)["session_id"] == s2  # still the open conversation (s1 was ended)
    db = next(dbmod.get_db())
    assert db.query(IntakeSession).filter(IntakeSession.student_id == "demo-student-1").count() == 2
    third = new_conversation(again)
    s = snap(again)
    assert s["session_id"] == third and s["fields"] == [] and s["transcript"] == [] and s["chief_concern"] is None  # nothing inherited


def test_book_first_then_summary_attaches_to_that_appointment(student, clinician):
    student.post("/api/v1/calendars/import-sample")
    say(student, "I have a headache")
    out = book(student, slot(local="2026-10-26T10:30"), key="book-first-01")
    confirm_all(student)
    p = submit(student)
    assert p["encounter_id"] == out["case_id"] and p["clinician_name"] == "Dr. Avery Rivera"
    assert clinician.get(f"/api/v1/clinician/encounters/{out['case_id']}/intake").json()["status"] == "SHARED"


def test_output_guard_allows_disclaimers_but_still_blocks_diagnosis():
    """Regression: live Claude replies saying a photo 'won't give you a diagnosis' were replaced wholesale."""
    from app.services import safety

    for ok in ["You can add a photo below — it's optional and won't give you a diagnosis.", "That's not a diagnosis; a clinician decides.",
               "I can't diagnose this, but I can help you book.", "The photo won't be used for a diagnosis."]:
        assert safety.guard_output(ok) == (ok, False), ok
    for bad in ["You likely have eczema.", "My diagnosis is a sprain.", "It sounds like you have the flu.", "This is probably not serious.",
                "That's not serious, but the diagnosis is a sprain."]:
        assert safety.guard_output(bad)[1], bad


def test_pre_transcript_open_conversations_are_ended_not_silently_continued(student):
    from app.services.intake_service import close_untranscribed_sessions

    say(student, "I have a rash")
    db = next(dbmod.get_db())
    sess = db.query(IntakeSession).filter(IntakeSession.status == "OPEN").one()
    conv = dict(sess.conversation)
    conv.pop("transcript")  # what an older database looks like
    sess.conversation = conv
    db.commit()
    assert close_untranscribed_sessions(db) == 1 and close_untranscribed_sessions(db) == 0
    s = snap(student)
    assert s["session_id"] != sess.id and s["transcript"] == []  # fresh conversation; the old one is kept, closed
    assert db.get(IntakeSession, sess.id).status == "CLOSED"
