from datetime import date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import Appointment, Calendar, CalendarEvent, ClinicSlot, Course, Encounter, User
from app.routers.student import appointment_summary
from app.routers.system import _demo_only
from app.schemas import (
    AppointmentSummary,
    AppointmentType,
    BlockIn,
    CalendarEventOut,
    ConfirmIn,
    ConfirmOut,
    ConflictOut,
    OptionOut,
    RecommendationIn,
    RecommendationsOut,
    RejectedOut,
    SlotOut,
    SlotsOut,
)
from app import serializers as ser
from app.security import require_student
from app.services import audit, scheduling
from app.services.clinic_adapter import get_adapter
from app.timeutil import as_utc, demo_now, to_local, utcnow

router = APIRouter(prefix="/api/v1", tags=["scheduling"])


def slot_out(s: ClinicSlot, tz: str) -> SlotOut:
    return SlotOut(
        id=s.id, clinic_id=s.clinic_id, clinic_name=s.clinic_name, location=s.location, appointment_type=s.appointment_type,
        starts_at=to_local(s.starts_at, tz), ends_at=to_local(s.ends_at, tz), travel_minutes=s.travel_minutes,
        status=s.status, permitted=s.permitted, source_mode=s.source_mode,
    )


def _window(start: str | None, days: int, tz: str) -> tuple[datetime, datetime]:
    first = date.fromisoformat(start) if start else get_settings().demo_today
    zone = ZoneInfo(tz)
    return datetime.combine(first, time.min, zone), datetime.combine(first + timedelta(days=days), time.min, zone)


def _busy(db: Session, student: User, lo: datetime, hi: datetime) -> list[scheduling.Interval]:
    codes = {c.id: c.code for c in db.scalars(select(Course).where(Course.student_id == student.id))}
    events = db.scalars(
        select(CalendarEvent).where(CalendarEvent.student_id == student.id, CalendarEvent.start_at < hi, CalendarEvent.end_at > lo, CalendarEvent.all_day.is_(False))
    ).all()
    busy = [
        scheduling.Interval(as_utc(e.start_at), as_utc(e.end_at), (codes.get(e.course_id) if e.course_id else None) or e.summary, e.id)
        for e in events
    ]
    # Existing demo appointments are busy time too.
    for appt, slot in db.execute(
        select(Appointment, ClinicSlot).join(ClinicSlot).where(Appointment.student_id == student.id, Appointment.state == "DEMO_CONFIRMED")
    ).all():
        busy.append(scheduling.Interval(as_utc(slot.starts_at), as_utc(slot.ends_at), "Personal: existing demo appointment", appt.id))
    return busy


def _to_slot(s: ClinicSlot) -> scheduling.Slot:
    return scheduling.Slot(s.id, as_utc(s.starts_at), as_utc(s.ends_at), s.appointment_type, s.travel_minutes, s.status == "AVAILABLE", s.permitted)


def _conflicts(cs: list[scheduling.Conflict]) -> list[ConflictOut]:
    return [ConflictOut(label=c.label.removeprefix("Personal: "), event_id=c.ref_id, kind=c.kind, overlap_minutes=c.overlap_minutes) for c in cs]


@router.get("/clinic/slots", response_model=SlotsOut)
def list_slots(
    start: str | None = Query(None),
    days: int = Query(5, ge=1, le=21),
    appointment_type: str | None = Query(None),
    user: User = Depends(require_student),
    db: Session = Depends(get_db),
) -> SlotsOut:
    adapter = get_adapter(db)
    lo, hi = _window(start, days, user.timezone)
    return SlotsOut(
        slots=[slot_out(s, user.timezone) for s in adapter.list_slots(lo, hi, appointment_type)],
        inventory_updated_at=adapter.inventory_updated_at(),
        source_mode=adapter.source_mode,
        appointment_types=[AppointmentType(**t) for t in adapter.appointment_types()],
    )


