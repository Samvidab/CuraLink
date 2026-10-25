from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import serializers as ser
from app.config import get_settings
from app.db import get_db
from app.errors import ApiError
from app.models import Appointment, AuditEvent, Calendar, CalendarEvent, ClinicSlot, Course, User
from app.schemas import (
    ActivityOut,
    AppointmentSummary,
    CalendarEventsOut,
    CalendarImportOut,
    MeOut,
    ProfileIn,
    StudentDashboard,
)
from app.routers.auth import me_out
from app.security import require_student
from app.services import audit, names, terms
from app.services.calendar_service import import_calendar
from app.services.ics_import import validate_upload
from app.timeutil import local_day_bounds, to_local

router = APIRouter(prefix="/api/v1", tags=["student"])


def _course_codes(db: Session, student_id: str) -> dict[str, str]:
    return {c.id: c.code for c in db.scalars(select(Course).where(Course.student_id == student_id))}


def events_between(db: Session, student: User, start: datetime, end: datetime, term: str | None | bool = True) -> list[CalendarEvent]:
    """term=True -> the student's selected term; a string -> that term; None/False -> all terms."""
    t = terms.selected(db, student) if term is True else (term or None)
    return list(
        db.scalars(
            select(CalendarEvent)
            .where(CalendarEvent.student_id == student.id, CalendarEvent.start_at < end, CalendarEvent.end_at > start, terms.term_filter(t))
            .order_by(CalendarEvent.start_at)
        )
    )


def appointment_summary(appt: Appointment, slot: ClinicSlot, tz: str, db: Session | None = None) -> AppointmentSummary:
    clinician_id = appt.clinician_id or slot.clinician_id
    doc = db.get(User, clinician_id) if db is not None and clinician_id else None
    return AppointmentSummary(
        id=appt.id, state=appt.state, clinician_id=clinician_id, clinician_name=doc.display_name if doc else None,
        appointment_type=appt.appointment_type or slot.appointment_type, clinic_name=slot.clinic_name,
        location=slot.location, starts_at=to_local(slot.starts_at, tz), ends_at=to_local(slot.ends_at, tz),
        source_mode=slot.source_mode,
    )


@router.patch("/students/me/profile", response_model=MeOut)
def update_profile(body: ProfileIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> MeOut:
    """Names are saved to the SIGNED-IN student's own row (the session decides who; nothing in the body can)."""
    first, last = names.clean(body.first_name, "first name"), names.clean(body.last_name, "last name")
    user.first_name, user.last_name = first, last
    user.preferred_name = names.clean(body.preferred_name, "preferred name", required=False)
    user.display_name = f"{first} {last}"
    audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="PROFILE_UPDATED", object_type="user", object_id=user.id)
    db.commit()
    return me_out(user)


@router.get("/students/me/dashboard", response_model=StudentDashboard)
def dashboard(user: User = Depends(require_student), db: Session = Depends(get_db)) -> StudentDashboard:
    s = get_settings()
    tz = user.timezone
    start, end = local_day_bounds(s.demo_today, tz)
    codes = _course_codes(db, user.id)
    cal = db.scalar(select(Calendar).where(Calendar.student_id == user.id))
    term = terms.selected(db, user)
    courses = list(db.scalars(select(Course).where(Course.student_id == user.id, (Course.term == term) | Course.term.is_(None) if term else True).order_by(Course.code)))
    next_appt = db.execute(
        select(Appointment, ClinicSlot)
        .join(ClinicSlot, Appointment.slot_id == ClinicSlot.id)
        .where(Appointment.student_id == user.id, Appointment.state == "DEMO_CONFIRMED")
        .order_by(ClinicSlot.starts_at)
    ).first()
    activity = db.scalars(
        select(AuditEvent).where(AuditEvent.subject_student_id == user.id).order_by(AuditEvent.id.desc()).limit(5)
    ).all()
    return StudentDashboard(
        today=s.demo_today.isoformat(),
        term=term,
        timezone=tz,
        display_name=user.display_name,
        calendar=ser.calendar(cal) if cal else None,
        courses=[ser.course(c) for c in courses],
        todays_classes=[ser.event(e, tz, codes) for e in events_between(db, user, start, end) if e.kind == "class"],
        next_appointment=appointment_summary(*next_appt, tz, db) if next_appt else None,
        activity=[ser.activity(a) for a in activity],
    )


@router.post("/calendars/import", response_model=CalendarImportOut)
async def import_ics(file: UploadFile = File(...), user: User = Depends(require_student), db: Session = Depends(get_db)) -> CalendarImportOut:
    data = await file.read(2 * 1024 * 1024 + 1)
    validate_upload(file.filename, file.content_type, data)
    cal, parsed = import_calendar(db, user, data, filename=file.filename, source_mode="uploaded")
    return _import_out(db, user, cal)


@router.post("/calendars/import-sample", response_model=CalendarImportOut)
def import_sample(user: User = Depends(require_student), db: Session = Depends(get_db)) -> CalendarImportOut:
    """Loads the fictional sample calendar (Flow A fallback)."""
    data = (get_settings().sample_data_dir / "sample.ics").read_bytes()
    cal, _ = import_calendar(db, user, data, filename="sample.ics", source_mode="demo")
    return _import_out(db, user, cal)


