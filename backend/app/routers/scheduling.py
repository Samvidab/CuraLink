"""Clinician-aware scheduling: clinician + time recommendations, explicit confirmation, safe booking."""

from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import curalink_config as cfg
from app import serializers as ser
from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import Appointment, Calendar, CalendarEvent, ClinicianProfile, ClinicSlot, Course, Encounter, IntakeField, IntakeSession, User
from app.routers.student import appointment_summary
from app.routers.system import _demo_only
from app.schemas import AppointmentSummary, BlockIn, CalendarEventOut, SchedulePreferences
from app.security import require_student
from app.services import audit, availability, previsit, scheduling, terms
from app.timeutil import as_utc, demo_now, to_local, utcnow

router = APIRouter(prefix="/api/v1", tags=["scheduling"])
TYPE_LABEL = {t["id"]: t["label"] for t in cfg.APPOINTMENT_TYPES}


class SearchIn(BaseModel):
    appointment_type: str = "routine_checkup"
    clinician_id: str | None = None  # explicit preference: results are ONLY this clinician
    specialty: str | None = None
    attribute: dict[str, str] | None = None  # e.g. {"gender": "woman"}; only self-reported profile attributes
    start: date | None = None  # local date; defaults to the demo "today"
    days: int = Field(5, ge=1, le=21)
    part_of_day: Literal["any", "morning", "afternoon", "evening"] = "any"
    sort: Literal["best", "earliest"] = "best"
    per_clinician: int = Field(8, ge=1, le=40)
    preferences: SchedulePreferences = SchedulePreferences()


class ConfirmIn(BaseModel):
    slot_id: str
    student_approved: bool
    idempotency_key: str = Field(min_length=8, max_length=80)
    intake_session_id: str | None = None  # the conversation this booking came from (default: the open one, if it has content)
    purpose: str | None = Field(None, max_length=300)  # student's own words; never inferred symptoms
    absence_requested: bool | None = None  # student wants to DISCUSS absence documentation; not an approval


def _now() -> datetime:
    s = get_settings()
    return demo_now(s.demo_today, s.demo_timezone)


def busy_for(db: Session, student: User, lo: datetime, hi: datetime) -> list[scheduling.Interval]:
    """Selected-semester class meetings, personal blocks and the student's other appointments."""
    codes = {c.id: c.code for c in db.scalars(select(Course).where(Course.student_id == student.id))}
    events = db.scalars(select(CalendarEvent).where(CalendarEvent.student_id == student.id, CalendarEvent.start_at < hi, CalendarEvent.end_at > lo, CalendarEvent.all_day.is_(False), terms.term_filter(terms.selected(db, student)))).all()
    busy = [scheduling.Interval(as_utc(e.start_at), as_utc(e.end_at), (codes.get(e.course_id) if e.course_id else None) or e.summary, e.id) for e in events]
    for appt, slot in db.execute(select(Appointment, ClinicSlot).join(ClinicSlot).where(Appointment.student_id == student.id, Appointment.state == "DEMO_CONFIRMED", ClinicSlot.starts_at < hi, ClinicSlot.ends_at > lo)).all():
        busy.append(scheduling.Interval(as_utc(slot.starts_at), as_utc(slot.ends_at), "Personal: your other appointment", appt.id))
    return busy


def _part(local: datetime) -> str:
    return "morning" if local.hour < 12 else "afternoon" if local.hour < 17 else "evening"


def _matches_attribute(p: ClinicianProfile, attribute: dict[str, str] | None) -> bool:
    if not attribute:
        return True
    attrs = p.attributes or {}
    return all(isinstance(attrs.get(k), dict) and attrs[k].get("source") and attrs[k].get("value") == v for k, v in attribute.items())