@router.post("/schedule/recommendations", response_model=RecommendationsOut)
def recommendations(body: RecommendationIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> RecommendationsOut:
    s = get_settings()
    adapter = get_adapter(db)
    tz = user.timezone
    lo, hi = _window(body.start, body.days, tz)
    slots = adapter.list_slots(lo, hi, None)  # type filtering happens in the engine so it can explain rejections
    if body.appointment_type and body.appointment_type not in {t["id"] for t in adapter.appointment_types()}:
        raise ApiError(422, "UNKNOWN_APPOINTMENT_TYPE", "Choose an appointment type offered by the clinic.")
    p = body.preferences
    prefs = scheduling.Preferences(
        appointment_type=body.appointment_type, avoid_class_conflicts=p.avoid_class_conflicts, max_travel_minutes=p.max_travel_minutes,
        earliest_hour=p.earliest_hour, latest_hour=p.latest_hour, allow_conflicts=p.allow_conflicts,
    )
    ranked, rejected = scheduling.rank_slots(
        [_to_slot(x) for x in slots], _busy(db, user, lo - timedelta(hours=2), hi + timedelta(hours=2)), prefs, demo_now(s.demo_today, tz), ZoneInfo(tz)
    )
    by_id = {x.id: x for x in slots}
    has_calendar = db.scalar(select(Calendar.id).where(Calendar.student_id == user.id)) is not None
    return RecommendationsOut(
        options=[
            OptionOut(rank=i + 1, slot=slot_out(by_id[r.slot.id], tz), score=r.score, reason_codes=r.reason_codes, conflicts=_conflicts(r.conflicts), source_mode=adapter.source_mode)
            for i, r in enumerate(ranked)
        ],
        # Wrong-type slots aren't "rejected" in any useful sense; leave them out of the explanation pane.
        rejected=[RejectedOut(slot=slot_out(by_id[r.slot.id], tz), reason_code=r.reason_code, conflicts=_conflicts(r.conflicts)) for r in rejected if r.reason_code != "WRONG_APPOINTMENT_TYPE"],
        calendar_considered=has_calendar,
        generated_at=utcnow(),
        source_mode=adapter.source_mode,
        scoring={
            "wait_points_per_day": scheduling.WAIT_POINTS_PER_DAY,
            "travel_points_per_10_min": scheduling.TRAVEL_POINTS_PER_10_MIN,
            "outside_preferred_hours": scheduling.OUTSIDE_PREFERRED_WINDOW,
            "tight_gap_penalty": scheduling.TIGHT_GAP_PENALTY,
        },
    )


@router.post("/appointments/confirm", response_model=ConfirmOut)
def confirm(body: ConfirmIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> ConfirmOut:
    if not body.student_approved:
        raise ApiError(400, "APPROVAL_REQUIRED", "Confirm that you want to reserve this demo time.")
    tz = user.timezone
    # Idempotency: a repeated request (double click, retry) returns the original result.
    existing = db.scalar(select(Appointment).where(Appointment.student_id == user.id, Appointment.idempotency_key == body.idempotency_key))
    if existing:
        if existing.slot_id != body.slot_id:
            raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "This confirmation was already used for a different time.")
        slot = db.get(ClinicSlot, existing.slot_id)
        return ConfirmOut(appointment_id=existing.id, status=existing.state, appointment=appointment_summary(existing, slot, tz), message="Already confirmed.")

    adapter = get_adapter(db)
    slot = adapter.get(body.slot_id)
    # Re-run hard constraints against the current calendar before reserving.
    lo, hi = as_utc(slot.starts_at) - timedelta(hours=3), as_utc(slot.ends_at) + timedelta(hours=3)
    conflicts = scheduling.find_conflicts(_to_slot(slot), _busy(db, user, lo, hi))
    if any(c.kind in ("CLASS_OVERLAP", "PERSONAL_BLOCK") for c in conflicts):
        raise ApiError(409, "CLASS_CONFLICT", "This time overlaps with your schedule. Pick another option.", details={"conflicts": [c.label for c in conflicts]})
    slot = adapter.reserve(body.slot_id)
    appt = Appointment(id=f"apt_{uuid4().hex[:10]}", student_id=user.id, slot_id=slot.id, state="DEMO_CONFIRMED", confirmation_mode="demo", idempotency_key=body.idempotency_key)
    db.add(appt)
    if slot.clinician_id:
        db.add(Encounter(id=f"enc_{uuid4().hex[:10]}", student_id=user.id, clinician_id=slot.clinician_id, appointment_id=appt.id, starts_at=slot.starts_at, visit_type=next((t["label"] for t in adapter.appointment_types() if t["id"] == slot.appointment_type), slot.appointment_type), status="UPCOMING"))
    audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="APPOINTMENT_DEMO_CONFIRMED", object_type="appointment", object_id=appt.id, from_state="OFFERED", to_state="DEMO_CONFIRMED", detail=f"slot {slot.id}")
    db.commit()
    return ConfirmOut(
        appointment_id=appt.id, status=appt.state, appointment=appointment_summary(appt, slot, tz),
        message="Demo appointment — not booked with a real clinic.",
    )


