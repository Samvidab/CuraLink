"""Clinician-owned absence documentation workflow.

Authority split (PRD §12): the student may REQUEST dates and must separately
consent to disclosure; only the clinician sets certified dates, wording and
signs a specific immutable document version; delivery happens only after all
gates pass, and only to a test inbox in demo mode.
"""

import hashlib
import json
import secrets
from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ApiError
from app.models import (
    AbsenceCase,
    CalendarEvent,
    ClinicianAbsenceDecision,
    Course,
    Delivery,
    DocumentVersion,
    SignatureAsset,
    SignAuthorization,
    SignNonce,
    TestInboxMessage,
    User,
)
from app.services import audit, pdf_builder
from app.services.absence_mapper import Impact, Meeting, impacted
from app.timeutil import as_utc, utcnow

DELIVERABLE_CONTACT = {"VERIFIED", "STUDENT_CONFIRMED"}
DEFAULT_WORDING = (
    "{student} has been seen by a healthcare professional and may be unable to attend class from {start} through {end}. "
    "This notice does not include medical details and does not determine whether an absence is excused."
)


# ---- impact & recipients ------------------------------------------------------

def class_meetings(db: Session, student_id: str) -> list[Meeting]:
    codes = {c.id: c.code for c in db.scalars(select(Course).where(Course.student_id == student_id))}
    rows = db.scalars(select(CalendarEvent).where(CalendarEvent.student_id == student_id, CalendarEvent.kind == "class", CalendarEvent.all_day.is_(False))).all()
    return [Meeting(e.id, e.course_id, codes.get(e.course_id, e.summary), as_utc(e.start_at), as_utc(e.end_at)) for e in rows]


def compute_impact(db: Session, student: User, start: date, end: date) -> Impact:
    try:
        return impacted(class_meetings(db, student.id), start, end, student.timezone)
    except ValueError as exc:
        raise ApiError(422, "INVALID_RANGE", "Choose an end date on or after the start date, at most 31 days long.") from exc


def domain_allowed(email: str | None) -> bool:
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].lower()
    return any(domain == d or domain.endswith("." + d) for d in get_settings().allowlisted_domains)


def recipients(db: Session, student_id: str, impact: Impact) -> list[dict]:
    courses = {c.code: c for c in db.scalars(select(Course).where(Course.student_id == student_id))}
    out = []
    for ci in impact.courses:
        c = courses.get(ci.course_code)
        email = c.instructor_email if c else None
        status = c.contact_status if c else "MISSING"
        reason = None
        if status not in DELIVERABLE_CONTACT:
            reason = "Contact needs review" if status == "NEEDS_REVIEW" else "Contact needed"
        elif not domain_allowed(email):
            reason = "Not on the demo test allowlist"
        out.append({
            "course_id": c.id if c else None, "course_code": ci.course_code, "course_title": c.title if c else None,
            "instructor_name": c.instructor_name if c else None, "email": email, "contact_status": status,
            "deliverable": reason is None, "blocked_reason": reason, "dates": ci.dates, "meetings": len(ci.meetings),
        })
    return out


def draft_message(student_name: str, clinician_name: str, r: dict, start: str, end: str) -> dict:
    """Minimal disclosure: no symptoms, no diagnosis, no intake details (AT-11)."""
    who = r["instructor_name"] or "Instructor"
    dates = ", ".join(r["dates"])
    return {
        "subject": f"Attendance verification: {student_name} · {r['course_code']}",
        "body": (
            f"Dear {who},\n\n"
            f"{student_name} was seen by a healthcare professional and may be absent from {r['course_code']} "
            f"on {dates} (verification period {start} to {end}).\n\n"
            "This message contains no medical information and does not determine whether the absence is excused; "
            "please apply your course and university policies.\n\n"
            f"Sent on behalf of {clinician_name} via CuraLink (demo). The signed verification is attached."
        ),
    }


# ---- versions -----------------------------------------------------------------

def latest_version(db: Session, case_id: str) -> DocumentVersion | None:
    return db.scalar(select(DocumentVersion).where(DocumentVersion.case_id == case_id).order_by(DocumentVersion.version.desc()))


def latest_decision(db: Session, case_id: str) -> ClinicianAbsenceDecision | None:
    return db.scalar(select(ClinicianAbsenceDecision).where(ClinicianAbsenceDecision.case_id == case_id).order_by(ClinicianAbsenceDecision.version.desc()))


