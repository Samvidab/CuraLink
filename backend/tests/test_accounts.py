"""Sign-in sessions, account creation, profile names and the personalized greeting."""

from sqlalchemy import select

from app import db as dbmod
from app.models import AuthSession, User
from app.routers import voice as voice_router
from app.services import llm_gateway, names
from tests.conftest import RIVERA_MON_1030, _client
from tests.test_voice import FakeStt, SlowTts

ME = "/api/v1/me"
PROFILE = "/api/v1/students/me/profile"


def _db():
    return next(dbmod.get_db())


def _register(app, email="alex.new@students.example.com", password="long-enough-pw"):
    c = _client(app)
    r = c.post("/api/v1/auth/register", json={"email": email, "password": password})
    return c, r


def test_unauthenticated_visitor_is_not_signed_in_as_anyone(app, student):
    """Another browser being signed in as Sam never signs in a new visitor."""
    assert student.get(ME).json()["display_name"] == "Sam Lee"
    fresh = _client(app)
    r = fresh.get(ME)
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHENTICATED"


def test_session_cookie_is_browser_session_only(app):
    r = _client(app).post("/api/v1/auth/demo/login", json={"persona": "student"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "max-age" not in cookie and "expires" not in cookie


def test_every_login_creates_a_new_session_and_revokes_the_old_one(app):
    c = _client(app)
    c.post("/api/v1/auth/demo/login", json={"persona": "student"})
    first = c.cookies.get("curalink_session")
    c.post("/api/v1/auth/demo/login", json={"persona": "clinician"})  # switch accounts in the same browser
    second = c.cookies.get("curalink_session")
    assert first != second
    old = _client(app)
    old.cookies.set("curalink_session", first)
    assert old.get(ME).status_code == 401  # the previous identity is gone
    assert c.get(ME).json()["role"] == "clinician"
    assert c.get("/api/v1/students/me/dashboard").status_code == 403  # no student data through the new session


def test_logout_invalidates_the_backend_session(app, student):
    token = student.cookies.get("curalink_session")
    assert student.post("/api/v1/auth/logout").status_code == 204
    replay = _client(app)
    replay.cookies.set("curalink_session", token)
    assert replay.get(ME).status_code == 401


def test_new_student_must_complete_profile_and_name_is_saved_to_their_own_row(app, student):
    c, r = _register(app)
    assert r.status_code == 201
    me = r.json()
    assert me["role"] == "student" and me["profile_complete"] is False and me["first_name"] is None
    # A body can't choose whose profile it writes: extra keys are ignored, the session decides.
    out = c.patch(PROFILE, json={"first_name": "Alex", "last_name": "Morgan", "preferred_name": "Al", "id": "demo-student-1"}).json()
    assert (out["id"], out["display_name"], out["preferred_name"], out["profile_complete"]) == (me["id"], "Alex Morgan", "Al", True)
    db = _db()
    assert db.get(User, me["id"]).first_name == "Alex"
    sam = db.get(User, "demo-student-1")
    assert (sam.display_name, sam.first_name, sam.preferred_name) == ("Sam Lee", "Sam", None)  # Sam untouched
    assert student.get(ME).json()["display_name"] == "Sam Lee"


def test_returning_students_are_not_prompted_again(app, login):
    c, _ = _register(app, "riley@students.example.com")
    c.patch(PROFILE, json={"first_name": "Riley", "last_name": "Chen"})
    c.post("/api/v1/auth/logout")
    _, r = login("riley@students.example.com", "long-enough-pw", "student")
    assert r.json()["profile_complete"] is True and r.json()["first_name"] == "Riley"
    _, sam = login("sam.lee@students.example.com", expected_role="student")
    assert sam.json()["profile_complete"] is True  # demo account arrives complete


def test_names_are_validated_and_required(app):
    c, _ = _register(app)
    assert c.patch(PROFILE, json={"first_name": "", "last_name": "Morgan"}).json()["code"] == "NAME_REQUIRED"
    assert c.patch(PROFILE, json={"first_name": "Alex", "last_name": "<script>"}).json()["code"] == "INVALID_NAME"
    assert c.patch(PROFILE, json={"first_name": "José", "last_name": "O’Neil-Smith"}).status_code == 200


def test_students_can_update_and_clear_their_preferred_name(student):
    assert student.patch(PROFILE, json={"first_name": "Sam", "last_name": "Lee", "preferred_name": "Sammy"}).json()["preferred_name"] == "Sammy"
    assert student.get("/api/v1/assistant/greeting").json()["text"].startswith("Hi Sammy!")
    assert student.patch(PROFILE, json={"first_name": "Sam", "last_name": "Lee", "preferred_name": ""}).json()["preferred_name"] is None
    assert student.get("/api/v1/assistant/greeting").json()["text"].startswith("Hi Sam!")


def test_new_sessions_keep_profile_and_records(app, student, login):
    student.post("/api/v1/calendars/import-sample")
    assert student.post("/api/v1/appointments/confirm", json={"slot_id": RIVERA_MON_1030, "student_approved": True, "idempotency_key": "acct-test-0001"}).status_code == 200
    student.patch(PROFILE, json={"first_name": "Sam", "last_name": "Lee", "preferred_name": "Sammy"})
    student.post("/api/v1/auth/logout")
    again, r = login("sam.lee@students.example.com", expected_role="student")
    assert r.json()["preferred_name"] == "Sammy"
    assert [a["clinician_name"] for a in again.get("/api/v1/appointments/me").json() if a["state"] == "DEMO_CONFIRMED"] == ["Dr. Avery Rivera"]
    demo_again = _client(app)
    demo_again.post("/api/v1/auth/demo/login", json={"persona": "student"})
    assert demo_again.get(ME).json()["id"] == "demo-student-1"  # demo login reuses Sam, never creates a copy
    assert len(_db().scalars(select(User).where(User.email == "sam.lee@students.example.com")).all()) == 1


def test_greeting_uses_the_authenticated_students_name_not_a_hardcoded_one(app, student):
    assert student.get("/api/v1/assistant/greeting").json()["text"] == "Hi Sam! I'm CuraLink, your campus healthcare navigator. I can help organize care, not diagnose. How can I help you today?"
    c, _ = _register(app)
    assert c.get("/api/v1/assistant/greeting").json()["text"].startswith("Hi! ")  # no name yet: no guess
    c.patch(PROFILE, json={"first_name": "Alex", "last_name": "Morgan"})
    assert c.get("/api/v1/assistant/greeting").json()["text"].startswith("Hi Alex!")
    assert "Sam" not in c.get("/api/v1/assistant/greeting").json()["text"]


def test_claude_context_carries_preferred_name(student, monkeypatch):
    seen = {}

    async def fake_turn(history, text, context, handle_tool):
        seen["ctx"] = context
        return llm_gateway.LlmTurn(text="Got it. When did it start?", tool_events=[], proposed_fields=[])

    monkeypatch.setattr(llm_gateway, "available", lambda: True)
    monkeypatch.setattr(llm_gateway, "run_turn", fake_turn)
    student.patch(PROFILE, json={"first_name": "Sam", "last_name": "Lee", "preferred_name": "Sammy"})
    student.post("/api/v1/intake/messages", json={"message": "I have a sore throat", "channel": "text", "history": []})
    assert "student's preferred name: Sammy;" in seen["ctx"]
    assert "use it rarely" in llm_gateway.SYSTEM_PROMPT


class RecordingTts(SlowTts):
    def __init__(self):
        super().__init__()
        self.spoken: list[str] = []

    async def speak(self, text, context_id):
        self.spoken.append(text)
        async for chunk in super().speak(text, context_id):
            yield chunk


def test_spoken_greeting_matches_displayed_greeting(student, monkeypatch):
    tts = RecordingTts()

    async def stt():
        return FakeStt([])

    async def tts_factory():
        return tts

    monkeypatch.setattr(voice_router, "cartesia_enabled", lambda: True)
    monkeypatch.setattr(voice_router, "stt_factory", stt)
    monkeypatch.setattr(voice_router, "tts_factory", tts_factory)
    shown = student.get("/api/v1/assistant/greeting").json()["text"]
    student.post("/api/v1/voice/sessions", json={"voice_consent": True})
    with student.websocket_connect("/api/v1/voice/stream") as ws:
        assert ws.receive_json()["type"] == "session.started"
        ws.send_json({"type": "history", "items": [{"role": "assistant", "text": shown}]})
        ws.send_json({"type": "greet"})
        events = []
        while not events or events[-1]["type"] != "assistant.audio.done":
            events.append(ws.receive_json())
        greeting = next(e for e in events if e["type"] == "assistant.greeting")
        assert greeting["text"] == shown == tts.spoken[0]
        ws.send_json({"type": "session.end"})


def test_greeting_is_not_spoken_once_the_student_has_talked(student, monkeypatch):
    tts = RecordingTts()

    async def factory():
        return tts

    async def stt():
        return FakeStt([])

    monkeypatch.setattr(voice_router, "cartesia_enabled", lambda: True)
    monkeypatch.setattr(voice_router, "stt_factory", stt)
    monkeypatch.setattr(voice_router, "tts_factory", factory)
    student.post("/api/v1/voice/sessions", json={"voice_consent": True})
    with student.websocket_connect("/api/v1/voice/stream") as ws:
        ws.receive_json()
        ws.send_json({"type": "history", "items": [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "hello"}]})
        ws.send_json({"type": "greet"})
        ws.send_json({"type": "session.end"})
        while ws.receive_json()["type"] != "session.ended":
            pass
    assert tts.spoken == []


def test_clinician_names_in_scheduling_and_dashboard(student, clinician):
    names_shown = {c["name"] for c in student.get("/api/v1/clinicians").json()["clinicians"]}
    assert {"Dr. Avery Rivera", "Dr. Morgan Hale"} <= names_shown
    me = clinician.get(ME).json()
    assert (me["display_name"], me["first_name"], me["last_name"]) == ("Dr. Avery Rivera", "Avery", "Rivera")
    rows = clinician.get("/api/v1/clinician/encounters").json()
    assert {"Jordan Kim", "Taylor Brooks"} <= {r["student_name"] for r in rows}


def test_clinician_sign_up_never_grants_clinician_access(app, login):
    anon = _client(app)
    r = anon.post("/api/v1/auth/register/clinician", json={"email": "new.doc@clinic.example.com", "password": "long-enough-pw", "first_name": "Jamie", "last_name": "Ortiz", "credentials": "MD", "clinical_role": "Family Medicine"})
    assert r.status_code == 201 and r.json()["status"] == "PENDING_VERIFICATION"
    assert "curalink_session" not in anon.cookies  # no session from a claim
    _, r = login("new.doc@clinic.example.com", "long-enough-pw", "clinician")
    assert r.status_code == 403 and r.json()["code"] == "CLINICIAN_NOT_VERIFIED"
    # Student sign-up always makes a student, whatever the body says.
    c, r = _register(app, "sneaky@clinic.example.com")
    c2 = _client(app)
    r2 = c2.post("/api/v1/auth/register", json={"email": "sneaky2@clinic.example.com", "password": "long-enough-pw", "role": "clinician"})
    assert r.json()["role"] == r2.json()["role"] == "student"
    assert c2.get("/api/v1/clinician/encounters").status_code == 403
    # Server-side verification is the only path to clinician access.
    from app.admin import main as admin

    assert admin(["verify-clinician", "new.doc@clinic.example.com"]) == 0
    doc, r = login("new.doc@clinic.example.com", "long-enough-pw", "clinician")
    assert r.status_code == 200 and r.json()["display_name"] == "Jamie Ortiz" and r.json()["clinical_role"] == "Family Medicine"
    assert doc.get("/api/v1/clinician/encounters").json() == []  # verified, but no one else's patients


def test_duplicate_email_and_weak_password_are_refused(app):
    _register(app, "dup@students.example.com")
    assert _register(app, "DUP@students.example.com")[1].json()["code"] == "EMAIL_IN_USE"
    assert _register(app, "sam.lee@students.example.com")[1].status_code == 409
    assert _register(app, "short@students.example.com", "short")[1].status_code == 422


def test_no_cross_account_leaks(app, student, clinician):
    c, _ = _register(app)
    c.patch(PROFILE, json={"first_name": "Alex", "last_name": "Morgan"})
    assert c.get("/api/v1/appointments/me").json() == []  # nothing of Sam's
    assert c.get("/api/v1/intake/sessions/current").json()["fields"] == []
    assert clinician.patch(PROFILE, json={"first_name": "X", "last_name": "Y"}).status_code == 403
    assert {r["student_name"] for r in clinician.get("/api/v1/clinician/encounters").json()}.isdisjoint({"Alex Morgan"})


def test_backfill_adds_missing_demo_names_without_touching_records(app, student):
    db = _db()
    sam = db.get(User, "demo-student-1")
    sam.first_name = sam.last_name = None
    sam.display_name = "Sam Lee"
    db.commit()
    assert student.get(ME).json()["profile_complete"] is False  # an older database
    assert names.backfill_demo_names(db) >= 1
    me = student.get(ME).json()
    assert (me["first_name"], me["last_name"], me["display_name"], me["profile_complete"]) == ("Sam", "Lee", "Sam Lee", True)
    assert db.scalars(select(AuthSession).where(AuthSession.user_id == "demo-student-1", AuthSession.revoked_at.is_(None))).first() is not None