@router.get("/appointments/me", response_model=list[AppointmentSummary])
def my_appointments(user: User = Depends(require_student), db: Session = Depends(get_db)) -> list[AppointmentSummary]:
    rows = db.execute(
        select(Appointment, ClinicSlot).join(ClinicSlot).where(Appointment.student_id == user.id).order_by(ClinicSlot.starts_at)
    ).all()
    return [appointment_summary(a, s, user.timezone) for a, s in rows]


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentSummary)
def cancel(appointment_id: str, user: User = Depends(require_student), db: Session = Depends(get_db)) -> AppointmentSummary:
    appt = db.get(Appointment, appointment_id)
    if appt is None or appt.student_id != user.id:
        raise ApiError(404, "NOT_FOUND", "Appointment not found.")
    if appt.state == "DEMO_CONFIRMED":
        get_adapter(db).release(appt.slot_id)
        appt.state = "CANCELLED"
        for enc in db.scalars(select(Encounter).where(Encounter.appointment_id == appt.id)):
            enc.status = "CANCELLED"
        audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="APPOINTMENT_CANCELLED", object_type="appointment", object_id=appt.id, from_state="DEMO_CONFIRMED", to_state="CANCELLED")
        db.commit()
    return appointment_summary(appt, db.get(ClinicSlot, appt.slot_id), user.timezone)


@router.post("/calendar/blocks", response_model=CalendarEventOut)
def add_block(body: BlockIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> CalendarEventOut:
    if body.end_at <= body.start_at or body.end_at - body.start_at > timedelta(hours=12):
        raise ApiError(422, "INVALID_BLOCK", "A personal block must end after it starts and last at most 12 hours.")
    if body.start_at.tzinfo is None:
        raise ApiError(422, "TIMEZONE_REQUIRED", "Include a UTC offset with block times.")
    cal = db.scalar(select(Calendar).where(Calendar.student_id == user.id))
    if cal is None:
        cal = Calendar(id=f"cal_{uuid4().hex[:10]}", student_id=user.id, source_mode="demo", filename=None, timezone=user.timezone, events_imported=0, warnings=[])
        db.add(cal)
        db.flush()
    ev = CalendarEvent(
        id=f"blk_{uuid4().hex[:10]}", calendar_id=cal.id, student_id=user.id, uid=f"block-{uuid4().hex}", summary=f"Personal: {body.label.strip()}",
        start_at=as_utc(body.start_at), end_at=as_utc(body.end_at), tzid=user.timezone, kind="personal_block", source="manual",
    )
    db.add(ev)
    db.commit()
    return ser.event(ev, user.timezone, {})


@router.delete("/calendar/blocks/{block_id}", status_code=204)
def delete_block(block_id: str, user: User = Depends(require_student), db: Session = Depends(get_db)) -> None:
    ev = db.get(CalendarEvent, block_id)
    if ev is None or ev.student_id != user.id or ev.kind != "personal_block":
        raise ApiError(404, "NOT_FOUND", "Block not found.")
    db.delete(ev)
    db.commit()


@router.post("/demo/slots/{slot_id}/invalidate", response_model=SlotOut, dependencies=[Depends(_demo_only)])
def invalidate_slot(slot_id: str, user: User = Depends(require_student), db: Session = Depends(get_db)) -> SlotOut:
    """Demo control: simulate another student taking a slot (stale-slot scenario, AT-05)."""
    slot = get_adapter(db).get(slot_id)
    if slot.status == "AVAILABLE":
        slot.status = "UNAVAILABLE"
        audit.record(db, actor_role="system", actor_id=None, subject_student_id=user.id, action="DEMO_SLOT_INVALIDATED", object_type="clinic_slot", object_id=slot.id, to_state="UNAVAILABLE")
        db.commit()
    return slot_out(slot, user.timezone)