def render_version(db: Session, case: AbsenceCase, clinician: User, wording: str | None = None, message_edits: dict[str, str] | None = None, excluded: list[str] | None = None) -> DocumentVersion:
    decision = latest_decision(db, case.id)
    if decision is None or decision.decision != "CERTIFY":
        raise ApiError(409, "NO_DECISION", "Set the certified dates before generating a document.")
    student = db.get(User, case.student_id)
    impact = compute_impact(db, student, decision.start_date, decision.end_date)
    recips = recipients(db, student.id, impact)
    excluded = set(excluded or [])
    start, end = decision.start_date.isoformat(), decision.end_date.isoformat()
    template = (wording or decision.wording or DEFAULT_WORDING)[:2000]
    final_wording = template.replace("{student}", student.display_name).replace("{start}", start).replace("{end}", end)
    messages = []
    for r in recips:
        m = draft_message(student.display_name, clinician.display_name, r, start, end)
        if message_edits and r["course_code"] in message_edits:
            m["body"] = message_edits[r["course_code"]][:4000]
        messages.append({**r, **m, "include": r["course_code"] not in excluded})
    prev = latest_version(db, case.id)
    version_no = (prev.version + 1) if prev else 1
    content = {
        "case_id": case.id, "version": version_no, "student_name": student.display_name, "clinician_name": clinician.display_name,
        "start_date": start, "end_date": end, "wording": final_wording,
        "courses": [{"code": r["course_code"], "dates": r["dates"]} for r in recips],
        "days": impact.days, "messages": messages,
    }
    pdf = pdf_builder.render(content)
    if prev and prev.state in ("UNSIGNED", "SIGNED"):
        prev.state = "SUPERSEDED"  # any edit invalidates the earlier version and its approval
    v = DocumentVersion(id=f"doc_{uuid4().hex[:10]}", case_id=case.id, decision_id=decision.id, version=version_no, content=content, unsigned_pdf=pdf, unsigned_sha256=pdf_builder.sha256(pdf), state="UNSIGNED", created_by=clinician.id)
    db.add(v)
    old = case.status
    case.status, case.updated_at = "PENDING_CLINICIAN_SIGNATURE", utcnow()
    audit.record(db, actor_role="clinician", actor_id=clinician.id, subject_student_id=case.student_id, action="DOCUMENT_RENDERED", object_type="document_version", object_id=v.id, from_state=old, to_state=case.status, detail=f"v{version_no}")
    return v


# ---- signing ------------------------------------------------------------------

def active_signature(db: Session, clinician_id: str) -> SignatureAsset | None:
    return db.scalar(select(SignatureAsset).where(SignatureAsset.clinician_id == clinician_id, SignatureAsset.revoked_at.is_(None)))


def destinations(version: DocumentVersion) -> list[dict]:
    return [{"course_code": m["course_code"], "email": m["email"]} for m in version.content["messages"] if m["include"]]


def destinations_hash(dests: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sorted(dests, key=lambda d: d["course_code"]), sort_keys=True).encode()).hexdigest()


def issue_nonce(db: Session, clinician: User, version: DocumentVersion) -> SignNonce:
    n = SignNonce(nonce=secrets.token_urlsafe(18), clinician_id=clinician.id, version_id=version.id, expires_at=utcnow() + timedelta(minutes=10))
    db.add(n)
    return n


def sign(db: Session, case: AbsenceCase, version: DocumentVersion, clinician: User, nonce: str, document_sha256: str, recipient_codes: list[str]) -> SignAuthorization:
    latest = latest_version(db, case.id)
    if latest is None or latest.id != version.id or version.state != "UNSIGNED":
        raise ApiError(409, "STALE_VERSION", "This document version changed or was already signed. Review the latest version.")
    if document_sha256 != version.unsigned_sha256:
        raise ApiError(409, "HASH_MISMATCH", "The document you reviewed doesn't match the stored version. Reload and review again.")
    n = db.get(SignNonce, nonce)
    if n is None or n.clinician_id != clinician.id or n.version_id != version.id or n.used_at is not None or as_utc(n.expires_at) <= utcnow():
        raise ApiError(409, "INVALID_NONCE", "This signing confirmation expired or was already used. Start again.")
    asset = active_signature(db, clinician.id)
    if asset is None:
        raise ApiError(409, "NO_SIGNATURE_ASSET", "Set up your demo sample signature in Signature Settings first.")
    dests = destinations(version)
    if sorted(recipient_codes) != sorted(d["course_code"] for d in dests):
        raise ApiError(409, "RECIPIENTS_CHANGED", "Confirm the exact recipients shown in the final preview.")
    n.used_at = utcnow()
    auth = SignAuthorization(
        id=f"sa_{uuid4().hex[:10]}", clinician_id=clinician.id, version_id=version.id, signature_asset_id=asset.id,
        document_sha256=version.unsigned_sha256, approved_destinations=dests, approved_destinations_hash=destinations_hash(dests), nonce=nonce,
    )
    db.add(auth)
    signed_at = utcnow()
    signed = pdf_builder.render(version.content, {
        "signed_at": signed_at.strftime("%Y-%m-%d %H:%M"), "clinician_name": clinician.display_name, "credentials": clinician.credentials,
        "unsigned_sha256": version.unsigned_sha256, "authorization_id": auth.id,
    })
    version.signed_pdf, version.signed_sha256, version.state, version.signed_at = signed, pdf_builder.sha256(signed), "SIGNED", signed_at
    old = case.status
    case.status, case.updated_at = "SIGNED", utcnow()
    audit.record(db, actor_role="clinician", actor_id=clinician.id, subject_student_id=case.student_id, action="DOCUMENT_SIGNED", object_type="document_version", object_id=version.id, from_state=old, to_state="SIGNED", detail=f"v{version.version} auth {auth.id}")
    return auth


