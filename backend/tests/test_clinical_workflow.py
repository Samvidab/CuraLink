from tests.conftest import RIVERA_MON_1030
"""Clinician-controlled absence workflow + manual-configuration guarantees.

Requirement map (other files cover the rest):
  1 AI can't set absence duration ........ test_ai_has_no_path_to_absence_duration
  2 intake confirmation before sharing ... test_intake.py::test_handoff_requires_confirmation_and_is_scoped
  3 only authorized clinician findings ... test_examination_findings_are_clinician_only
  4 only authorized clinician approves ... test_determination_actions_and_authorization
  5 multi-day -> correct classes ......... test_determination_actions_and_authorization, test_absence.py
  6 lookup never fabricates .............. test_instructor_directory_never_fabricates
  7 only confirmed contacts deliverable .. test_absence.py::test_full_signed_delivery_flow_with_all_gates
  8 signature needs per-version approval . test_drawn_signature_is_encrypted_and_applied_only_on_approval
  9 edits invalidate approval ............ test_absence.py (AT-27), test_changing_dates_voids_signed_version
 10 nothing delivered before approvals ... test_absence.py (AT-07/09/28)
 11 demo delivery = test inbox only ...... test_non_test_delivery_mode_refuses_to_send
 12 config placeholders documented ....... test_config_markers.py
 13 missing keys -> labelled fallback .... test_missing_keys_report_labelled_fallbacks
"""

import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from PIL import Image, ImageDraw

from app import curalink_config as cfg
from app.config import get_settings
from app.services import instructor_directory, llm_gateway
from app.services.intake_fields import FIELD_KEYS

PW = "curalink-demo"


def _booked(student):
    student.post("/api/v1/calendars/import-sample")
    student.post("/api/v1/appointments/confirm", json={"slot_id": RIVERA_MON_1030, "student_approved": True, "idempotency_key": "clin-flow-0001"})
    return student.get("/api/v1/students/me/encounters").json()[0]


def _signature_png() -> str:
    img = Image.new("RGBA", (400, 120), (0, 0, 0, 0))
    ImageDraw.Draw(img).line([(20, 80), (120, 30), (220, 90), (380, 40)], fill=(20, 30, 120, 255), width=5)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def test_ai_has_no_path_to_absence_duration(student):
    assert not [k for k in FIELD_KEYS if any(w in k for w in ("absence", "duration", "days", "excuse"))]
    names = {t["name"] for t in llm_gateway.TOOLS}
    assert not [n for n in names if any(w in n for w in ("absence", "certif", "sign", "send", "book", "approve", "decide"))]

    def props(schema):
        for k, v in schema.get("properties", {}).items():
            yield k
            yield from props(v)
            yield from props(v.get("items", {}))

    params = {p for t in llm_gateway.TOOLS for p in props(t["input_schema"])}
    assert not [p for p in params if any(w in p for w in ("start_date", "end_date", "duration", "days", "absence"))]
    enum = llm_gateway.TOOLS[0]["input_schema"]["properties"]["fields"]["items"]["properties"]["key"]["enum"]
    assert "absence_days" not in enum
    enc = _booked(student)
    assert student.post(f"/api/v1/clinician/encounters/{enc['id']}/absence-case").status_code == 403


def test_examination_findings_are_clinician_only(student, clinician, login):
    enc = _booked(student)
    url = f"/api/v1/clinician/encounters/{enc['id']}/evaluation"
    assert student.put(url, json={"values": {"assessment": "x"}}).status_code == 403
    hale, _ = login("dr.hale@clinic.example.com")
    assert hale.put(url, json={"values": {"assessment": "x"}}).status_code == 403
    assert clinician.put(url, json={"values": {"not_a_field": "x"}}).status_code == 422
    r = clinician.put(url, json={"values": {"examination_findings": "Mild pharyngeal erythema (fictional)", "activity_restrictions": "Rest 48h (fictional)"}}).json()
    assert r["values"]["examination_findings"].startswith("Mild")
    assert {f["key"] for f in r["fields"]} == {f["key"] for f in cfg.EXAMINATION_FIELDS}
    # Findings are clinician-only: not in the student's case view nor in any professor message.
    assert "pharyngeal" not in json.dumps(student.get("/api/v1/students/me/cases").json())


