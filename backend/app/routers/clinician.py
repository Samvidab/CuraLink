from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import serializers as ser
from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import AbsenceCase, AuditEvent, Encounter, HandoffPacket, IntakeSession, User
from app.schemas import ActivityOut, ClinicianDashboard, ClinicianIntakeOut, EncounterDetail, EncounterRow, IntakeFieldOut
from app.services import audit
from app.timeutil import utcnow
from app.security import require_clinician
from app.timeutil import as_utc, local_day_bounds, to_local

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
    base = _row(enc, student, user.timezone)
    return EncounterDetail(**base.model_dump(), student_id=student.id, student_email=student.email, appointment_id=enc.appointment_id)


@router.get("/activity", response_model=list[ActivityOut])
def clinician_activity(user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> list[ActivityOut]:
    rows = db.scalars(select(AuditEvent).where(AuditEvent.actor_id == user.id).order_by(AuditEvent.id.desc()).limit(100)).all()
    return [ser.activity(a) for a in rows]


@router.get("/encounters/{encounter_id}/intake", response_model=ClinicianIntakeOut)
def encounter_intake(encounter_id: str, user: User = Depends(require_clinician), db: Session = Depends(get_db)) -> ClinicianIntakeOut:
    """Only what the student explicitly authorized, for an assigned encounter. Every view is audited."""
    enc = assigned_encounter(db, user, encounter_id)
    p = db.scalar(select(HandoffPacket).where(HandoffPacket.encounter_id == enc.id).order_by(HandoffPacket.version.desc()))
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
    return ClinicianIntakeOut(
        encounter_id=enc.id, status="SHARED", packet_id=p.id, version=p.version, shared_at=p.student_approved_at, fields=fields,
        consent={"intake_shared": True, "voice_transcript_shared": False, "photo_shared": False, "voice_used": bool(sess and sess.voice_consent)},
    )
