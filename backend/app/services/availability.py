"""Clinician availability -> candidate appointment times -> safe booking.

Candidate times are GENERATED from stored data only:
  weekly AvailabilityRule windows (clinician's local timezone)
  + AvailabilityException ('extra' hours) - AvailabilityException ('unavailable' days/periods)
  - the clinician's existing BOOKED intervals,
  on a SLOT_STEP_MINUTES grid where the full APPOINTMENT_DURATION fits.
Nothing is hardcoded and nothing is invented: no rule, no slot.

Slot ids are "<clinician_id>|<UTC start ISO>|<appointment_type>" so the backend can re-validate the exact
interval at confirmation time; a displayed slot is never a reservation.
"""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import curalink_config as cfg
from app.config import get_settings
from app.errors import ApiError
from app.models import AvailabilityException, AvailabilityRule, ClinicianProfile, ClinicSlot, User
from app.timeutil import as_utc

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def duration(appointment_type: str) -> timedelta:
    return timedelta(minutes=cfg.APPOINTMENT_DURATION.get(appointment_type, cfg.DEFAULT_APPOINTMENT_DURATION))


# CURALINK_CONFIG: DEMO_CLINICIAN_AVAILABILITY
# Fictional working hours/exceptions live in sample_data/demo_availability.json and are loaded at demo reset.
# Production: replace with the clinic's scheduling system feed (same tables). Never presented as a real calendar.
def load_demo(db: Session, only_missing: bool = False) -> list[str]:
    """Insert demo clinician profiles, weekly hours and exceptions. With only_missing=True (existing databases)
    it touches ONLY clinicians that have no profile yet and never changes student calendars, appointments,
    bookings or cases. Returns the clinician ids it configured."""
    s = get_settings()
    data = json.loads((s.sample_data_dir / "demo_availability.json").read_text())
    users = json.loads((s.sample_data_dir / "demo_users.json").read_text())
    configured: list[str] = []
    for c in users["clinicians"]:
        p = c.get("profile")
        if not p or (only_missing and (db.get(ClinicianProfile, c["id"]) is not None or db.get(User, c["id"]) is None)):
            continue
        configured.append(c["id"])
        clinic = data["clinics"][p["clinic_id"]]
        db.add(ClinicianProfile(
            clinician_id=c["id"], specialty=p["specialty"], clinic_id=p["clinic_id"], clinic_name=clinic["name"], location=clinic.get("location"),
            travel_minutes=clinic.get("travel_minutes", 10), timezone=clinic.get("timezone", s.demo_timezone), appointment_types=p["appointment_types"],
            attributes=p.get("attributes", {}), bio=p.get("bio"), photo_url=p.get("photo_url"),
        ))
    for r in data["weekly"]:
        if r["clinician_id"] not in configured:
            continue
        for wd in r["weekdays"]:
            db.add(AvailabilityRule(clinician_id=r["clinician_id"], weekday=WEEKDAYS[wd], start_time=r["start"], end_time=r["end"]))
    for e in data["exceptions"]:
        if e["clinician_id"] not in configured:
            continue
        d0 = date.fromisoformat(e["date"])
        db.add(AvailabilityException(clinician_id=e["clinician_id"], start_date=d0, end_date=date.fromisoformat(e.get("end_date", e["date"])), kind=e["kind"], start_time=e.get("start"), end_time=e.get("end"), reason=e.get("reason")))
    return configured


def ensure_demo_data(db: Session) -> dict:
    """Safe upgrade for demo databases created before clinician-aware scheduling (they have clinicians but no
    profiles or hours, so no clinician cards or times could ever appear). Adds only what is missing:
      - demo clinician profiles/hours/exceptions for clinicians without a profile
      - clinician_id/appointment_type on older appointments, copied from their booked slot
    Nothing is reset or deleted. Run explicitly with: uv run python -m app.admin seed-availability"""
    from app.models import Appointment

    added = load_demo(db, only_missing=True)
    fixed = 0
    for appt in db.scalars(select(Appointment).where(Appointment.clinician_id.is_(None))).all():
        slot = db.get(ClinicSlot, appt.slot_id)
        if slot is not None and slot.clinician_id:
            appt.clinician_id, appt.appointment_type = slot.clinician_id, appt.appointment_type or slot.appointment_type
            fixed += 1
    if added or fixed:
        db.commit()
    return {"clinicians_configured": added, "appointments_backfilled": fixed}