# ---- delivery (transactional outbox, test transport) ------------------------

class TestInboxTransport:
    """Demo transport: writes to the local test inbox. `fail_next` simulates an outage (AT-14)."""

    __test__ = False
    fail_next = 0

    @classmethod
    def send(cls, db: Session, d: Delivery, subject: str, body: str, attachment_sha: str) -> str:
        if cls.fail_next > 0:
            cls.fail_next -= 1
            raise RuntimeError("TRANSPORT_UNAVAILABLE")
        msg = TestInboxMessage(id=f"msg_{uuid4().hex[:10]}", delivery_id=d.id, to=d.destination, subject=subject, body=body, attachment_name="attendance-verification-DEMO.pdf", attachment_sha256=attachment_sha)
        db.add(msg)
        return msg.id


def check_delivery_gates(db: Session, case: AbsenceCase, version: DocumentVersion) -> SignAuthorization:
    if not case.disclosure_consent or case.consent_revoked_at is not None:
        raise ApiError(409, "STUDENT_CONSENT_MISSING", "The student hasn't consented to sending (or withdrew consent). Nothing will be sent.")
    latest = latest_version(db, case.id)
    if version.state != "SIGNED" or latest is None or latest.id != version.id:
        raise ApiError(409, "NOT_SIGNED", "Only the latest signed version can be sent.")
    auth = db.scalar(select(SignAuthorization).where(SignAuthorization.version_id == version.id))
    if auth is None or auth.document_sha256 != version.unsigned_sha256 or pdf_builder.sha256(version.signed_pdf or b"") != version.signed_sha256:
        raise ApiError(409, "AUTHORIZATION_INVALID", "The signature authorization doesn't match this document.")
    if auth.approved_destinations_hash != destinations_hash(destinations(version)):
        raise ApiError(409, "RECIPIENTS_CHANGED", "Recipients changed after signing. Generate and sign a new version.")
    blocked = [m["course_code"] for m in version.content["messages"] if m["include"] and not m["deliverable"]]
    if blocked:
        raise ApiError(409, "RECIPIENT_NOT_VERIFIED", f"Verify instructor contacts first: {', '.join(blocked)}.", details={"courses": blocked})
    return auth


def deliver(db: Session, case: AbsenceCase, version: DocumentVersion, actor: User, idempotency_key: str) -> list[Delivery]:
    auth = check_delivery_gates(db, case, version)
    out: list[Delivery] = []
    for dest in auth.approved_destinations:
        # Idempotent per (version, destination): repeats return the existing row.
        d = db.scalar(select(Delivery).where(Delivery.version_id == version.id, Delivery.destination == dest["email"]))
        if d is None:
            d = Delivery(id=f"dlv_{uuid4().hex[:10]}", case_id=case.id, version_id=version.id, course_code=dest["course_code"], destination=dest["email"], idempotency_key=idempotency_key)
            db.add(d)
            db.flush()
        out.append(d)
    case.status = "DELIVERY_QUEUED"
    audit.record(db, actor_role=actor.role, actor_id=actor.id, subject_student_id=case.student_id, action="DELIVERY_QUEUED", object_type="absence_case", object_id=case.id, to_state="DELIVERY_QUEUED", detail=f"{len(out)} recipients, test_only")
    db.flush()
    process(db, case, version)
    return out


def process(db: Session, case: AbsenceCase, version: DocumentVersion) -> None:
    """Outbox worker (synchronous in demo). Re-checks consent right before each send."""
    messages = {m["course_code"]: m for m in version.content["messages"]}
    for d in db.scalars(select(Delivery).where(Delivery.version_id == version.id, Delivery.state.in_(("QUEUED", "FAILED")))):
        if not case.disclosure_consent or case.consent_revoked_at is not None:
            d.state, d.error_code = "CANCELLED", "CONSENT_REVOKED"
            continue
        if not domain_allowed(d.destination):
            d.state, d.error_code = "FAILED", "DESTINATION_NOT_ALLOWLISTED"
            continue
        d.attempts += 1
        m = messages[d.course_code]
        try:
            d.receipt_id = TestInboxTransport.send(db, d, m["subject"], m["body"], version.signed_sha256 or "")
            d.state, d.sent_at, d.error_code = "SENT", utcnow(), None
        except RuntimeError as exc:
            d.state, d.error_code = "FAILED", str(exc)
    states = [d.state for d in db.scalars(select(Delivery).where(Delivery.version_id == version.id))]
    old = case.status
    if states and all(s == "SENT" for s in states):
        case.status = "SENT"
    elif any(s == "FAILED" for s in states):
        case.status = "FAILED"
    elif states and all(s == "CANCELLED" for s in states):
        case.status = "REVOKED"
    if case.status != old:
        audit.record(db, actor_role="system", actor_id=None, subject_student_id=case.student_id, action=f"DELIVERY_{case.status}", object_type="absence_case", object_id=case.id, from_state=old, to_state=case.status, status="ok" if case.status == "SENT" else "error", detail=f"{states.count('SENT')}/{len(states)} delivered to test inbox")
