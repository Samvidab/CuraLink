from tests.conftest import RIVERA_MON_1030
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
    student.post("/api/v1/appointments/confirm", json={"slot_id": RIVERA_MON_1030, "student_approved": True, "idempotency_key": "abs-key-0001"})
    # Symptom details in intake must never leak into professor messages (AT-11).
    sid = student.get("/api/v1/intake/sessions/current").json()["session_id"]
    student.patch(f"/api/v1/intake/sessions/{sid}/fields", json={"fields": [{"key": "symptoms_free_text", "value": {"text": "strep-like sore throat and vomiting"}}]})
    enc = student.get("/api/v1/students/me/encounters").json()[0]
    r = student.post("/api/v1/absence-cases", json={"encounter_id": enc["id"], "reported_missed_dates": ["2026-10-26"], "note": "I'd rather not share details", "disclosure_consent": True})
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


def test_full_signed_delivery_flow_with_all_gates(student, clinician, case, login):
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

    # AT-07: unconfirmed recipients block delivery, with the precise reason and courses.
    r = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/deliver", json={"idempotency_key": "dlv-key-0001"})
    assert r.status_code == 409 and r.json()["code"] == "STUDENT_CONFIRMATION_MISSING" and "COM 217" in r.json()["details"]["courses"]
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
    assert len(student.get("/api/v1/demo/test-inbox").json()) == 4  # the student's own notices
    assert login("jordan.kim@students.example.com")[0].get("/api/v1/demo/test-inbox").json() == []  # never another student's
    assert login("dr.hale@clinic.example.com")[0].get("/api/v1/demo/test-inbox").json() == []  # nor an unassigned clinician

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


# ---- only clinicians decide certified absence dates --------------------------------------------------------------

def test_student_cannot_choose_or_change_certified_dates(student, clinician, case):
    enc = student.get("/api/v1/students/me/encounters").json()[0]
    for bad in ({"requested_start": "2026-10-27", "requested_end": "2026-10-30"}, {"start_date": "2026-10-27", "end_date": "2026-10-28"}, {"decision": "CERTIFY"}):
        r = student.post("/api/v1/absence-cases", json={"encounter_id": enc["id"], **bad})
        assert r.status_code == 422, bad  # rejected outright, never stored
    assert student.post(f"/api/v1/clinician/absence-cases/{case['id']}/decision", json={"decision": "CERTIFY", "start_date": "2026-10-27", "end_date": "2026-11-05"}).status_code == 403
    assert student.post(f"/api/v1/clinician/absence-cases/{case['id']}/render", json={}).status_code == 403
    assert student.patch(f"/api/v1/absence-cases/{case['id']}", json={"start_date": "2026-10-27"}).status_code in (404, 405)
    mine = student.get("/api/v1/students/me/cases").json()[0]
    assert mine["decision"] is None and mine["reported_missed_dates"] == ["2026-10-26"] and mine["legacy_requested_range"] is None
    assert "requested_start" not in mine


def test_reported_missed_dates_are_facts_not_certification(student, clinician, case):
    view = clinician.get(f"/api/v1/clinician/absence-cases/{case['id']}").json()
    assert view["reported_missed_dates"] == ["2026-10-26"] and view["decision"] is None
    assert view["status"] in ("STUDENT_REQUESTED", "CLINICIAN_REVIEW")  # nothing approved, nothing generated
    assert clinician.post(f"/api/v1/clinician/absence-cases/{case['id']}/render", json={}).status_code == 409  # no document before a CERTIFY decision


def test_clinician_can_certify_multi_day_decline_or_defer(clinician, case):
    out = _certify(clinician, case["id"], "2026-10-27", "2026-10-30")
    assert out["decision"]["start_date"] == "2026-10-27" and out["decision"]["end_date"] == "2026-10-30" and out["status"] == "DATES_SET"
    for decision, status in (("DEFER", "DEFERRED"), ("DECLINE", "REJECTED")):
        r = clinician.post(f"/api/v1/clinician/absence-cases/{case['id']}/decision", json={"decision": decision})
        assert r.json()["status"] == status and r.json()["decision"]["start_date"] is None


# ---- delivery statuses are distinct, persisted, and shared by both portals --------------------------------------

def _purdue_like_contacts(student):
    """Real-looking (non-test) instructor addresses, confirmed by the student, like a real UniTime import."""
    courses = student.get("/api/v1/students/me/dashboard").json()["courses"]
    for c in courses:
        r = student.patch(f"/api/v1/courses/{c['id']}/contact", json={"instructor_email": f"{c['code'].replace(' ', '').lower()}@purdue.edu", "confirm": True})
        assert r.status_code == 200, r.text
    return courses


def _signed_v1(clinician, case_id):
    clinician.post("/api/v1/clinician/signature-assets")
    _certify(clinician, case_id)
    doc = _render(clinician, case_id)
    r, _ = _sign(clinician, doc["id"])
    assert r.status_code == 200
    return doc


