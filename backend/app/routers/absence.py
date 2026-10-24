from datetime import date
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError
from app.models import (
    AbsenceCase,
    AuditEvent,
    ClinicianAbsenceDecision,
    Course,
    Delivery,
    DocumentVersion,
    Encounter,
    SignatureAsset,
    TestInboxMessage,
    User,
)
from app.routers.clinician import assigned_encounter
from app.routers.system import _demo_only
from app.security import current_user, require_clinician, require_student, verify_password
from app.services import absence_service as svc
from app.services import audit
from app.timeutil import to_local, utcnow

router = APIRouter(prefix="/api/v1", tags=["absence"])

STATUS_LABELS = {
    "STUDENT_REQUESTED": "Waiting for clinician review",
    "CLINICIAN_REVIEW": "Clinician reviewing",
    "DATES_SET": "Clinician set dates",
    "PENDING_CLINICIAN_SIGNATURE": "Awaiting clinician signature",
    "SIGNED": "Signed — not sent yet",
    "DELIVERY_QUEUED": "Sending to test inbox",
    "SENT": "Delivered to test inbox",
    "FAILED": "Delivery failed — retry available",
    "REJECTED": "Clinician declined to document",
    "REVOKED": "Consent withdrawn — nothing sent",
}


# ---- schemas ----------------------------------------------------------------

class CaseIn(BaseModel):
    encounter_id: str
    requested_start: date
    requested_end: date
    note: str | None = Field(None, max_length=1000)
    disclosure_consent: bool = False


class ConsentIn(BaseModel):
    consent: bool


class ContactIn(BaseModel):
    instructor_email: str = Field(min_length=3, max_length=254)
    confirm: bool


class DecisionIn(BaseModel):
    decision: Literal["CERTIFY", "DECLINE"]
    start_date: date | None = None
    end_date: date | None = None
    wording: str | None = Field(None, max_length=2000)
    rationale_private: str | None = Field(None, max_length=2000)


class RenderIn(BaseModel):
    wording: str | None = Field(None, max_length=2000)
    message_edits: dict[str, str] = Field(default_factory=dict)
    excluded_courses: list[str] = Field(default_factory=list)


class ApproveSignIn(BaseModel):
    nonce: str
    document_sha256: str
    recipient_courses: list[str]
    password: str = Field(min_length=1, max_length=200)  # step-up re-authentication
    confirm: bool


class DeliverIn(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=80)


class ImpactQuery(BaseModel):
    start_date: date
    end_date: date


def _impact_out(impact, recips: list[dict]) -> dict:
    return {
        "start_date": impact.start_date.isoformat(), "end_date": impact.end_date.isoformat(), "days": impact.days,
        "total_meetings": impact.total_meetings,
        "courses": [{"course_code": c.course_code, "course_id": c.course_id, "dates": c.dates, "meetings": c.meetings} for c in impact.courses],
        "recipients": recips,
    }


def _deliveries(db: Session, case_id: str) -> list[dict]:
    rows = db.scalars(select(Delivery).where(Delivery.case_id == case_id).order_by(Delivery.queued_at)).all()
    return [{"id": d.id, "course_code": d.course_code, "destination": d.destination, "state": d.state, "attempts": d.attempts, "error_code": d.error_code, "receipt_id": d.receipt_id, "sent_at": d.sent_at, "version_id": d.version_id} for d in rows]


def _timeline(db: Session, case: AbsenceCase) -> list[dict]:
    rows = db.scalars(select(AuditEvent).where(AuditEvent.object_id.in_([case.id, case.encounter_id] + [v.id for v in db.scalars(select(DocumentVersion).where(DocumentVersion.case_id == case.id)).all()])).order_by(AuditEvent.id)).all()
    return [{"event_type": a.action, "actor": a.actor_role, "to_state": a.to_state, "status": a.status, "at": a.at, "detail": a.detail} for a in rows]


def _version_out(v: DocumentVersion | None, include_content: bool) -> dict | None:
    if v is None:
        return None
    out = {"id": v.id, "version": v.version, "state": v.state, "unsigned_sha256": v.unsigned_sha256, "signed_sha256": v.signed_sha256, "signed_at": v.signed_at, "created_at": v.created_at}
    if include_content:
        out["content"] = v.content
    return out


