from datetime import UTC, date, datetime

import pytest

from app.services.absence_mapper import Meeting, impacted

TZ = "America/Indiana/Indianapolis"


# ---- pure impact engine ------------------------------------------------------

def test_mapper_counts_only_real_meetings_across_a_weekend():
    """AT-25: a multi-day range crossing a weekend lists only actual meetings."""
    def m(i, code, d, h):
        return Meeting(f"e{i}", code, code, datetime(2026, 10, d, h, tzinfo=UTC), datetime(2026, 10, d, h + 1, tzinfo=UTC))

    meetings = [m(1, "CS 240", 30, 14), m(2, "CS 240", 31, 14), m(3, "STAT 350", 29, 16), m(4, "CS 240", 26, 14)]
    imp = impacted(meetings, date(2026, 10, 29), date(2026, 11, 1), TZ)
    assert [d["weekend"] for d in imp.days] == [False, False, True, True]
    assert imp.total_meetings == 3  # Oct 26 is outside the inclusive range
    with pytest.raises(ValueError):
        impacted(meetings, date(2026, 11, 2), date(2026, 11, 1), TZ)


# ---- API workflow --------------------------------------------------------------

@pytest.fixture()
def case(student):
    student.post("/api/v1/calendars/import-sample")
    student.post("/api/v1/appointments/confirm", json={"slot_id": "slot_04", "student_approved": True, "idempotency_key": "abs-key-0001"})
    # Symptom details in intake must never leak into professor messages (AT-11).
    sid = student.get("/api/v1/intake/sessions/current").json()["session_id"]
    student.patch(f"/api/v1/intake/sessions/{sid}/fields", json={"fields": [{"key": "symptoms_free_text", "value": {"text": "strep-like sore throat and vomiting"}}]})
    enc = student.get("/api/v1/students/me/encounters").json()[0]
    r = student.post("/api/v1/absence-cases", json={"encounter_id": enc["id"], "requested_start": "2026-10-27", "requested_end": "2026-10-30", "note": "I'd rather not share details", "disclosure_consent": True})
    assert r.status_code == 200, r.text
    return r.json()