@dataclass(frozen=True)
class Candidate:
    clinician_id: str
    starts_at: datetime  # UTC
    ends_at: datetime  # UTC
    appointment_type: str

    @property
    def id(self) -> str:
        return f"{self.clinician_id}|{self.starts_at.strftime('%Y-%m-%dT%H:%MZ')}|{self.appointment_type}"


def parse_slot_id(slot_id: str) -> tuple[str, datetime, str]:
    try:
        clinician_id, start, appt_type = slot_id.split("|")
        return clinician_id, datetime.strptime(start, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC), appt_type
    except ValueError:
        raise ApiError(422, "INVALID_SLOT", "That appointment option isn't valid. Refresh the list.") from None


def _hm(v: str) -> time:
    h, m = v.split(":")
    return time(int(h), int(m))


def _subtract(windows: list[tuple[datetime, datetime]], cut: tuple[datetime, datetime]) -> list[tuple[datetime, datetime]]:
    out = []
    for s, e in windows:
        if cut[1] <= s or cut[0] >= e:
            out.append((s, e))
            continue
        if s < cut[0]:
            out.append((s, cut[0]))
        if cut[1] < e:
            out.append((cut[1], e))
    return out


def working_windows(db: Session, profile: ClinicianProfile, day: date) -> list[tuple[datetime, datetime]]:
    """UTC windows the clinician works on a local date (DST-safe: built in the clinic's zone)."""
    zone = ZoneInfo(profile.timezone)
    rules = db.scalars(select(AvailabilityRule).where(AvailabilityRule.clinician_id == profile.clinician_id, AvailabilityRule.weekday == day.weekday())).all()
    windows = [
        (datetime.combine(day, _hm(r.start_time), zone).astimezone(UTC), datetime.combine(day, _hm(r.end_time), zone).astimezone(UTC))
        for r in rules
        if (r.effective_from is None or r.effective_from <= day) and (r.effective_to is None or day <= r.effective_to)
    ]
    exceptions = db.scalars(select(AvailabilityException).where(AvailabilityException.clinician_id == profile.clinician_id, AvailabilityException.start_date <= day, AvailabilityException.end_date >= day)).all()
    for ex in exceptions:
        if ex.kind == "extra" and ex.start_time and ex.end_time:
            windows.append((datetime.combine(day, _hm(ex.start_time), zone).astimezone(UTC), datetime.combine(day, _hm(ex.end_time), zone).astimezone(UTC)))
    for ex in exceptions:
        if ex.kind == "unavailable":
            if ex.start_time and ex.end_time:
                windows = _subtract(windows, (datetime.combine(day, _hm(ex.start_time), zone).astimezone(UTC), datetime.combine(day, _hm(ex.end_time), zone).astimezone(UTC)))
            else:
                windows = []
    return sorted(windows)


def booked_intervals(db: Session, clinician_id: str, lo: datetime, hi: datetime) -> list[tuple[datetime, datetime]]:
    rows = db.scalars(select(ClinicSlot).where(ClinicSlot.clinician_id == clinician_id, ClinicSlot.status == "BOOKED", ClinicSlot.starts_at < hi, ClinicSlot.ends_at > lo)).all()
    return [(as_utc(r.starts_at), as_utc(r.ends_at)) for r in rows]


def candidates(db: Session, profile: ClinicianProfile, appointment_type: str, first_day: date, days: int, now: datetime) -> list[Candidate]:
    if appointment_type not in (profile.appointment_types or []) or not profile.accepting:
        return []
    dur, step = duration(appointment_type), timedelta(minutes=cfg.SLOT_STEP_MINUTES)
    out: list[Candidate] = []
    zone = ZoneInfo(profile.timezone)
    lo = datetime.combine(first_day, time.min, zone).astimezone(UTC)
    booked = booked_intervals(db, profile.clinician_id, lo, lo + timedelta(days=days + 1))
    for i in range(days):
        day = first_day + timedelta(days=i)
        for ws, we in working_windows(db, profile, day):
            t = ws
            while t + dur <= we:
                if t > now and not any(max(t, bs) < min(t + dur, be) for bs, be in booked):
                    out.append(Candidate(profile.clinician_id, t, t + dur, appointment_type))
                t += step
    return out