def test_determination_actions_and_authorization(student, clinician, login):
    enc = _booked(student)
    case = clinician.post(f"/api/v1/clinician/encounters/{enc['id']}/absence-case").json()
    assert case["origin"] == "clinician" and case["status"] == "CLINICIAN_REVIEW" and case["decision"] is None
    url = f"/api/v1/clinician/absence-cases/{case['id']}/decision"
    hale, _ = login("dr.hale@clinic.example.com")
    assert hale.post(url, json={"decision": "CERTIFY", "start_date": "2026-10-30", "end_date": "2026-11-02"}).status_code == 403
    assert student.post(url, json={"decision": "CERTIFY", "start_date": "2026-10-30", "end_date": "2026-11-02"}).status_code == 403
    assert clinician.post(url, json={"decision": "CERTIFY"}).json()["code"] == "DATES_REQUIRED"  # no default duration
    assert clinician.post(url, json={"decision": "DEFER"}).json()["status"] == "DEFERRED"
    assert clinician.post(f"/api/v1/clinician/absence-cases/{case['id']}/render", json={}).status_code == 409
    # Multi-day across a weekend: Fri (STAT only; CS cancelled by EXDATE) .. Mon (all four).
    out = clinician.post(url, json={"decision": "CERTIFY", "start_date": "2026-10-30", "end_date": "2026-11-02"}).json()
    assert out["status"] == "DATES_SET"
    dates = {c["course_code"]: c["dates"] for c in out["impact"]["courses"]}
    assert dates == {"STAT 350": ["2026-10-30", "2026-11-02"], "CS 240": ["2026-11-02"], "PHIL 208": ["2026-11-02"], "COM 217": ["2026-11-02"]}
    assert [d["weekend"] for d in out["impact"]["days"]] == [False, True, True, False]
    # One-day absence is supported too.
    one = clinician.post(url, json={"decision": "CERTIFY", "start_date": "2026-10-29", "end_date": "2026-10-29"}).json()
    assert [c["course_code"] for c in one["impact"]["courses"]] == ["COM 217"]
    assert clinician.post(url, json={"decision": "DECLINE"}).json()["status_label"] == "No medical absence certificate indicated"


def test_certificate_has_every_required_field(student, clinician):
    enc = _booked(student)
    case = clinician.post(f"/api/v1/clinician/encounters/{enc['id']}/absence-case").json()
    clinician.post(f"/api/v1/clinician/absence-cases/{case['id']}/decision", json={"decision": "CERTIFY", "start_date": "2026-10-28", "end_date": "2026-10-29"})
    doc = clinician.post(f"/api/v1/clinician/absence-cases/{case['id']}/render", json={}).json()["document"]
    for f in cfg.ABSENCE_CERTIFICATION_FIELDS:
        assert str(doc["content"][f]).strip(), f
    assert doc["content"]["appointment_date"] == "2026-10-26" and doc["content"]["clinician_credentials"] == "MD (fictional)"
    v = clinician.get(f"/api/v1/verify/{doc['content']['verification_id']}").json()
    assert v["found"] and v["demo"] and "Sam" not in json.dumps(v)  # minimal, no names
    assert clinician.get("/api/v1/verify/CLV-DEMO-NOPE").json()["found"] is False


def test_drawn_signature_is_encrypted_and_applied_only_on_approval(student, clinician):
    png_b64 = _signature_png()
    raw = base64.b64decode(png_b64.split(",")[1])
    asset = clinician.post("/api/v1/clinician/signature-assets/drawn", json={"png_base64": png_b64}).json()
    assert asset["kind"] == "drawn"
    from app import db as dbmod
    from app.models import SignatureAsset

    gen = dbmod.get_db()
    db = next(gen)
    blob = db.get(SignatureAsset, asset["id"]).encrypted_blob
    gen.close()
    assert blob and b"\x89PNG" not in blob and raw[16:64] not in blob  # encrypted at rest
    assert clinician.get(f"/api/v1/clinician/signature-assets/{asset['id']}/preview").content.startswith(b"\x89PNG")
    assert student.get(f"/api/v1/clinician/signature-assets/{asset['id']}/preview").status_code == 403
    # Redraw replaces (old one revoked).
    asset2 = clinician.post("/api/v1/clinician/signature-assets/drawn", json={"png_base64": png_b64}).json()
    assets = {a["id"]: a for a in clinician.get("/api/v1/clinician/signature-assets").json()}
    assert assets[asset["id"]]["revoked_at"] and not assets[asset2["id"]]["revoked_at"]

    enc = _booked(student)
    case = clinician.post(f"/api/v1/clinician/encounters/{enc['id']}/absence-case").json()
    clinician.post(f"/api/v1/clinician/absence-cases/{case['id']}/decision", json={"decision": "CERTIFY", "start_date": "2026-10-28", "end_date": "2026-10-28"})
    doc = clinician.post(f"/api/v1/clinician/absence-cases/{case['id']}/render", json={}).json()["document"]
    assert doc["state"] == "UNSIGNED"  # stored signature applied nothing
    req = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/sign-request").json()
    ok = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/approve-sign", json={"nonce": req["nonce"], "document_sha256": req["document_sha256"], "recipient_courses": [r["course_code"] for r in req["recipients"]], "password": PW, "confirm": True})
    assert ok.status_code == 200
    signed = clinician.get(f"/api/v1/clinician/documents/{doc['id']}/preview", params={"signed": "true"}).content
    unsigned = clinician.get(f"/api/v1/clinician/documents/{doc['id']}/preview").content
    assert signed != unsigned and b"/Subtype /Image" in signed and b"/Subtype /Image" not in unsigned