def _certify(clinician, case_id, start="2026-10-28", end="2026-10-29", **kw):
    r = clinician.post(f"/api/v1/clinician/absence-cases/{case_id}/decision", json={"decision": "CERTIFY", "start_date": start, "end_date": end, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _render(clinician, case_id, **kw):
    r = clinician.post(f"/api/v1/clinician/absence-cases/{case_id}/render", json=kw)
    assert r.status_code == 200, r.text
    return r.json()["document"]


def _sign(clinician, version_id, password="curalink-demo"):
    req = clinician.post(f"/api/v1/clinician/documents/{version_id}/sign-request").json()
    return clinician.post(f"/api/v1/clinician/documents/{version_id}/approve-sign", json={
        "nonce": req["nonce"], "document_sha256": req["document_sha256"], "recipient_courses": [r["course_code"] for r in req["recipients"]], "password": password, "confirm": True,
    }), req


def _fix_contacts(student):
    courses = {c["code"]: c for c in student.get("/api/v1/students/me/dashboard").json()["courses"]}
    student.patch(f"/api/v1/courses/{courses['PHIL 208']['id']}/contact", json={"instructor_email": "dana.williams@example.com", "confirm": True})
    student.patch(f"/api/v1/courses/{courses['COM 217']['id']}/contact", json={"instructor_email": courses["COM 217"]["instructor_email"], "confirm": True})


def test_student_request_is_not_certification(student, case):
    assert case["status"] == "STUDENT_REQUESTED" and case["decision"] is None
    assert case["excused_status"].startswith("UNKNOWN")
    assert student.post(f"/api/v1/clinician/absence-cases/{case['id']}/decision", json={"decision": "CERTIFY", "start_date": "2026-10-27", "end_date": "2026-10-30"}).status_code == 403


def test_clinician_chooses_shorter_range_and_sees_exact_impact(clinician, case):
    detail = clinician.get(f"/api/v1/clinician/absence-cases/{case['id']}").json()
    assert detail["status"] == "CLINICIAN_REVIEW" and detail["student_note"] == "I'd rather not share details"
    out = _certify(clinician, case["id"])
    imp = out["impact"]
    by_code = {c["course_code"]: c["dates"] for c in imp["courses"]}
    # Wed: CS, PHIL, STAT (moved to 2:30 via RECURRENCE-ID); Thu: COM only.
    assert by_code == {"CS 240": ["2026-10-28"], "PHIL 208": ["2026-10-28"], "STAT 350": ["2026-10-28"], "COM 217": ["2026-10-29"]}
    status = {r["course_code"]: (r["contact_status"], r["deliverable"]) for r in imp["recipients"]}
    assert status == {"CS 240": ("VERIFIED", True), "STAT 350": ("VERIFIED", True), "PHIL 208": ("MISSING", False), "COM 217": ("NEEDS_REVIEW", False)}
    assert next(r for r in imp["recipients"] if r["course_code"] == "PHIL 208")["email"] is None  # never guessed


def test_excluding_courses_yields_exactly_matching_drafts(clinician, case):
    """AT-06."""
    _certify(clinician, case["id"], "2026-10-28", "2026-10-28")
    doc = _render(clinician, case["id"], excluded_courses=["STAT 350"])
    included = [m["course_code"] for m in doc["content"]["messages"] if m["include"]]
    assert included == ["CS 240", "PHIL 208"]


def test_full_signed_delivery_flow_with_all_gates(student, clinician, case):
    _certify(clinician, case["id"])
    doc = _render(clinician, case["id"])
    assert doc["state"] == "UNSIGNED" and doc["version"] == 1
    for m in doc["content"]["messages"]:  # AT-11: minimal disclosure
        assert "throat" not in m["body"].lower() and "vomit" not in m["body"].lower() and "rather not" not in m["body"]
    pdf = clinician.get(f"/api/v1/clinician/documents/{doc['id']}/preview")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")

    # A stored signature is required, but never signs by itself.
    r, _ = _sign(clinician, doc["id"])
    assert r.status_code == 409 and r.json()["code"] == "NO_SIGNATURE_ASSET"
    clinician.post("/api/v1/clinician/signature-assets")
    assert clinician.get(f"/api/v1/clinician/absence-cases/{case['id']}").json()["document"]["state"] == "UNSIGNED"

    r, _ = _sign(clinician, doc["id"], password="wrong-pass")
    assert r.status_code == 401 and r.json()["code"] == "REAUTH_FAILED"
    req = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/sign-request").json()
    bad = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/approve-sign", json={**{"nonce": req["nonce"], "recipient_courses": [x["course_code"] for x in req["recipients"]], "password": "curalink-demo", "confirm": True}, "document_sha256": "0" * 64})
    assert bad.status_code == 409 and bad.json()["code"] == "HASH_MISMATCH"  # AT-26
    r, req = _sign(clinician, doc["id"])
    assert r.status_code == 200 and r.json()["state"] == "SIGNED"
    replay = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/approve-sign", json={"nonce": req["nonce"], "document_sha256": req["document_sha256"], "recipient_courses": [x["course_code"] for x in req["recipients"]], "password": "curalink-demo", "confirm": True})
    assert replay.status_code == 409  # single-use nonce / already signed

    # AT-07: unverified recipients block delivery.
    r = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/deliver", json={"idempotency_key": "dlv-key-0001"})
    assert r.status_code == 409 and r.json()["code"] == "RECIPIENT_NOT_VERIFIED"
    assert clinician.get("/api/v1/demo/test-inbox").json() == []

    # Student corrects contacts -> clinician must render and sign a NEW version (AT-27).
    _fix_contacts(student)
    doc2 = _render(clinician, case["id"])
    assert doc2["version"] == 2 and doc2["state"] == "UNSIGNED"
    stale = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/deliver", json={"idempotency_key": "dlv-key-0002"})
    assert stale.status_code == 409 and stale.json()["code"] == "NOT_SIGNED"
    assert _sign(clinician, doc2["id"])[0].status_code == 200

    sent = clinician.post(f"/api/v1/clinician/documents/{doc2['id']}/deliver", json={"idempotency_key": "dlv-key-0003"}).json()
    assert sent["status"] == "SENT" and {d["state"] for d in sent["deliveries"]} == {"SENT"}
    inbox = clinician.get("/api/v1/demo/test-inbox").json()
    assert len(inbox) == 4 and all(m["to"].endswith("@example.com") for m in inbox)
    # AT-10: repeating the request sends nothing new.
    clinician.post(f"/api/v1/clinician/documents/{doc2['id']}/deliver", json={"idempotency_key": "dlv-key-0003"})
    clinician.post(f"/api/v1/clinician/documents/{doc2['id']}/deliver", json={"idempotency_key": "dlv-key-0004"})
    assert len(clinician.get("/api/v1/demo/test-inbox").json()) == 4

    mine = student.get("/api/v1/students/me/cases").json()[0]
    assert mine["status"] == "SENT" and mine["status_label"] == "Delivered to test inbox"
    # Student view never exposes clinician-private rationale, the signature asset, or document internals.
    assert not {"rationale_private", "signature_asset", "content", "student_note"} & set(mine) and "rationale_private" not in str(mine["decision"])


def test_no_delivery_without_student_disclosure_consent(student, clinician, case):
    """AT-09 / AT-28."""
    _fix_contacts(student)
    student.post(f"/api/v1/absence-cases/{case['id']}/consent", json={"consent": False})
    _certify(clinician, case["id"])
    clinician.post("/api/v1/clinician/signature-assets")
    doc = _render(clinician, case["id"])
    assert _sign(clinician, doc["id"])[0].status_code == 200
    r = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/deliver", json={"idempotency_key": "dlv-key-0101"})
    assert r.status_code == 409 and r.json()["code"] == "STUDENT_CONSENT_MISSING"
    assert clinician.get("/api/v1/demo/test-inbox").json() == []


def test_transport_failure_is_recoverable_not_false_delivered(student, clinician, case):
    """AT-14."""
    _fix_contacts(student)
    _certify(clinician, case["id"])
    clinician.post("/api/v1/clinician/signature-assets")
    doc = _render(clinician, case["id"])
    _sign(clinician, doc["id"])
    clinician.post("/api/v1/demo/transport/fail-next", params={"count": 1})
    out = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/deliver", json={"idempotency_key": "dlv-key-0201"}).json()
    assert out["status"] == "FAILED"
    failed = [d for d in out["deliveries"] if d["state"] == "FAILED"]
    assert len(failed) == 1 and failed[0]["error_code"] == "TRANSPORT_UNAVAILABLE"
    assert len(clinician.get("/api/v1/demo/test-inbox").json()) == 3
    out = clinician.post(f"/api/v1/clinician/deliveries/{failed[0]['id']}/retry").json()
    assert out["status"] == "SENT" and len(clinician.get("/api/v1/demo/test-inbox").json()) == 4


def test_decline_blocks_documents(clinician, case):
    """AT-29: the clinician may decline; nothing can be generated."""
    out = clinician.post(f"/api/v1/clinician/absence-cases/{case['id']}/decision", json={"decision": "DECLINE", "rationale_private": "not appropriate"}).json()
    assert out["status"] == "REJECTED"
    assert clinician.post(f"/api/v1/clinician/absence-cases/{case['id']}/render", json={}).status_code == 409


def test_changing_dates_voids_signed_version(clinician, case):
    _certify(clinician, case["id"])
    clinician.post("/api/v1/clinician/signature-assets")
    doc = _render(clinician, case["id"])
    _sign(clinician, doc["id"])
    out = _certify(clinician, case["id"], "2026-10-28", "2026-10-28")
    assert out["document"]["state"] == "SUPERSEDED" and out["status"] == "DATES_SET"


def test_revoked_signature_cannot_sign(clinician, case):
    _certify(clinician, case["id"])
    asset = clinician.post("/api/v1/clinician/signature-assets").json()
    assert clinician.delete(f"/api/v1/clinician/signature-assets/{asset['id']}").status_code == 204
    doc = _render(clinician, case["id"])
    r, _ = _sign(clinician, doc["id"])
    assert r.status_code == 409 and r.json()["code"] == "NO_SIGNATURE_ASSET"


def test_other_clinicians_and_students_are_locked_out(student, case, login):
    """AT-08 / AT-24."""
    hale, _ = login("dr.hale@clinic.example.com")
    assert hale.get(f"/api/v1/clinician/absence-cases/{case['id']}").status_code == 403
    assert hale.get("/api/v1/clinician/absence-cases").json() == []
    assert student.get(f"/api/v1/clinician/absence-cases/{case['id']}").status_code == 403
    assert student.post("/api/v1/clinician/signature-assets").status_code == 403


def test_contact_correction_requires_confirmation(student, case):
    c = student.get("/api/v1/students/me/dashboard").json()["courses"][0]
    assert student.patch(f"/api/v1/courses/{c['id']}/contact", json={"instructor_email": "x@example.com", "confirm": False}).status_code == 422
    r = student.patch(f"/api/v1/courses/{c['id']}/contact", json={"instructor_email": "someone@gmail.com", "confirm": True}).json()
    assert r["contact_status"] == "STUDENT_CONFIRMED" and r["deliverable"] is False  # outside the demo allowlist


def test_dashboard_still_works_after_contact_correction(student, case):
    """Regression: STUDENT_CONFIRMED contacts broke the dashboard schema (500)."""
    _fix_contacts(student)
    r = student.get("/api/v1/students/me/dashboard")
    assert r.status_code == 200
    assert {c["code"]: c["contact_status"] for c in r.json()["courses"]}["PHIL 208"] == "STUDENT_CONFIRMED"


def test_case_metrics_are_measured_from_audit_log(student, case):
    m = student.get("/api/v1/students/me/cases").json()[0]["metrics"]
    assert m["request_to_delivery_seconds"] is None and m["student_actions"] >= 1