def validate(db: Session, slot_id: str, now: datetime) -> tuple[Candidate, ClinicianProfile]:
    """Re-check a slot against CURRENT data (clinician, type, hours, exceptions, bookings)."""
    clinician_id, start, appt_type = parse_slot_id(slot_id)
    profile = db.get(ClinicianProfile, clinician_id)
    if profile is None:
        raise ApiError(404, "UNKNOWN_CLINICIAN", "That clinician isn't available for booking.")
    if appt_type not in (profile.appointment_types or []):
        raise ApiError(409, "TYPE_NOT_OFFERED", "This clinician doesn't offer that appointment type.")
    cand = Candidate(clinician_id, start, start + duration(appt_type), appt_type)
    if cand.starts_at <= now:
        raise ApiError(409, "SLOT_UNAVAILABLE", "That time has already passed. Here are updated options — nothing was booked.")
    local_day = start.astimezone(ZoneInfo(profile.timezone)).date()
    if not any(ws <= cand.starts_at and cand.ends_at <= we for ws, we in working_windows(db, profile, local_day)):
        raise ApiError(409, "SLOT_UNAVAILABLE", "The clinician is no longer available at that time. Here are updated options — nothing was booked.")
    if any(max(cand.starts_at, bs) < min(cand.ends_at, be) for bs, be in booked_intervals(db, clinician_id, cand.starts_at - timedelta(hours=4), cand.ends_at + timedelta(hours=4))):
        raise ApiError(409, "SLOT_UNAVAILABLE", "That time was just booked. Here are updated options — nothing was booked.")
    return cand, profile


def book(db: Session, cand: Candidate, profile: ClinicianProfile) -> ClinicSlot:
    """Insert the booked interval; the write lock + unique index + post-insert overlap check prevent double-booking."""
    row = ClinicSlot(
        id=f"bk_{uuid4().hex[:12]}", clinic_id=profile.clinic_id, clinic_name=profile.clinic_name, location=profile.location or "",
        appointment_type=cand.appointment_type, starts_at=cand.starts_at, ends_at=cand.ends_at, travel_minutes=profile.travel_minutes,
        clinician_id=cand.clinician_id, status="BOOKED", permitted=True, source_mode="demo",
    )
    db.add(row)
    try:
        db.flush()  # acquires SQLite's write lock: concurrent bookers serialize here
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "SLOT_UNAVAILABLE", "That time was just booked. Here are updated options — nothing was booked.") from None
    clash = db.scalar(select(ClinicSlot.id).where(ClinicSlot.clinician_id == cand.clinician_id, ClinicSlot.status == "BOOKED", ClinicSlot.id != row.id, ClinicSlot.starts_at < cand.ends_at, ClinicSlot.ends_at > cand.starts_at))
    if clash:
        db.rollback()
        raise ApiError(409, "SLOT_UNAVAILABLE", "That time was just booked. Here are updated options — nothing was booked.")
    return row


def profile_out(db: Session, p: ClinicianProfile) -> dict:
    u = db.get(User, p.clinician_id)
    return {
        "clinician_id": p.clinician_id, "name": u.display_name if u else p.clinician_id, "credentials": u.credentials if u else None,
        "specialty": p.specialty, "clinic_id": p.clinic_id, "clinic_name": p.clinic_name, "location": p.location,
        "appointment_types": p.appointment_types, "photo_url": p.photo_url, "bio": p.bio, "timezone": p.timezone,
        "attributes": {k: v for k, v in (p.attributes or {}).items() if isinstance(v, dict) and v.get("source")},
        "source_mode": "demo",
    }


def active_profiles(db: Session) -> list[ClinicianProfile]:
    rows = db.execute(select(ClinicianProfile, User).join(User, User.id == ClinicianProfile.clinician_id).where(User.role == "clinician", User.clinician_verified.is_(True), ClinicianProfile.accepting.is_(True))).all()
    return [p for p, _ in sorted(rows, key=lambda r: r[1].display_name)]
