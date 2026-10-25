"""Clinician-owned absence documentation workflow.

Authority split (PRD §12): the student may REQUEST dates and must separately
consent to disclosure; only the clinician sets certified dates, wording and
signs a specific immutable document version; delivery happens only after all
gates pass, and only to a test inbox in demo mode.
"""

import hashlib
import json
import secrets
from zoneinfo import ZoneInfo
from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ApiError
from app.models import (
    AbsenceCase,
    CalendarEvent,
    Encounter,
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
from app import curalink_config as cfg
from app.services import audit, pdf_builder, signature_vault, terms
from app.services.absence_mapper import Impact, Meeting, impacted
from app.timeutil import as_utc, utcnow

DELIVERABLE_CONTACT = {"VERIFIED", "STUDENT_CONFIRMED"}


# ---- impact & recipients ------------------------------------------------------

def class_meetings(db: Session, student_id: str) -> list[Meeting]:
    """Meetings in the student's selected semester only (other terms stay stored but never match)."""
    term = terms.selected(db, db.get(User, student_id))
    codes = {c.id: c.code for c in db.scalars(select(Course).where(Course.student_id == student_id))}
    rows = db.scalars(select(CalendarEvent).where(CalendarEvent.student_id == student_id, CalendarEvent.kind == "class", CalendarEvent.all_day.is_(False), terms.term_filter(term))).all()
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


# ---- recipient status: three separate questions, never one boolean --------------------------------------------
#   1. contact:  is this instructor's address confirmed? (VERIFIED from an authoritative source, or STUDENT_CONFIRMED)
#   2. route:    may the DEMO deliver it?  direct (address is itself a test address) / isolated test inbox (real-looking
#                address, simulated, never contacted) / not permitted
#   3. gates:    consent, signature validity and recipient set are separate case-level checks (delivery_readiness)
CONTACT_STATE = {"VERIFIED": "VERIFIED", "STUDENT_CONFIRMED": "CONFIRMED_BY_STUDENT", "NEEDS_REVIEW": "STUDENT_CONFIRMATION_MISSING"}
CONTACT_LABEL = {"VERIFIED": "Verified from an official source", "CONFIRMED_BY_STUDENT": "Confirmed by student",
                 "STUDENT_CONFIRMATION_MISSING": "Student confirmation missing", "EMAIL_MISSING": "Recipient email missing",
                 "EMAIL_UNVERIFIED": "Recipient email unverified", "EMAIL_CHANGED_AFTER_SIGNING": "Email changed after signing"}
ROUTE_LABEL = {"DIRECT_TEST_ADDRESS": "Test address — deliverable", "ISOLATED_TEST_INBOX": "Simulated: isolated test inbox (real address not contacted)",
               "NOT_PERMITTED_FOR_DEMO": "Recipient not permitted for demo delivery", "NO_ADDRESS": "No address on file"}


def contact_state(status: str | None, email: str | None) -> str:
    if not email:
        return "EMAIL_MISSING"
    return CONTACT_STATE.get(status or "", "EMAIL_UNVERIFIED")


def demo_alias(course_code: str) -> str:
    slug = "".join(ch for ch in course_code.lower() if ch.isalnum()) or "course"
    return f"{slug}.instructor@{get_settings().demo_inbox_domain}"


def demo_route(email: str | None, course_code: str) -> str:
    if not email:
        return "NO_ADDRESS"
    if domain_allowed(email):
        return "DIRECT_TEST_ADDRESS"
    if get_settings().demo_inbox_redirect and get_settings().email_delivery_mode == "test_inbox" and domain_allowed(demo_alias(course_code)):
        return "ISOLATED_TEST_INBOX"
    return "NOT_PERMITTED_FOR_DEMO"


def _recipient_fields(course_code: str, email: str | None, status: str | None) -> dict:
    contact = contact_state(status, email)
    route = demo_route(email, course_code)
    contact_ok = contact in ("VERIFIED", "CONFIRMED_BY_STUDENT")
    reason = None if contact_ok else CONTACT_LABEL[contact]
    if reason is None and route == "NOT_PERMITTED_FOR_DEMO":
        reason = ROUTE_LABEL[route]
    return {"contact_state": contact, "contact_label": CONTACT_LABEL[contact], "demo_route": route, "route_label": ROUTE_LABEL[route],
            "deliverable": reason is None, "blocked_reason": reason}


def recipients(db: Session, student_id: str, impact: Impact) -> list[dict]:
    term = terms.selected(db, db.get(User, student_id))
    courses = {c.code: c for c in db.scalars(select(Course).where(Course.student_id == student_id, (Course.term == term) | Course.term.is_(None) if term else True))}
    out = []
    for ci in impact.courses:
        c = courses.get(ci.course_code)
        email = c.instructor_email if c else None
        status = c.contact_status if c else "MISSING"
        out.append({
            "course_id": c.id if c else None, "course_code": ci.course_code, "course_title": c.title if c else None,
            "instructor_name": c.instructor_name if c else None, "email": email, "contact_status": status,
            **_recipient_fields(ci.course_code, email, status), "dates": ci.dates, "meetings": len(ci.meetings),
        })
    return out


def course_contacts(db: Session, student: User) -> list[dict]:
    """Selected-term courses in the same shape as recipients (no dates): contact status the student can fix."""
    term = terms.selected(db, student)
    rows = db.scalars(select(Course).where(Course.student_id == student.id, (Course.term == term) | Course.term.is_(None) if term else True).order_by(Course.code)).all()
    out = []
    for c in rows:
        out.append({"course_id": c.id, "course_code": c.code, "course_title": c.title, "instructor_name": c.instructor_name, "email": c.instructor_email,
                    "contact_status": c.contact_status, **_recipient_fields(c.code, c.instructor_email, c.contact_status), "dates": [], "meetings": 0})
    return out


def _fill(template: str, values: dict) -> str:
    for k, v in values.items():
        template = template.replace("{" + k + "}", str(v))
    return template


def draft_message(student_name: str, clinician_name: str, r: dict, start: str, end: str) -> dict:
    """Minimal disclosure: no symptoms, no diagnosis, no intake details (AT-11). Template: NOTIFICATION_TEMPLATES."""
    values = {
        "instructor": r["instructor_name"] or "Instructor", "student": student_name, "course": r["course_code"],
        "dates": ", ".join(r["dates"]), "start": start, "end": end, "clinician": clinician_name, "clinic": cfg.clinic_profile()["name"],
    }
    return {"subject": _fill(cfg.NOTIFICATION_TEMPLATES["subject"], values), "body": _fill(cfg.NOTIFICATION_TEMPLATES["body"], values)}


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
    template = (wording or decision.wording or cfg.CERTIFICATE_LANGUAGE["default_statement"])[:2000]
    final_wording = template.replace("{student}", student.display_name).replace("{start}", start).replace("{end}", end)
    messages = []
    for r in recips:
        m = draft_message(student.display_name, clinician.display_name, r, start, end)
        if message_edits and r["course_code"] in message_edits:
            m["body"] = message_edits[r["course_code"]][:4000]
        messages.append({**r, **m, "include": r["course_code"] not in excluded})
    prev = latest_version(db, case.id)
    version_no = (prev.version + 1) if prev else 1
    enc = db.get(Encounter, case.encounter_id)
    clinic = cfg.clinic_profile()
    content = {
        "case_id": case.id, "version": version_no, "student_name": student.display_name, "clinician_name": clinician.display_name,
        "clinician_credentials": clinician.credentials or "", "clinic_name": clinic["name"],
        "clinic_contact": f"{clinic['address']} · {clinic['phone']} · {clinic['email']}",
        "appointment_date": as_utc(enc.starts_at).astimezone(ZoneInfo(student.timezone)).date().isoformat() if enc else "",
        "issue_date": utcnow().date().isoformat(),
        # CURALINK_CONFIG: DOCUMENT_VERIFICATION
        # Demo verification reference (random, unguessable). GET /api/v1/verify/{id} returns a minimal DEMO record.
        # TODO(CURALINK-MANUAL): a real authenticity service (e.g. signed QR + clinic-hosted verifier) for production.
        "verification_id": f"CLV-DEMO-{secrets.token_hex(4).upper()}-{version_no}",
        "start_date": start, "end_date": end, "wording": final_wording,
        "courses": [{"code": r["course_code"], "dates": r["dates"]} for r in recips],
        "days": impact.days, "messages": messages,
    }
    missing_fields = [f for f in cfg.ABSENCE_CERTIFICATION_FIELDS if not str(content.get(f) or "").strip()]
    if missing_fields:
        raise ApiError(422, "CERTIFICATE_INCOMPLETE", f"Certificate fields missing: {', '.join(missing_fields)}.", details={"fields": missing_fields})
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


# CURALINK_CONFIG: SIGNING_POLICY
# Enforced here and in POST /clinician/documents/{id}/approve-sign (re-authentication). A signature is applied
# only to the LATEST UNSIGNED version, with a matching document hash, a fresh single-use nonce, the exact
# recipient list shown in the preview, and an active signature asset. Any later edit creates a new unsigned version.
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
    drawn = signature_vault.decrypt(asset.encrypted_blob, clinician.id) if asset.kind == "drawn" and asset.encrypted_blob else None
    signed = pdf_builder.render(version.content, {
        "signed_at": signed_at.strftime("%Y-%m-%d %H:%M"), "clinician_name": clinician.display_name, "credentials": clinician.credentials,
        "unsigned_sha256": version.unsigned_sha256, "authorization_id": auth.id, "image_png": drawn,
    })
    version.signed_pdf, version.signed_sha256, version.state, version.signed_at = signed, pdf_builder.sha256(signed), "SIGNED", signed_at
    old = case.status
    case.status, case.updated_at = "SIGNED", utcnow()
    audit.record(db, actor_role="clinician", actor_id=clinician.id, subject_student_id=case.student_id, action="DOCUMENT_SIGNED", object_type="document_version", object_id=version.id, from_state=old, to_state="SIGNED", detail=f"v{version.version} auth {auth.id}")
    return auth


# ---- delivery (transactional outbox, test transport) ------------------------

# CURALINK_CONFIG: EMAIL_PROVIDER
# The only implemented transport is the local test inbox below. A future provider (e.g. Microsoft Graph or an SMTP
# relay approved by the clinic) must implement send(db, delivery, subject, body, attachment_sha) and be selected in
# transport(). TODO(CURALINK-MANUAL): authorized production email provider + credentials (env vars, never source).
def transport():
    # CURALINK_CONFIG: EMAIL_DELIVERY_MODE  ("test_inbox" only; anything else refuses to send)
    mode = get_settings().email_delivery_mode
    if mode != "test_inbox":
        raise ApiError(503, "DELIVERY_PROVIDER_NOT_CONFIGURED", f"Delivery mode '{mode}' is not implemented. Nothing was sent.", recoverable=False)
    return TestInboxTransport


class TestInboxTransport:
    """Demo transport: writes to the local test inbox. `fail_next` simulates an outage (AT-14)."""

    __test__ = False
    fail_next = 0

    @classmethod
    def send(cls, db: Session, d: Delivery, subject: str, body: str, attachment_sha: str) -> str:
        if cls.fail_next > 0:
            cls.fail_next -= 1
            raise RuntimeError("TRANSPORT_UNAVAILABLE")
        msg = TestInboxMessage(id=f"msg_{uuid4().hex[:10]}", delivery_id=d.id, to=d.destination, subject=subject, body=body, attachment_name="attendance-verification-DEMO.pdf",
                               attachment_sha256=attachment_sha, intended_recipient=d.intended_recipient)
        db.add(msg)
        return msg.id


# CURALINK_CONFIG: DOCUMENT_RECIPIENT_RULES
# Every send requires ALL of: student disclosure consent (re-checked at send time), the latest SIGNED version with
# an intact hash, recipients unchanged since signing, and each recipient VERIFIED/STUDENT_CONFIRMED and inside
# TEST_EMAIL_ALLOWLIST. No configuration flag disables these checks.
BLOCKER_STATUS = {"STUDENT_CONSENT_MISSING": 409, "NOT_SIGNED": 409, "DOCUMENT_CHANGED_AFTER_SIGNING": 409, "RECIPIENTS_CHANGED_AFTER_SIGNING": 409,
                  "STUDENT_CONFIRMATION_MISSING": 409, "RECIPIENT_EMAIL_UNVERIFIED": 409, "RECIPIENT_NOT_PERMITTED_FOR_DEMO": 409}


def delivery_readiness(db: Session, case: AbsenceCase, version: DocumentVersion | None) -> dict:
    """ONE computation used by the delivery gate, the clinician portal and the student portal, from persisted
    records only: case consent, the signed version + its authorization, and the student's current course contacts.
    Each problem has its own code; none of them is reported as another."""
    blockers: list[dict] = []
    consent = bool(case.disclosure_consent and case.consent_revoked_at is None)
    if not consent:
        blockers.append({"code": "STUDENT_CONSENT_MISSING", "message": "The student hasn't consented to sending (or withdrew consent). Nothing will be sent."})
    signed, auth = False, None
    if version is None or version.state != "SIGNED":
        blockers.append({"code": "NOT_SIGNED", "message": "No signed version yet. The clinician must approve and sign before anything can be sent."})
    else:
        latest = latest_version(db, case.id)
        auth = db.scalar(select(SignAuthorization).where(SignAuthorization.version_id == version.id))
        intact = auth is not None and auth.document_sha256 == version.unsigned_sha256 and pdf_builder.sha256(version.signed_pdf or b"") == version.signed_sha256
        if latest is None or latest.id != version.id or not intact:
            blockers.append({"code": "DOCUMENT_CHANGED_AFTER_SIGNING", "message": "The document changed after it was signed. Review, regenerate and sign the current version."})
        elif auth.approved_destinations_hash != destinations_hash(destinations(version)):
            blockers.append({"code": "RECIPIENTS_CHANGED_AFTER_SIGNING", "message": "The recipients differ from the ones the clinician signed for. Generate and sign a new version."})
        else:
            signed = True
    courses = {c.id: c for c in db.scalars(select(Course).where(Course.student_id == case.student_id))}
    recips = []
    for m in (version.content["messages"] if version else []):
        if not m.get("include", True):
            continue
        c = courses.get(m.get("course_id") or "")
        email, status = m.get("email"), (c.contact_status if c else m.get("contact_status"))
        fields = _recipient_fields(m["course_code"], email, status)
        if c is not None and email and (c.instructor_email or "").lower() != email.lower():
            # The signature covers this exact address: a different current address needs a new signed version.
            fields.update(contact_state="EMAIL_CHANGED_AFTER_SIGNING", contact_label=CONTACT_LABEL["EMAIL_CHANGED_AFTER_SIGNING"], deliverable=False,
                          blocked_reason="Instructor email changed after signing — generate and sign a new version")
        recips.append({"course_code": m["course_code"], "course_id": m.get("course_id"), "course_title": m.get("course_title"), "instructor_name": m.get("instructor_name"), "email": email,
                       "deliver_to": (email if fields["demo_route"] == "DIRECT_TEST_ADDRESS" else demo_alias(m["course_code"]) if fields["demo_route"] == "ISOLATED_TEST_INBOX" else None),
                       **fields})
    def courses_where(pred):
        return [r["course_code"] for r in recips if pred(r)]
    missing = courses_where(lambda r: r["contact_state"] in ("STUDENT_CONFIRMATION_MISSING", "EMAIL_MISSING"))
    if missing:
        no_email = courses_where(lambda r: r["contact_state"] == "EMAIL_MISSING")
        parts = [f"confirm the instructor email for {', '.join(c for c in missing if c not in no_email)}" if len(no_email) < len(missing) else "",
                 f"add and confirm an instructor email for {', '.join(no_email)}" if no_email else ""]
        blockers.append({"code": "STUDENT_CONFIRMATION_MISSING", "courses": missing, "message": "The student still needs to " + " and ".join(p for p in parts if p) + "."})
    unverified = courses_where(lambda r: r["contact_state"] == "EMAIL_UNVERIFIED")
    if unverified:
        blockers.append({"code": "RECIPIENT_EMAIL_UNVERIFIED", "courses": unverified, "message": f"No verified instructor email for {', '.join(unverified)}."})
    changed = courses_where(lambda r: r["contact_state"] == "EMAIL_CHANGED_AFTER_SIGNING")
    if changed:
        blockers.append({"code": "RECIPIENTS_CHANGED_AFTER_SIGNING", "courses": changed, "message": f"Instructor email changed after signing for {', '.join(changed)}. Generate and sign a new version."})
    not_permitted = courses_where(lambda r: r["demo_route"] == "NOT_PERMITTED_FOR_DEMO" and r["contact_state"] in ("VERIFIED", "CONFIRMED_BY_STUDENT"))
    if not_permitted:
        blockers.append({"code": "RECIPIENT_NOT_PERMITTED_FOR_DEMO", "courses": not_permitted, "message": f"Demo delivery isn't permitted for {', '.join(not_permitted)} (not a test address, and the isolated test inbox is off)."})
    rows = db.scalars(select(Delivery).where(Delivery.case_id == case.id, Delivery.version_id == version.id)).all() if version else []
    failed = [d.course_code for d in rows if d.state == "FAILED"]
    sent = bool(rows) and all(d.state == "SENT" for d in rows)
    return {
        "clinician_signed": signed, "signed_version": version.version if version and version.state == "SIGNED" else None,
        "student_consent": consent,
        "contacts_confirmed": bool(recips) and all(r["contact_state"] in ("VERIFIED", "CONFIRMED_BY_STUDENT") for r in recips),
        "recipients": recips,
        "blockers": blockers + ([{"code": "DELIVERY_FAILED", "courses": failed, "message": f"Delivery failed for {', '.join(failed)}. Retry is available; nothing was marked delivered."}] if failed else []),
        "ready": not blockers and not sent, "delivered": sent,
        "uses_isolated_test_inbox": any(r["demo_route"] == "ISOLATED_TEST_INBOX" for r in recips),
    }


def check_delivery_gates(db: Session, case: AbsenceCase, version: DocumentVersion) -> SignAuthorization:
    readiness = delivery_readiness(db, case, version)
    for b in readiness["blockers"]:
        if b["code"] in BLOCKER_STATUS:
            raise ApiError(BLOCKER_STATUS[b["code"]], b["code"], b["message"], details={"courses": b.get("courses", [])})
    return db.scalar(select(SignAuthorization).where(SignAuthorization.version_id == version.id))


def deliver(db: Session, case: AbsenceCase, version: DocumentVersion, actor: User, idempotency_key: str) -> list[Delivery]:
    auth = check_delivery_gates(db, case, version)
    transport()  # refuse up front if no supported delivery mode is configured
    out: list[Delivery] = []
    for dest in auth.approved_destinations:
        # The clinician signed for these instructors; in the demo, a real-looking address is never contacted:
        # the copy goes to the isolated test inbox under a fictional alias (transport routing only, so the signed
        # document and the signed recipient list are unchanged).
        to = dest["email"] if demo_route(dest["email"], dest["course_code"]) == "DIRECT_TEST_ADDRESS" else demo_alias(dest["course_code"])
        intended = None if to == dest["email"] else dest["email"]
        # Idempotent per (version, destination): repeats return the existing row.
        d = db.scalar(select(Delivery).where(Delivery.version_id == version.id, Delivery.destination == to))
        if d is None:
            d = Delivery(id=f"dlv_{uuid4().hex[:10]}", case_id=case.id, version_id=version.id, course_code=dest["course_code"], destination=to, intended_recipient=intended, idempotency_key=idempotency_key)
            db.add(d)
            db.flush()
        out.append(d)
    case.status = "DELIVERY_QUEUED"
    redirected = sum(1 for d in out if d.intended_recipient)
    audit.record(db, actor_role=actor.role, actor_id=actor.id, subject_student_id=case.student_id, action="DELIVERY_QUEUED", object_type="absence_case", object_id=case.id, to_state="DELIVERY_QUEUED",
                 detail=f"{len(out)} recipients, test_only" + (f", {redirected} to isolated test inbox (real addresses not contacted)" if redirected else ""))
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
            d.receipt_id = transport().send(db, d, m["subject"], m["body"], version.signed_sha256 or "")
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