def test_non_test_delivery_mode_refuses_to_send(student, clinician, monkeypatch):
    enc = _booked(student)
    courses = {c["code"]: c for c in student.get("/api/v1/students/me/dashboard").json()["courses"]}
    for code, email in [("PHIL 208", "dana.williams@example.com"), ("COM 217", courses["COM 217"]["instructor_email"])]:
        student.patch(f"/api/v1/courses/{courses[code]['id']}/contact", json={"instructor_email": email, "confirm": True})
    case = clinician.post(f"/api/v1/clinician/encounters/{enc['id']}/absence-case").json()
    student.post(f"/api/v1/absence-cases/{case['id']}/consent", json={"consent": True})
    clinician.post(f"/api/v1/clinician/absence-cases/{case['id']}/decision", json={"decision": "CERTIFY", "start_date": "2026-10-28", "end_date": "2026-10-28"})
    clinician.post("/api/v1/clinician/signature-assets")
    doc = clinician.post(f"/api/v1/clinician/absence-cases/{case['id']}/render", json={}).json()["document"]
    req = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/sign-request").json()
    clinician.post(f"/api/v1/clinician/documents/{doc['id']}/approve-sign", json={"nonce": req["nonce"], "document_sha256": req["document_sha256"], "recipient_courses": [r["course_code"] for r in req["recipients"]], "password": PW, "confirm": True})
    monkeypatch.setattr(get_settings(), "email_delivery_mode", "smtp")
    r = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/deliver", json={"idempotency_key": "mode-key-0001"})
    assert r.status_code == 503 and r.json()["code"] == "DELIVERY_PROVIDER_NOT_CONFIGURED"
    assert clinician.get("/api/v1/demo/test-inbox").json() == []
    monkeypatch.setattr(get_settings(), "email_delivery_mode", "test_inbox")
    assert clinician.post(f"/api/v1/clinician/documents/{doc['id']}/deliver", json={"idempotency_key": "mode-key-0002"}).json()["status"] == "SENT"
    assert student.get("/api/v1/students/me/cases").json()[0]["status_label"] == "Delivered to test inbox"


def test_instructor_directory_never_fabricates(monkeypatch):
    assert instructor_directory.resolve("ZZZ 99999", "001").provenance == "none"
    assert instructor_directory.resolve("ZZZ 99999", "001").instructor_email is None
    replies = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(replies["body"]).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(get_settings(), "university_directory_url", f"http://127.0.0.1:{srv.server_port}")
    try:
        replies["body"] = {"instructor_name": "A. Person"}
        m = instructor_directory.resolve("ZZZ 99999", "001")
        assert (m.instructor_name, m.instructor_email, m.contact_status) == ("A. Person", None, "NEEDS_REVIEW")
        replies["body"] = {"instructor_name": "A. Person", "instructor_email": "a.person@example.com", "authoritative": False}
        assert instructor_directory.resolve("ZZZ 99999", "001").contact_status == "NEEDS_REVIEW"
        replies["body"] = {"instructor_name": "A. Person", "instructor_email": "a.person@example.com", "authoritative": True}
        assert instructor_directory.resolve("ZZZ 99999", "001").contact_status == "VERIFIED"
        replies["body"] = {}
        assert instructor_directory.resolve("ZZZ 99999", "001").provenance == "none"
    finally:
        srv.shutdown()


def test_missing_keys_report_labelled_fallbacks(student):
    h = student.get("/api/v1/health").json()["integrations"]
    assert h["llm"] == "fallback" and h["voice"] == "fallback" and h["email_delivery"] == "test_only"
    assert student.post("/api/v1/intake/messages", json={"message": "hello"}).json()["mode"] == "scripted"
    assert student.post("/api/v1/voice/sessions", json={"voice_consent": True}).json()["mode"] == "browser"
    assert student.post("/api/v1/vision/demo-images/red_area?consent=true").json()["observer"] == "heuristic"


def test_intake_summary_attributes_sources(student):
    student.post("/api/v1/intake/messages", json={"message": "sore throat since yesterday, 100.4 F"})
    student.post("/api/v1/vision/demo-images/red_area?consent=true")
    s = student.get("/api/v1/intake/sessions/current/summary").json()
    assert s["student_reported"]["temperature"][0]["display"] == "100.4°F"
    assert s["ai_generated"][0]["source"] == "photo_observation"
    assert s["clinician_verified"] == [] and {u["key"] for u in s["uncertain"]} >= {"temperature", "symptoms_free_text"}
