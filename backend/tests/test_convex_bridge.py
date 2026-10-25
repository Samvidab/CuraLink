"""FastAPI -> Convex bridge: token signing, authorized projections, after-commit sync, revocation, voice tickets."""

import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.config import get_settings
from app.services import convex_bridge as cb
from tests.conftest import RIVERA_MON_1030, _client

SECRET_FIELDS = ("password_hash", "token_hash", "nonce", "encrypted_blob", "signed_pdf", "unsigned_pdf", "image_png")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@pytest.fixture()
def captured(monkeypatch, tmp_path):
    """Convex sync on, with POSTs captured instead of sent; the outbox runs synchronously."""
    s = get_settings()
    monkeypatch.setattr(s, "convex_site_url", "https://test-deployment.convex.site")
    monkeypatch.setattr(s, "convex_sync_secret", "s" * 40)
    monkeypatch.setattr(s, "public_api_url", "https://api.example.com")
    monkeypatch.setattr(s, "secrets_dir", tmp_path)
    monkeypatch.setattr(cb, "_key", None)
    sent: list[dict] = []
    monkeypatch.setattr(cb, "post", lambda records, reset_all=False: sent.extend(records))
    cb.install()
    monkeypatch.setattr(cb._queue, "put", lambda item: cb.push_keys(*item))  # no background thread in tests
    yield sent
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    for name, fn in (("after_flush", cb._after_flush), ("after_commit", cb._after_commit), ("after_rollback", cb._after_rollback)):
        if event.contains(Session, name, fn):
            event.remove(Session, name, fn)


def latest(sent: list[dict], table: str, rid: str | None = None) -> dict:
    rows = [r for r in sent if r["table"] == table and (rid is None or r["recordId"] == rid)]
    assert rows, f"no {table} record synced"
    return rows[-1]


def test_token_is_valid_rs256_with_issuer_audience_role(app, student, captured):
    tok = student.get("/api/v1/convex/token").json()["token"]
    head, body, sig = tok.split(".")
    claims = json.loads(_b64d(body))
    assert (claims["iss"], claims["aud"], claims["sub"], claims["role"]) == ("https://api.example.com", "curalink-convex", "demo-student-1", "student")
    assert claims["exp"] - claims["iat"] == cb.TOKEN_TTL
    key = _client(app).get("/.well-known/jwks.json").json()["keys"][0]
    assert json.loads(_b64d(head))["kid"] == key["kid"] and key["alg"] == "RS256"
    pub = rsa.RSAPublicNumbers(int.from_bytes(_b64d(key["e"]), "big"), int.from_bytes(_b64d(key["n"]), "big")).public_key()
    pub.verify(_b64d(sig), f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())  # raises if invalid
    assert _client(app).get("/api/v1/convex/token").status_code == 401  # signed-out users get no token


def test_commits_sync_authorized_projections_without_secrets(app, student, clinician, captured):
    student.post("/api/v1/calendars/import-sample")
    student.post("/api/v1/intake/messages", json={"message": "I have a fever", "channel": "text", "history": []})
    out = student.post("/api/v1/appointments/confirm", json={"slot_id": RIVERA_MON_1030, "student_approved": True, "idempotency_key": "convex-sync-01"}).json()
    appt = latest(captured, "appointments", out["appointment_id"])
    assert appt["studentId"] == "demo-student-1" and appt["clinicianIds"] == ["demo-clinician-1"] and appt["data"]["caseId"] == out["case_id"]
    sess = latest(captured, "intakeSessions")
    assert sess["clinicianIds"] == []  # conversation drafts are never visible to clinicians
    snap = student.get("/api/v1/intake/sessions/current").json()
    for f in snap["fields"]:
        student.post(f"/api/v1/intake/sessions/{snap['session_id']}/fields/{f['key']}/confirm", json={"confirmed": True})
    pkt = student.post(f"/api/v1/intake/sessions/{snap['session_id']}/summary", json={"student_authorized": True, "field_keys": [f["key"] for f in snap["fields"]]}).json()
    summ = latest(captured, "previsitSummaries", pkt["packet_id"])
    assert summ["clinicianIds"] == ["demo-clinician-1"] and summ["data"]["summary"]["chief_concern"]
    blob = json.dumps(captured)
    assert not any(f in blob for f in SECRET_FIELDS) and "scrypt$" not in blob