def _slot_out(c: availability.Candidate, p: ClinicianProfile, name: str, tz: str, r: scheduling.Ranked | None) -> dict:
    return {
        "id": c.id, "clinician_id": c.clinician_id, "clinician_name": name, "appointment_type": c.appointment_type, "appointment_label": TYPE_LABEL.get(c.appointment_type, c.appointment_type),
        "starts_at": to_local(c.starts_at, tz).isoformat(), "ends_at": to_local(c.ends_at, tz).isoformat(), "minutes": int((c.ends_at - c.starts_at).total_seconds() // 60),
        "clinic_name": p.clinic_name, "location": p.location, "travel_minutes": p.travel_minutes,
        "score": r.score if r else None, "reason_codes": r.reason_codes if r else [], "source_mode": "demo",
    }


def _rank_for(db: Session, user: User, p: ClinicianProfile, req: SearchIn, first: date, days: int) -> tuple[list[tuple[availability.Candidate, scheduling.Ranked]], Counter]:
    now = _now()
    tz = user.timezone
    cands = availability.candidates(db, p, req.appointment_type, first, days, now)
    if req.part_of_day != "any":
        cands = [c for c in cands if _part(to_local(c.starts_at, tz)) == req.part_of_day]
    by_id = {c.id: c for c in cands}
    slots = [scheduling.Slot(c.id, c.starts_at, c.ends_at, c.appointment_type, p.travel_minutes) for c in cands]
    lo = datetime.combine(first, time.min, ZoneInfo(tz))
    pref = req.preferences
    ranked, rejected = scheduling.rank_slots(
        slots, busy_for(db, user, lo - timedelta(hours=2), lo + timedelta(days=days, hours=2)),
        scheduling.Preferences(appointment_type=req.appointment_type, avoid_class_conflicts=pref.avoid_class_conflicts, max_travel_minutes=pref.max_travel_minutes, earliest_hour=pref.earliest_hour, latest_hour=pref.latest_hour, allow_conflicts=pref.allow_conflicts),
        now, ZoneInfo(tz),
    )
    if req.sort == "earliest":
        ranked.sort(key=lambda r: (r.slot.starts_at, r.score, r.slot.id))
    return [(by_id[r.slot.id], r) for r in ranked], Counter(r.reason_code for r in rejected)


def search(db: Session, user: User, req: SearchIn) -> dict:
    """The single source of appointment options for the Appointments page AND the assistant."""
    if req.appointment_type not in TYPE_LABEL:
        raise ApiError(422, "UNKNOWN_APPOINTMENT_TYPE", "Choose an appointment type offered by the clinic.")
    tz = user.timezone
    first = req.start or get_settings().demo_today
    profiles = availability.active_profiles(db)
    requested = None
    if req.clinician_id:
        requested = next((p for p in profiles if p.clinician_id == req.clinician_id), None)
        if requested is None:
            raise ApiError(404, "UNKNOWN_CLINICIAN", "That clinician isn't available for booking in this demo.")
        profiles = [requested]
    if req.specialty:
        profiles = [p for p in profiles if p.specialty == req.specialty]
    if req.attribute:
        profiles = [p for p in profiles if _matches_attribute(p, req.attribute)]
    names = {u.id: u.display_name for u in db.scalars(select(User).where(User.role == "clinician")).all()}

    cards, flat, rejected_total = [], [], Counter()
    for p in profiles:
        offers_type = req.appointment_type in (p.appointment_types or [])
        pairs, rejected = _rank_for(db, user, p, req, first, req.days) if offers_type else ([], Counter())
        rejected_total.update(rejected)
        slots = [_slot_out(c, p, names.get(p.clinician_id, p.clinician_id), tz, r) for c, r in pairs]
        flat.extend(slots)
        cards.append({**availability.profile_out(db, p), "offers_type": offers_type, "slots": slots[: req.per_clinician], "total_available": len(slots), "excluded": dict(rejected)})
    if req.sort == "earliest":
        flat.sort(key=lambda s: (s["starts_at"], s["score"] or 0, s["id"]))
    else:
        flat.sort(key=lambda s: (s["score"] or 0, s["starts_at"], s["id"]))
    cards.sort(key=lambda c: (not c["slots"], c["slots"][0]["starts_at"] if c["slots"] else "", c["name"]))

    notice, alternatives = None, {"same_clinician": [], "other_clinicians": []}
    if requested and not flat:
        name = names.get(requested.clinician_id, "That clinician")
        if req.appointment_type not in (requested.appointment_types or []):
            notice = f"{name} doesn't offer {TYPE_LABEL[req.appointment_type].lower()} visits."
        else:
            notice = f"{name} has no openings that fit your classes in this window."
            later, _ = _rank_for(db, user, requested, req.model_copy(update={"part_of_day": "any"}), first + timedelta(days=req.days), 14)
            alternatives["same_clinician"] = [_slot_out(c, requested, name, tz, r) for c, r in later[:4]]
        others = [p for p in availability.active_profiles(db) if p.clinician_id != requested.clinician_id]
        for p in others:
            pairs, _ = _rank_for(db, user, p, req, first, req.days) if req.appointment_type in (p.appointment_types or []) else ([], Counter())
            alternatives["other_clinicians"] += [_slot_out(c, p, names.get(p.clinician_id, p.clinician_id), tz, r) for c, r in pairs[:2]]
    elif not flat:
        notice = "No eligible appointments matched your calendar. Try another date or contact the clinic." if profiles else "No clinician matches that preference in this demo."
    has_calendar = db.scalar(select(Calendar.id).where(Calendar.student_id == user.id)) is not None
    return {
        "appointment_type": req.appointment_type, "appointment_label": TYPE_LABEL[req.appointment_type], "start": first.isoformat(), "days": req.days,
        "part_of_day": req.part_of_day, "sort": req.sort, "clinician_id": req.clinician_id,
        "clinicians": cards, "options": flat[:12], "excluded": dict(rejected_total), "notice": notice, "alternatives": alternatives,
        "calendar_considered": has_calendar, "term": terms.selected(db, user), "source_mode": "demo", "generated_at": utcnow().isoformat(),
    }


@router.get("/clinicians")
def clinicians(user: User = Depends(require_student), db: Session = Depends(get_db)) -> dict:
    profiles = availability.active_profiles(db)
    return {"clinicians": [availability.profile_out(db, p) for p in profiles], "appointment_types": cfg.APPOINTMENT_TYPES,
            "specialties": sorted({p.specialty for p in profiles}), "source_mode": "demo"}


@router.post("/schedule/search")
def schedule_search(body: SearchIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> dict:
    return search(db, user, body)


@router.post("/appointments/confirm")
def confirm(body: ConfirmIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> dict:
    if not body.student_approved:
        raise ApiError(400, "APPROVAL_REQUIRED", "Confirm that you want to reserve this demo time.")
    tz = user.timezone
    existing = db.scalar(select(Appointment).where(Appointment.student_id == user.id, Appointment.idempotency_key == body.idempotency_key))
    if existing:  # double click / retry / repeated assistant event: same result, no second booking
        slot = db.get(ClinicSlot, existing.slot_id)
        if slot and availability.parse_slot_id(body.slot_id)[1] != as_utc(slot.starts_at):
            raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "This confirmation was already used for a different time.")
        return _confirm_out(db, existing, tz, "Already confirmed.")
    cand, profile = availability.validate(db, body.slot_id, _now())  # re-check clinician availability NOW
    conflicts = scheduling.find_conflicts(scheduling.Slot(cand.id, cand.starts_at, cand.ends_at, cand.appointment_type, profile.travel_minutes), busy_for(db, user, cand.starts_at - timedelta(hours=3), cand.ends_at + timedelta(hours=3)))
    if any(c.kind in ("CLASS_OVERLAP", "PERSONAL_BLOCK") for c in conflicts):
        raise ApiError(409, "CLASS_CONFLICT", "This time overlaps with your schedule or another appointment. Pick another option.", details={"conflicts": [c.label.removeprefix("Personal: ") for c in conflicts]})
    sess = _booking_session(db, user, body.intake_session_id)
    slot = availability.book(db, cand, profile)
    purpose = (body.purpose or "").strip() or (sess.purpose if sess else None)
    absence = body.absence_requested if body.absence_requested is not None else bool(sess and sess.absence_requested)
    appt = Appointment(id=f"apt_{uuid4().hex[:10]}", student_id=user.id, slot_id=slot.id, clinician_id=cand.clinician_id, appointment_type=cand.appointment_type, state="DEMO_CONFIRMED",
                       confirmation_mode="demo", idempotency_key=body.idempotency_key, intake_session_id=sess.id if sess else None, purpose=purpose, absence_requested=absence)
    db.add(appt)
    db.flush()
    enc = Encounter(id=f"enc_{uuid4().hex[:10]}", student_id=user.id, clinician_id=cand.clinician_id, appointment_id=appt.id, starts_at=cand.starts_at, visit_type=TYPE_LABEL.get(cand.appointment_type, cand.appointment_type), status="UPCOMING")
    db.add(enc)
    db.flush()
    attached = previsit.attach_pending(db, user.id, enc)  # summaries the student approved "for the clinician I book next"
    audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="APPOINTMENT_DEMO_CONFIRMED", object_type="appointment", object_id=appt.id, from_state="OFFERED", to_state="DEMO_CONFIRMED",
                 detail=f"clinician {cand.clinician_id}; case {enc.id}" + (f"; session {sess.id}" if sess else "") + ("; absence documentation requested" if absence else "") + (f"; {attached} summaries attached" if attached else ""))
    db.commit()
    return _confirm_out(db, appt, tz, "Demo appointment — not booked with a real clinic.")


def _booking_session(db: Session, user: User, session_id: str | None) -> IntakeSession | None:
    if session_id:
        sess = db.get(IntakeSession, session_id)
        if sess is None or sess.student_id != user.id:
            raise ApiError(404, "NOT_FOUND", "Conversation not found.")
        return sess
    sess = db.scalar(select(IntakeSession).where(IntakeSession.student_id == user.id, IntakeSession.status == "OPEN").order_by(IntakeSession.created_at.desc()))
    has_content = sess is not None and (sess.chief_concern or sess.purpose or db.scalar(select(IntakeField.id).where(IntakeField.session_id == sess.id)))
    return sess if has_content else None


def _confirm_out(db: Session, appt: Appointment, tz: str, message: str) -> dict:
    slot = db.get(ClinicSlot, appt.slot_id)
    enc = db.scalar(select(Encounter).where(Encounter.appointment_id == appt.id))
    return {"appointment_id": appt.id, "status": appt.state, "external_booking": False, "appointment": appointment_summary(appt, slot, tz, db).model_dump(), "message": message,
            "case_id": enc.id if enc else None, "intake_session_id": appt.intake_session_id, "purpose": appt.purpose, "absence_requested": bool(appt.absence_requested)}


@router.get("/appointments/me", response_model=list[AppointmentSummary])
def my_appointments(user: User = Depends(require_student), db: Session = Depends(get_db)) -> list[AppointmentSummary]:
    rows = db.execute(select(Appointment, ClinicSlot).join(ClinicSlot).where(Appointment.student_id == user.id).order_by(ClinicSlot.starts_at)).all()
    return [appointment_summary(a, s, user.timezone, db) for a, s in rows]


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentSummary)
def cancel(appointment_id: str, user: User = Depends(require_student), db: Session = Depends(get_db)) -> AppointmentSummary:
    """Cancelling frees the clinician's time. Choosing a different clinician = cancel + new booking (both audited)."""
    appt = db.get(Appointment, appointment_id)
    if appt is None or appt.student_id != user.id:
        raise ApiError(404, "NOT_FOUND", "Appointment not found.")
    slot = db.get(ClinicSlot, appt.slot_id)
    if appt.state == "DEMO_CONFIRMED":
        appt.state = "CANCELLED"
        if slot and slot.status == "BOOKED":
            slot.status = "CANCELLED"
        for enc in db.scalars(select(Encounter).where(Encounter.appointment_id == appt.id)):
            enc.status = "CANCELLED"
        audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="APPOINTMENT_CANCELLED", object_type="appointment", object_id=appt.id, from_state="DEMO_CONFIRMED", to_state="CANCELLED", detail=f"clinician {appt.clinician_id}")
        db.commit()
    return appointment_summary(appt, slot, user.timezone, db)


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
    ev = CalendarEvent(id=f"blk_{uuid4().hex[:10]}", calendar_id=cal.id, student_id=user.id, uid=f"block-{uuid4().hex}", summary=f"Personal: {body.label.strip()}",
                       start_at=as_utc(body.start_at), end_at=as_utc(body.end_at), tzid=user.timezone, kind="personal_block", source="manual")
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


class OtherBookingIn(BaseModel):
    slot_id: str


@router.post("/demo/book-as-other", dependencies=[Depends(_demo_only)])
def book_as_other(body: OtherBookingIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> dict:
    """Demo control: another (fictional) student books this exact time, to show stale-slot recovery."""
    cand, profile = availability.validate(db, body.slot_id, _now())
    slot = availability.book(db, cand, profile)
    db.add(Appointment(id=f"apt_{uuid4().hex[:10]}", student_id="demo-student-3", slot_id=slot.id, clinician_id=cand.clinician_id, appointment_type=cand.appointment_type, state="DEMO_CONFIRMED", idempotency_key=f"other-{uuid4().hex[:8]}"))
    audit.record(db, actor_role="system", actor_id=None, subject_student_id=user.id, action="DEMO_SLOT_TAKEN_BY_OTHER", object_type="clinic_slot", object_id=slot.id)
    db.commit()
    return {"slot_id": body.slot_id, "status": "BOOKED_BY_SOMEONE_ELSE"}