def _import_out(db: Session, user: User, cal: Calendar) -> CalendarImportOut:
    courses = db.scalars(select(Course).where(Course.student_id == user.id).order_by(Course.code)).all()
    return CalendarImportOut(
        calendar_id=cal.id, events_imported=cal.events_imported, courses=[ser.course(c) for c in courses],
        timezone=cal.timezone, warnings=list(cal.warnings or []), source_mode=cal.source_mode,
    )


@router.delete("/calendars/me", status_code=204)
def delete_calendar(user: User = Depends(require_student), db: Session = Depends(get_db)) -> None:
    db.execute(delete(CalendarEvent).where(CalendarEvent.student_id == user.id))
    db.execute(delete(Calendar).where(Calendar.student_id == user.id))
    db.execute(delete(Course).where(Course.student_id == user.id))
    audit.record(db, actor_role="student", actor_id=user.id, subject_student_id=user.id, action="CALENDAR_DELETED")
    db.commit()


@router.get("/calendar/terms")
def list_terms(user: User = Depends(require_student), db: Session = Depends(get_db)) -> dict:
    available = terms.available(db, user.id)
    return {"terms": available, "selected": terms.selected(db, user), "default": terms.default_term(available), "today": terms.today().isoformat()}


class TermIn(BaseModel):
    term: str


@router.put("/calendar/selected-term")
def select_term(body: TermIn, user: User = Depends(require_student), db: Session = Depends(get_db)) -> dict:
    available = terms.available(db, user.id)
    if body.term not in {t["term"] for t in available}:
        raise ApiError(422, "UNKNOWN_TERM", "That semester isn't in your imported calendar.")
    cal = db.scalar(select(Calendar).where(Calendar.student_id == user.id))
    cal.selected_term = body.term
    db.commit()
    return {"terms": available, "selected": body.term, "default": terms.default_term(available), "today": terms.today().isoformat()}


@router.get("/calendar/review")
def review_schedule(term: str | None = Query(None), user: User = Depends(require_student), db: Session = Depends(get_db)) -> dict:
    """Every detected course with its term, meeting pattern and data source (no filtering, nothing deleted)."""
    tz = user.timezone
    out = []
    for c in db.scalars(select(Course).where(Course.student_id == user.id, (Course.term == term) if term else True).order_by(Course.term, Course.code)).all():
        evs = db.scalars(select(CalendarEvent).where(CalendarEvent.course_id == c.id).order_by(CalendarEvent.start_at)).all()
        pattern: dict[str, int] = {}
        for e in evs:
            st, en = to_local(e.start_at, tz), to_local(e.end_at, tz)
            key = f"{st:%a} {st:%-I:%M %p}–{en:%-I:%M %p}"
            pattern[key] = pattern.get(key, 0) + 1
        out.append({
            **ser.course(c).model_dump(), "meetings": len(evs),
            "first_meeting": to_local(evs[0].start_at, tz).date().isoformat() if evs else None,
            "last_meeting": to_local(evs[-1].start_at, tz).date().isoformat() if evs else None,
            "pattern": sorted(pattern.items(), key=lambda kv: -kv[1])[:6],
            "locations": sorted({e.location for e in evs if e.location})[:4],
            "moved_meetings": sum(1 for e in evs if e.recurrence_id),
        })
    cal = db.scalar(select(Calendar).where(Calendar.student_id == user.id))
    return {"courses": out, "calendar": ser.calendar(cal).model_dump() if cal else None, "timezone": tz, "terms": terms.available(db, user.id), "selected": terms.selected(db, user)}


@router.get("/calendar/events", response_model=CalendarEventsOut)
def calendar_events(
    start: date | None = Query(None),
    end: date | None = Query(None),
    term: str | None = Query(None, description="Defaults to the student's selected semester"),
    user: User = Depends(require_student),
    db: Session = Depends(get_db),
) -> CalendarEventsOut:
    s = get_settings()
    tz = user.timezone
    first = start or (s.demo_today - timedelta(days=s.demo_today.weekday()))
    last = end or (first + timedelta(days=7))
    if (last - first).days > 120:
        raise ApiError(422, "RANGE_TOO_LARGE", "Request at most 120 days of events at a time.")
    zone = ZoneInfo(tz)
    lo = datetime.combine(first, time.min, zone)
    hi = datetime.combine(last, time.min, zone)
    cal = db.scalar(select(Calendar).where(Calendar.student_id == user.id))
    codes = _course_codes(db, user.id)
    selected = term or terms.selected(db, user)
    return CalendarEventsOut(
        events=[ser.event(e, tz, codes) for e in events_between(db, user, lo, hi, selected)],
        timezone=cal.timezone if cal else tz,
        calendar=ser.calendar(cal) if cal else None,
        term=selected,
    )


@router.get("/students/me/activity", response_model=list[ActivityOut])
def student_activity(user: User = Depends(require_student), db: Session = Depends(get_db)) -> list[ActivityOut]:
    rows = db.scalars(select(AuditEvent).where(AuditEvent.subject_student_id == user.id).order_by(AuditEvent.id.desc()).limit(100)).all()
    return [ser.activity(a) for a in rows]