def student_case_out(db: Session, case: AbsenceCase) -> dict:
    """Student view: no clinician private notes, no signature asset, no document internals."""
    enc = db.get(Encounter, case.encounter_id)
    doc = db.get(User, enc.clinician_id)
    student = db.get(User, case.student_id)
    d = svc.latest_decision(db, case.id)
    v = svc.latest_version(db, case.id)
    return {
        "id": case.id, "status": case.status, "status_label": STATUS_LABELS.get(case.status, case.status),
        "encounter_id": enc.id, "visit_type": enc.visit_type, "appointment_at": to_local(enc.starts_at, student.timezone), "clinician_name": doc.display_name,
        "requested_start": case.requested_start, "requested_end": case.requested_end,
        "disclosure_consent": case.disclosure_consent and case.consent_revoked_at is None, "consent_revoked_at": case.consent_revoked_at,
        "decision": {"decision": d.decision, "start_date": d.start_date, "end_date": d.end_date} if d else None,
        "document": {"version": v.version, "state": v.state, "signed_at": v.signed_at} if v else None,
        "deliveries": _deliveries(db, case.id), "timeline": _timeline(db, case), "created_at": case.created_at,
        "excused_status": "UNKNOWN — decided by your university",
    }


def clinician_case_out(db: Session, case: AbsenceCase, clinician: User) -> dict:
    enc = db.get(Encounter, case.encounter_id)
    student = db.get(User, case.student_id)
    d = svc.latest_decision(db, case.id)
    v = svc.latest_version(db, case.id)
    impact = None
    if d and d.decision == "CERTIFY":
        imp = svc.compute_impact(db, student, d.start_date, d.end_date)
        impact = _impact_out(imp, svc.recipients(db, student.id, imp))
    asset = svc.active_signature(db, clinician.id)
    return {
        "id": case.id, "status": case.status, "status_label": STATUS_LABELS.get(case.status, case.status),
        "encounter_id": enc.id, "visit_type": enc.visit_type, "appointment_at": to_local(enc.starts_at, clinician.timezone),
        "student_name": student.display_name, "requested_start": case.requested_start, "requested_end": case.requested_end,
        "student_note": case.student_note,
        "decision": {"decision": d.decision, "start_date": d.start_date, "end_date": d.end_date, "wording": d.wording, "rationale_private": d.rationale_private, "version": d.version} if d else None,
        "impact": impact, "document": _version_out(v, include_content=True),
        "signature_asset": {"id": asset.id, "kind": asset.kind, "created_at": asset.created_at} if asset else None,
        "gates": {
            "student_consent": case.disclosure_consent and case.consent_revoked_at is None,
            "signed": bool(v and v.state == "SIGNED"),
            "recipients_verified": bool(v and all(m["deliverable"] for m in v.content["messages"] if m["include"])),
        },
        "deliveries": _deliveries(db, case.id), "timeline": _timeline(db, case),
    }


# ---- student ------------------------------------------------------------------

def _own_case(db: Session, user: User, case_id: str) -> AbsenceCase:
    case = db.get(AbsenceCase, case_id)
    if case is None or case.student_id != user.id:
        raise ApiError(404, "NOT_FOUND", "Case not found.")
    return case


@router.post("/absence-cases/preview")
def preview(body: ImpactQuery, user: User = Depends(require_student), db: Session = Depends(get_db)) -> dict:
    imp = svc.compute_impact(db, user, body.start_date, body.end_date)
    return _impact_out(imp, svc.recipients(db, user.id, imp))


@router.post("/absence-cases")
def create_case(body: CaseIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> dict:
    enc = db.get(Encounter, body.encounter_id)
    if enc is None or enc.student_id != user.id or enc.status == "CANCELLED":
        raise ApiError(404, "NOT_FOUND", "Choose one of your demo appointments.")
    svc.compute_impact(db, user, body.requested_start, body.requested_end)  # validates range
    case = AbsenceCase(id=f"case_{uuid4().hex[:8]}", student_id=user.id, encounter_id=enc.id, requested_start=body.requested_start, requested_end=body.requested_end, student_note=(body.note or "").strip() or None)
    if body.disclosure_consent:
        case.disclosure_consent, case.disclosure_consent_at = True, utcnow()
    db.add(case)
    audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="ABSENCE_REQUESTED", object_type="absence_case", object_id=case.id, to_state="STUDENT_REQUESTED", detail="student-requested dates (not certified)")
    if body.disclosure_consent:
        audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="DISCLOSURE_CONSENT_GRANTED", object_type="absence_case", object_id=case.id)
    db.commit()
    return student_case_out(db, case)


