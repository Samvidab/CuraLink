from uuid import uuid4

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import serializers as ser
from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app import curalink_config as cfg
from app.models import AbsenceCase, Appointment, Attachment, AuditEvent, ClinicalEvaluation, ClinicSlot, Encounter, HandoffPacket, IntakeAnnotation, IntakeSession, User
from app.schemas import ActivityOut, ClinicianDashboard, ClinicianIntakeOut, EncounterDetail, EncounterRow, IntakeFieldOut
from app.security import require_clinician
from app.services import audit, previsit
from app.timeutil import as_utc, local_day_bounds, to_local, utcnow

router = APIRouter(prefix="/api/v1/clinician", tags=["clinician"])

STATUS_LABELS = {
    "UPCOMING": "Upcoming",
    "INTAKE_SHARED": "Intake received",
    "CLINICIAN_REVIEW": "Needs review",
    "COMPLETED": "Completed",
    "CANCELLED": "Cancelled",
}


def assigned_encounter(db: Session, clinician: User, encounter_id: str) -> Encounter:
    """Object-scoped access: a clinician only reaches encounters assigned to them.
    Unknown and unassigned ids return the same 403 so existence isn't leaked."""
    enc = db.get(Encounter, encounter_id)
    if enc is None or enc.clinician_id != clinician.id:
        raise ApiError(403, "FORBIDDEN", "You don't have access to this encounter.", recoverable=False)
    return enc


def _row(enc: Encounter, student: User, tz: str) -> EncounterRow:
    # List rows intentionally carry no symptom or intake preview.
    return EncounterRow(
        id=enc.id, student_name=student.display_name, starts_at=to_local(enc.starts_at, tz), visit_type=enc.visit_type,
        status=enc.status, status_label=STATUS_LABELS.get(enc.status, enc.status), source_mode=enc.source_mode,
    )


def _assigned(db: Session, clinician: User) -> list[tuple[Encounter, User]]:
    return list(
        db.execute(
            select(Encounter, User)
            .join(User, Encounter.student_id == User.id)
            .where(Encounter.clinician_id == clinician.id, Encounter.status != "CANCELLED")
            .order_by(Encounter.starts_at)
        ).all()
    )