def test_confirmed_real_looking_contacts_go_to_isolated_test_inbox_without_resigning(app, student, clinician, case, login):
    _purdue_like_contacts(student)
    doc = _signed_v1(clinician, case["id"])
    view = clinician.get(f"/api/v1/clinician/absence-cases/{case['id']}").json()
    dv = view["delivery"]
    assert dv["clinician_signed"] and dv["student_consent"] and dv["contacts_confirmed"] and dv["ready"] and dv["blockers"] == []
    assert {r["contact_label"] for r in dv["recipients"]} == {"Confirmed by student"} and {r["demo_route"] for r in dv["recipients"]} == {"ISOLATED_TEST_INBOX"}
    signed_sha = view["document"]["signed_sha256"]
    out = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/deliver", json={"idempotency_key": "dlv-real-0001"}).json()
    assert out["status"] == "SENT" and all(d["simulated"] and d["intended_recipient"].endswith("@purdue.edu") for d in out["deliveries"])
    after = clinician.get(f"/api/v1/clinician/absence-cases/{case['id']}").json()
    assert after["document"]["version"] == 1 and after["document"]["state"] == "SIGNED" and after["document"]["signed_sha256"] == signed_sha  # signature untouched
    inbox = clinician.get("/api/v1/demo/test-inbox").json()
    assert inbox and all(m["to"].endswith("@test-inbox.example.com") and not m["to"].endswith("purdue.edu") and m["intended_recipient"].endswith("@purdue.edu") for m in inbox)
    assert after["delivery"]["delivered"] and not after["delivery"]["ready"]


def test_demo_redirect_off_reports_not_permitted_and_keeps_the_signature(student, clinician, case, monkeypatch):
    from app.config import get_settings

    _purdue_like_contacts(student)
    doc = _signed_v1(clinician, case["id"])
    monkeypatch.setattr(get_settings(), "demo_inbox_redirect", False)
    r = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/deliver", json={"idempotency_key": "dlv-real-0002"})
    assert r.status_code == 409 and r.json()["code"] == "RECIPIENT_NOT_PERMITTED_FOR_DEMO"
    view = clinician.get(f"/api/v1/clinician/absence-cases/{case['id']}").json()
    assert view["document"]["state"] == "SIGNED" and view["delivery"]["contacts_confirmed"]  # confirmed, just not deliverable in the demo
    assert [b["code"] for b in view["delivery"]["blockers"]] == ["RECIPIENT_NOT_PERMITTED_FOR_DEMO"]
    assert clinician.get("/api/v1/demo/test-inbox").json() == []


def test_confirming_the_same_address_after_signing_needs_no_new_signature(student, clinician, case):
    courses = {c["code"]: c for c in student.get("/api/v1/students/me/dashboard").json()["courses"]}
    student.patch(f"/api/v1/courses/{courses['PHIL 208']['id']}/contact", json={"instructor_email": "dana.williams@example.com", "confirm": True})
    doc = _signed_v1(clinician, case["id"])  # COM 217 still unconfirmed at signing time
    blockers = clinician.get(f"/api/v1/clinician/absence-cases/{case['id']}").json()["delivery"]["blockers"]
    assert [(b["code"], b["courses"]) for b in blockers] == [("STUDENT_CONFIRMATION_MISSING", ["COM 217"])]
    student.patch(f"/api/v1/courses/{courses['COM 217']['id']}/contact", json={"instructor_email": courses["COM 217"]["instructor_email"], "confirm": True})
    assert clinician.post(f"/api/v1/clinician/documents/{doc['id']}/deliver", json={"idempotency_key": "dlv-same-0001"}).json()["status"] == "SENT"


def test_changed_email_or_document_after_signing_is_reported_precisely(student, clinician, case):
    _purdue_like_contacts(student)
    doc = _signed_v1(clinician, case["id"])
    courses = {c["code"]: c for c in student.get("/api/v1/students/me/dashboard").json()["courses"]}
    student.patch(f"/api/v1/courses/{courses['CS 240']['id']}/contact", json={"instructor_email": "someone.else@purdue.edu", "confirm": True})
    r = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/deliver", json={"idempotency_key": "dlv-chg-0001"})
    assert r.json()["code"] == "RECIPIENTS_CHANGED_AFTER_SIGNING" and r.json()["details"]["courses"] == ["CS 240"]
    _render(clinician, case["id"])  # a newer version exists now
    r = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/deliver", json={"idempotency_key": "dlv-chg-0002"})
    assert r.json()["code"] == "NOT_SIGNED" or r.json()["code"] == "DOCUMENT_CHANGED_AFTER_SIGNING"


def test_consent_missing_is_its_own_status(student, clinician, case):
    _purdue_like_contacts(student)
    doc = _signed_v1(clinician, case["id"])
    student.post(f"/api/v1/absence-cases/{case['id']}/consent", json={"consent": False})
    r = clinician.post(f"/api/v1/clinician/documents/{doc['id']}/deliver", json={"idempotency_key": "dlv-cons-0001"})
    assert r.json()["code"] == "STUDENT_CONSENT_MISSING"


def test_student_confirmations_persist_across_sessions_and_both_portals_agree(app, student, clinician, case, login):
    _purdue_like_contacts(student)
    _signed_v1(clinician, case["id"])
    student.post("/api/v1/auth/logout")
    again, _ = login("sam.lee@students.example.com", expected_role="student")
    mine = again.get("/api/v1/students/me/cases").json()[0]["delivery"]
    theirs = clinician.get(f"/api/v1/clinician/absence-cases/{case['id']}").json()["delivery"]
    assert mine["recipients"] == theirs["recipients"] and mine["blockers"] == theirs["blockers"]
    assert {r["contact_label"] for r in mine["recipients"]} == {"Confirmed by student"}