@router.get("/students/me/cases")
def my_cases(user: User = Depends(require_student), db: Session = Depends(get_db)) -> list[dict]:
    return [student_case_out(db, c) for c in db.scalars(select(AbsenceCase).where(AbsenceCase.student_id == user.id).order_by(AbsenceCase.created_at.desc()))]


@router.post("/absence-cases/{case_id}/consent")
def set_disclosure_consent(case_id: str, body: ConsentIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> dict:
    case = _own_case(db, user, case_id)
    if body.consent:
        case.disclosure_consent, case.disclosure_consent_at, case.consent_revoked_at = True, utcnow(), None
        audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="DISCLOSURE_CONSENT_GRANTED", object_type="absence_case", object_id=case.id)
    elif case.disclosure_consent:
        case.consent_revoked_at = utcnow()
        # Stop anything not yet sent. Already-delivered messages can't be recalled.
        for d in db.scalars(select(Delivery).where(Delivery.case_id == case.id, Delivery.state.in_(("QUEUED", "FAILED")))):
            d.state, d.error_code = "CANCELLED", "CONSENT_REVOKED"
        if case.status not in ("SENT", "REJECTED"):
            case.status = "REVOKED"
        audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="DISCLOSURE_CONSENT_REVOKED", object_type="absence_case", object_id=case.id, to_state=case.status)
    db.commit()
    return student_case_out(db, case)


@router.patch("/courses/{course_id}/contact")
def correct_contact(course_id: str, body: ContactIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> dict:
    """Manual correction (PRD US-05). Never synthesized; the student confirms the address they typed."""
    course = db.get(Course, course_id)
    if course is None or course.student_id != user.id:
        raise ApiError(404, "NOT_FOUND", "Course not found.")
    email = body.instructor_email.strip()
    if "@" not in email or " " in email or not body.confirm:
        raise ApiError(422, "INVALID_CONTACT", "Enter the instructor's email exactly as published and confirm it.")
    course.instructor_email, course.contact_status, course.provenance = email, "STUDENT_CONFIRMED", "manual"
    audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="CONTACT_CORRECTED", object_type="course", object_id=course.id, detail=course.code)
    db.commit()
    return {"id": course.id, "code": course.code, "instructor_email": course.instructor_email, "contact_status": course.contact_status, "deliverable": svc.domain_allowed(email)}


# ---- clinician --------------------------------------------------------------

def _clin_case(db: Session, clinician: User, case_id: str) -> AbsenceCase:
    case = db.get(AbsenceCase, case_id)
    if case is None:
        raise ApiError(403, "FORBIDDEN", "You don't have access to this case.", recoverable=False)
    assigned_encounter(db, clinician, case.encounter_id)  # 403 unless assigned
    return case


def _version(db: Session, clinician: User, version_id: str) -> tuple[AbsenceCase, DocumentVersion]:
    v = db.get(DocumentVersion, version_id)
    if v is None:
        raise ApiError(403, "FORBIDDEN", "You don't have access to this document.", recoverable=False)
    return _clin_case(db, clinician, v.case_id), v


@router.get("/clinician/absence-cases")
def clinician_cases(user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(AbsenceCase, Encounter, User).join(Encounter, AbsenceCase.encounter_id == Encounter.id).join(User, AbsenceCase.student_id == User.id).where(Encounter.clinician_id == user.id).order_by(AbsenceCase.created_at.desc())).all()
    return [{"id": c.id, "student_name": u.display_name, "encounter_id": e.id, "visit_type": e.visit_type, "status": c.status, "status_label": STATUS_LABELS.get(c.status, c.status), "requested_start": c.requested_start, "requested_end": c.requested_end, "created_at": c.created_at} for c, e, u in rows]