@router.get("/dashboard", response_model=ClinicianDashboard)
def dashboard(user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> ClinicianDashboard:
    s = get_settings()
    start, end = local_day_bounds(s.demo_today, user.timezone)
    rows = _assigned(db, user)
    return ClinicianDashboard(
        today=s.demo_today.isoformat(),
        display_name=user.display_name,
        appointments_today=sum(1 for e, _ in rows if start <= as_utc(e.starts_at) < end),
        intakes_to_review=sum(1 for e, _ in rows if e.status in ("INTAKE_SHARED", "CLINICIAN_REVIEW")),
        absence_cases=sum(
            1 for c in db.scalars(select(AbsenceCase).join(Encounter, AbsenceCase.encounter_id == Encounter.id).where(Encounter.clinician_id == user.id))
            if c.status not in ("SENT", "REJECTED", "REVOKED")
        ),
        encounters=[_row(e, u, user.timezone) for e, u in rows],
    )


@router.get("/encounters", response_model=list[EncounterRow])
def encounters(user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> list[EncounterRow]:
    return [_row(e, u, user.timezone) for e, u in _assigned(db, user)]


@router.get("/encounters/{encounter_id}", response_model=EncounterDetail)
def encounter_detail(encounter_id: str, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> EncounterDetail:
    enc = assigned_encounter(db, user, encounter_id)
    student = db.get(User, enc.student_id)
    assert student is not None
    base = _row(enc, student, user.timezone).model_dump()
    appt = db.get(Appointment, enc.appointment_id) if enc.appointment_id else None
    slot = db.get(ClinicSlot, appt.slot_id) if appt else None
    base.update(purpose=appt.purpose if appt else None, absence_requested=bool(appt and appt.absence_requested),
                ends_at=to_local(slot.ends_at, user.timezone) if slot else None, location=f"{slot.clinic_name}{', ' + slot.location if slot.location else ''}" if slot else None)
    return EncounterDetail(**base, student_id=student.id, student_email=student.email, appointment_id=enc.appointment_id)


@router.get("/activity", response_model=list[ActivityOut])
def clinician_activity(user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> list[ActivityOut]:
    rows = db.scalars(select(AuditEvent).where(AuditEvent.actor_id == user.id).order_by(AuditEvent.id.desc()).limit(100)).all()
    return [ser.activity(a) for a in rows]


@router.get("/encounters/{encounter_id}/intake", response_model=ClinicianIntakeOut)
def encounter_intake(encounter_id: str, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> ClinicianIntakeOut:
    """Only what the student explicitly authorized, for an assigned encounter. Every view is audited."""
    enc = assigned_encounter(db, user, encounter_id)
    p = previsit.current_for_encounter(db, enc)
    if p is None:
        return ClinicianIntakeOut(encounter_id=enc.id, status="NOT_SHARED", packet_id=None, version=None, shared_at=None, fields=[], consent={})
    if p.status == "WITHDRAWN":
        return ClinicianIntakeOut(encounter_id=enc.id, status="WITHDRAWN", packet_id=p.id, version=p.version, shared_at=None, fields=[], consent={})
    sess = db.get(IntakeSession, p.session_id)
    if p.clinician_viewed_at is None:
        p.clinician_viewed_at = utcnow()
        if enc.status == "INTAKE_SHARED":
            enc.status = "CLINICIAN_REVIEW"
    audit.record(db, actor_role="clinician", actor_id=user.id, subject_student_id=enc.student_id, action="INTAKE_VIEWED", object_type="encounter", object_id=enc.id, detail=f"v{p.version}")
    db.commit()
    fields = [IntakeFieldOut(key=f["key"], label=f["label"], value=f["value"], display=f["display"], provenance=f["provenance"], confirmed_by_student=True, updated_at=f["updated_at"]) for f in p.field_snapshot]
    atts = [db.get(Attachment, aid) for aid in (p.attachment_ids or [])]
    attachments = [{"id": a.id, "observations": a.observations, "limitations": a.limitations, "quality": a.quality, "observer": a.observer, "synthetic_demo": a.synthetic_demo, "image_url": f"/api/v1/clinician/encounters/{enc.id}/attachments/{a.id}"} for a in atts if a]
    notes = {}
    for n in db.scalars(select(IntakeAnnotation).where(IntakeAnnotation.packet_id == p.id).order_by(IntakeAnnotation.created_at)).all():
        notes[n.field_key] = {"decision": n.decision, "corrected_value": n.corrected_value, "note": n.note, "at": n.created_at.isoformat()}
    return ClinicianIntakeOut(
        encounter_id=enc.id, status="SHARED", packet_id=p.id, version=p.version, shared_at=p.student_approved_at, fields=fields,
        consent={"intake_shared": True, "voice_transcript_shared": False, "photo_shared": bool(attachments), "voice_used": bool(sess and sess.voice_consent)},
        attachments=attachments, annotations=notes, summary=previsit.summary_of(db, p), consent_text=p.consent_text,
        session={"session_id": p.session_id, "started_at": to_local(sess.created_at, user.timezone).isoformat() if sess else None,
                 "ended_at": to_local(sess.ended_at, user.timezone).isoformat() if sess and sess.ended_at else None,
                 "intake_complete": bool(sess and sess.status != "OPEN"), "version": p.version},
    )


@router.get("/encounters/{encounter_id}/previsit-history")
def previsit_history(encounter_id: str, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> dict:
    """AI-assisted pre-visit history for this encounter's student: only summaries attached to encounters assigned
    to this clinician, one entry per conversation session, grouped by local start date, newest first. Audited."""
    enc = assigned_encounter(db, user, encounter_id)
    out = previsit.history(db, user, enc.student_id, user.timezone)
    audit.record(db, actor_role="clinician", actor_id=user.id, subject_student_id=enc.student_id, action="PREVISIT_HISTORY_VIEWED", object_type="encounter", object_id=enc.id,
                 detail=f"{sum(len(g['sessions']) for g in out['groups'])} sessions")
    db.commit()
    return out


def _shared_packet(db: Session, enc: Encounter) -> HandoffPacket:
    p = previsit.current_for_encounter(db, enc)
    if p is None or p.status != "SHARED":
        raise ApiError(403, "FORBIDDEN", "Nothing is currently shared for this encounter.", recoverable=False)
    return p


@router.get("/encounters/{encounter_id}/attachments/{attachment_id}")
def shared_photo(encounter_id: str, attachment_id: str, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> Response:
    """Only photos the student explicitly selected in a currently shared summary attached to an encounter assigned
    to this clinician (photos from older sessions stay visible in the history while still shared)."""
    enc = assigned_encounter(db, user, encounter_id)
    a = db.get(Attachment, attachment_id)
    if a is None or not previsit.can_view_photo(db, user, enc.student_id, attachment_id):
        raise ApiError(403, "FORBIDDEN", "This photo wasn't shared with you.", recoverable=False)
    audit.record(db, actor_role="clinician", actor_id=user.id, subject_student_id=enc.student_id, action="PHOTO_VIEWED", object_type="attachment", object_id=a.id)
    db.commit()
    return Response(a.data, media_type="image/png", headers={"Cache-Control": "no-store"})


class AnnotationIn(BaseModel):
    field_key: str
    decision: str = Field(pattern="^(accepted|corrected|rejected)$")
    corrected_value: str | None = Field(None, max_length=1000)
    note: str | None = Field(None, max_length=1000)


@router.post("/encounters/{encounter_id}/intake/annotations")
def annotate(encounter_id: str, body: AnnotationIn, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> dict:
    """Clinician accepts, corrects or rejects a student/AI-provided detail; the original stays intact."""
    enc = assigned_encounter(db, user, encounter_id)
    p = _shared_packet(db, enc)
    if body.field_key not in {f["key"] for f in p.field_snapshot}:
        raise ApiError(422, "UNKNOWN_FIELD", "That field isn't in the shared packet.")
    if body.decision == "corrected" and not (body.corrected_value or "").strip():
        raise ApiError(422, "VALUE_REQUIRED", "Enter the corrected value.")
    db.add(IntakeAnnotation(id=f"ann_{uuid4().hex[:8]}", packet_id=p.id, field_key=body.field_key, clinician_id=user.id, decision=body.decision, corrected_value=(body.corrected_value or "").strip() or None, note=body.note))
    audit.record(db, actor_role="clinician", actor_id=user.id, subject_student_id=enc.student_id, action="INTAKE_FIELD_REVIEWED", object_type="encounter", object_id=enc.id, detail=f"{body.field_key}: {body.decision}")
    db.commit()
    return {"field_key": body.field_key, "decision": body.decision}


class EvaluationIn(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


@router.get("/encounters/{encounter_id}/evaluation")
def get_evaluation(encounter_id: str, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> dict:
    enc = assigned_encounter(db, user, encounter_id)
    ev = db.scalar(select(ClinicalEvaluation).where(ClinicalEvaluation.encounter_id == enc.id))
    return {"fields": cfg.EXAMINATION_FIELDS, "values": ev.values if ev else {}, "updated_at": ev.updated_at if ev else None}


@router.put("/encounters/{encounter_id}/evaluation")
def put_evaluation(encounter_id: str, body: EvaluationIn, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> dict:
    """Clinician-entered findings. Only the assigned, verified clinician; content never logged or sent to professors."""
    enc = assigned_encounter(db, user, encounter_id)
    allowed = {f["key"] for f in cfg.EXAMINATION_FIELDS}
    unknown = set(body.values) - allowed
    if unknown:
        raise ApiError(422, "UNKNOWN_FIELD", f"Unknown examination field(s): {', '.join(sorted(unknown))}.")
    ev = db.scalar(select(ClinicalEvaluation).where(ClinicalEvaluation.encounter_id == enc.id))
    clean = {k: v.strip()[:4000] for k, v in body.values.items()}
    if ev is None:
        ev = ClinicalEvaluation(id=f"eval_{uuid4().hex[:8]}", encounter_id=enc.id, clinician_id=user.id, values=clean)
        db.add(ev)
    else:
        ev.values, ev.updated_at, ev.clinician_id = {**ev.values, **clean}, utcnow(), user.id
    audit.record(db, actor_role="clinician", actor_id=user.id, subject_student_id=enc.student_id, action="EVALUATION_SAVED", object_type="encounter", object_id=enc.id, detail=f"{len(clean)} fields")
    db.commit()
    return {"fields": cfg.EXAMINATION_FIELDS, "values": ev.values, "updated_at": ev.updated_at}