def test_cancel_and_withdraw_revoke_clinician_access_in_convex(app, student, captured):
    student.post("/api/v1/calendars/import-sample")
    student.post("/api/v1/intake/messages", json={"message": "I have a sore throat", "channel": "text", "history": []})
    out = student.post("/api/v1/appointments/confirm", json={"slot_id": RIVERA_MON_1030, "student_approved": True, "idempotency_key": "convex-sync-02"}).json()
    snap = student.get("/api/v1/intake/sessions/current").json()
    for f in snap["fields"]:
        student.post(f"/api/v1/intake/sessions/{snap['session_id']}/fields/{f['key']}/confirm", json={"confirmed": True})
    pkt = student.post(f"/api/v1/intake/sessions/{snap['session_id']}/summary", json={"student_authorized": True, "field_keys": [f["key"] for f in snap["fields"]]}).json()
    student.post(f"/api/v1/handoffs/{pkt['packet_id']}/withdraw")
    w = latest(captured, "previsitSummaries", pkt["packet_id"])
    assert w["clinicianIds"] == [] and w["data"]["summary"] is None
    student.post(f"/api/v1/appointments/{out['appointment_id']}/cancel")
    assert latest(captured, "appointments", out["appointment_id"])["clinicianIds"] == []


def test_clinician_only_fields_and_absence_records(app, student, clinician, captured):
    student.post("/api/v1/calendars/import-sample")
    student.post("/api/v1/appointments/confirm", json={"slot_id": RIVERA_MON_1030, "student_approved": True, "idempotency_key": "convex-sync-03"})
    enc = student.get("/api/v1/students/me/encounters").json()[0]
    case = student.post("/api/v1/absence-cases", json={"encounter_id": enc["id"], "note": "private context", "disclosure_consent": True}).json()
    clinician.post(f"/api/v1/clinician/absence-cases/{case['id']}/decision", json={"decision": "CERTIFY", "start_date": "2026-10-27", "end_date": "2026-10-28", "rationale_private": "exam notes"})
    dec = latest(captured, "absenceDecisions")
    assert dec["data"]["startDate"] == "2026-10-27" and "rationalePrivate" not in dec["data"] and dec["clinicianOnly"]["rationalePrivate"] == "exam notes"
    ac = latest(captured, "absenceCases", case["id"])
    assert ac["data"]["consent"]["given"] is True and ac["clinicianOnly"]["studentNote"] == "private context" and "studentNote" not in ac["data"]


def test_demo_reset_resends_everything_with_reset_flag(app, monkeypatch, captured):
    calls = []
    monkeypatch.setattr(cb, "post", lambda records, reset_all=False: calls.append((len(records), reset_all)))
    c = _client(app)
    assert c.post("/api/v1/demo/reset").status_code == 200
    assert calls and calls[-1][1] is True and calls[-1][0] > 5


def test_voice_ticket_is_single_use_and_bound_to_the_student(app, monkeypatch):
    from app.routers import voice as v

    monkeypatch.setattr(get_settings(), "public_api_url", "https://api.example.com")
    monkeypatch.setattr(v, "cartesia_enabled", lambda: True)
    s = _client(app)
    s.post("/api/v1/auth/demo/login", json={"persona": "student"})
    url = s.post("/api/v1/voice/sessions", json={"voice_consent": True}).json()["stream_url"]
    assert url.startswith("wss://api.example.com/api/v1/voice/stream?ticket=")
    ticket = url.split("ticket=")[1]
    assert v.redeem_ticket(ticket) == "demo-student-1"
    assert v.redeem_ticket(ticket) is None  # single use
    assert v.redeem_ticket("forged") is None