@router.get("/clinician/absence-cases/{case_id}")
def clinician_case(case_id: str, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> dict:
    case = _clin_case(db, user, case_id)
    if case.status == "STUDENT_REQUESTED":
        case.status = "CLINICIAN_REVIEW"
        audit.record(db, actor_role="clinician", actor_id=user.id, subject_student_id=case.student_id, action="CASE_OPENED", object_type="absence_case", object_id=case.id, from_state="STUDENT_REQUESTED", to_state="CLINICIAN_REVIEW")
        db.commit()
    return clinician_case_out(db, case, user)


@router.post("/clinician/absence-cases/{case_id}/preview")
def clinician_preview(case_id: str, body: ImpactQuery, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> dict:
    case = _clin_case(db, user, case_id)
    student = db.get(User, case.student_id)
    imp = svc.compute_impact(db, student, body.start_date, body.end_date)
    return _impact_out(imp, svc.recipients(db, student.id, imp))


@router.post("/clinician/absence-cases/{case_id}/decision")
def decide(case_id: str, body: DecisionIn, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> dict:
    """Only the clinician sets certified dates, chooses a shorter range, or declines (AT-29)."""
    case = _clin_case(db, user, case_id)
    if case.status in ("SENT", "DELIVERY_QUEUED"):
        raise ApiError(409, "ALREADY_SENT", "This case was already sent. Create a corrected version from a new case.")
    if body.decision == "CERTIFY":
        if not body.start_date or not body.end_date:
            raise ApiError(422, "DATES_REQUIRED", "Choose the inclusive first and last dates.")
        svc.compute_impact(db, db.get(User, case.student_id), body.start_date, body.end_date)
    prev = svc.latest_decision(db, case.id)
    d = ClinicianAbsenceDecision(id=f"dec_{uuid4().hex[:8]}", case_id=case.id, clinician_id=user.id, decision=body.decision, start_date=body.start_date if body.decision == "CERTIFY" else None, end_date=body.end_date if body.decision == "CERTIFY" else None, wording=body.wording, rationale_private=body.rationale_private, version=(prev.version + 1) if prev else 1)
    db.add(d)
    v = svc.latest_version(db, case.id)
    if v and v.state in ("UNSIGNED", "SIGNED"):
        v.state = "SUPERSEDED"  # changed dates void any existing document/approval
    old = case.status
    case.status = "DATES_SET" if body.decision == "CERTIFY" else "REJECTED"
    audit.record(db, actor_role="clinician", actor_id=user.id, subject_student_id=case.student_id, action="ABSENCE_DECISION", object_type="absence_case", object_id=case.id, from_state=old, to_state=case.status, detail=f"{body.decision} {body.start_date or ''}..{body.end_date or ''}")
    db.commit()
    return clinician_case_out(db, case, user)


@router.post("/clinician/absence-cases/{case_id}/render")
def render(case_id: str, body: RenderIn, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> dict:
    case = _clin_case(db, user, case_id)
    if case.status in ("SENT", "DELIVERY_QUEUED", "REJECTED", "REVOKED"):
        raise ApiError(409, "CASE_CLOSED", "This case can't be changed now.")
    svc.render_version(db, case, user, body.wording, body.message_edits, body.excluded_courses)
    db.commit()
    return clinician_case_out(db, case, user)


@router.get("/clinician/documents/{version_id}/preview")
def preview_pdf(version_id: str, signed: bool = False, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> Response:
    _, v = _version(db, user, version_id)
    data = v.signed_pdf if signed and v.signed_pdf else v.unsigned_pdf
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="attendance-v{v.version}{"-signed" if signed else ""}-DEMO.pdf"', "Cache-Control": "no-store"})


@router.post("/clinician/documents/{version_id}/sign-request")
def sign_request(version_id: str, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> dict:
    """Fresh, single-use confirmation tied to this exact version and hash."""
    case, v = _version(db, user, version_id)
    latest = svc.latest_version(db, case.id)
    if latest is None or latest.id != v.id or v.state != "UNSIGNED":
        raise ApiError(409, "STALE_VERSION", "Only the latest unsigned version can be signed.")
    n = svc.issue_nonce(db, user, v)
    db.commit()
    return {"nonce": n.nonce, "expires_at": n.expires_at, "document_sha256": v.unsigned_sha256, "version": v.version, "recipients": svc.destinations(v), "start_date": v.content["start_date"], "end_date": v.content["end_date"]}


@router.post("/clinician/documents/{version_id}/approve-sign")
def approve_sign(version_id: str, body: ApproveSignIn, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> dict:
    case, v = _version(db, user, version_id)
    if not body.confirm:
        raise ApiError(400, "CONFIRMATION_REQUIRED", "Confirm that you approve this exact version.")
    if not verify_password(body.password, user.password_hash):
        raise ApiError(401, "REAUTH_FAILED", "Password didn't match. Signing requires re-entering your password.")
    auth = svc.sign(db, case, v, user, body.nonce, body.document_sha256, body.recipient_courses)
    db.commit()
    return {"state": "SIGNED", "authorization_id": auth.id, "signed_sha256": v.signed_sha256, "version": v.version, "case": clinician_case_out(db, case, user)}


@router.post("/clinician/documents/{version_id}/deliver")
def deliver(version_id: str, body: DeliverIn, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> dict:
    case, v = _version(db, user, version_id)
    if case.status in ("SENT",):
        return clinician_case_out(db, case, user)  # idempotent repeat
    svc.deliver(db, case, v, user, body.idempotency_key)
    db.commit()
    return clinician_case_out(db, case, user)


@router.post("/clinician/deliveries/{delivery_id}/retry")
def retry(delivery_id: str, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> dict:
    d = db.get(Delivery, delivery_id)
    if d is None:
        raise ApiError(403, "FORBIDDEN", "You don't have access to this delivery.", recoverable=False)
    case, v = _version(db, user, d.version_id)
    svc.check_delivery_gates(db, case, v)  # re-validate everything before any retry
    svc.process(db, case, v)
    db.commit()
    return clinician_case_out(db, case, user)


@router.get("/clinician/signature-assets")
def list_assets(user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": a.id, "kind": a.kind, "created_at": a.created_at, "revoked_at": a.revoked_at} for a in db.scalars(select(SignatureAsset).where(SignatureAsset.clinician_id == user.id).order_by(SignatureAsset.created_at.desc()))]


@router.post("/clinician/signature-assets")
def enroll_asset(user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> dict:
    """Demo: enrolls the generated, watermarked sample. Real signature uploads are out of scope."""
    if svc.active_signature(db, user.id):
        raise ApiError(409, "ALREADY_ENROLLED", "You already have an active demo signature.")
    a = SignatureAsset(id=f"sig_{uuid4().hex[:8]}", clinician_id=user.id, kind="demo_sample")
    db.add(a)
    audit.record(db, actor_role="clinician", actor_id=user.id, action="SIGNATURE_ENROLLED", object_type="signature_asset", object_id=a.id, detail="demo_sample")
    db.commit()
    return {"id": a.id, "kind": a.kind, "created_at": a.created_at, "revoked_at": None}


@router.delete("/clinician/signature-assets/{asset_id}", status_code=204)
def revoke_asset(asset_id: str, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> None:
    a = db.get(SignatureAsset, asset_id)
    if a is None or a.clinician_id != user.id:
        raise ApiError(404, "NOT_FOUND", "Signature not found.")
    if a.revoked_at is None:
        a.revoked_at = utcnow()
        audit.record(db, actor_role="clinician", actor_id=user.id, action="SIGNATURE_REVOKED", object_type="signature_asset", object_id=a.id)
        db.commit()


# ---- demo-only ----------------------------------------------------------------

@router.get("/demo/test-inbox", dependencies=[Depends(_demo_only)])
def test_inbox(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    """What 'professors' would have received. Demo transport only; nothing leaves the server."""
    rows = db.scalars(select(TestInboxMessage).order_by(TestInboxMessage.received_at.desc()).limit(50)).all()
    return [{"id": m.id, "to": m.to, "subject": m.subject, "body": m.body, "attachment_name": m.attachment_name, "attachment_sha256": m.attachment_sha256, "received_at": m.received_at} for m in rows]


@router.post("/demo/transport/fail-next", dependencies=[Depends(_demo_only)])
def fail_next(count: int = 1, user: User = Depends(current_user)) -> dict:
    svc.TestInboxTransport.fail_next = max(0, min(count, 10))
    return {"fail_next": svc.TestInboxTransport.fail_next}

