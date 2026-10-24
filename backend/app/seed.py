"""Fictional demo dataset. `reset_demo` wipes the database and reseeds it."""

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app import db as dbmod
from app.config import get_settings
from app.models import Appointment, ClinicianProfile, ClinicSlot, Encounter, User
from app.services import availability
from app.security import hash_password
from app.services import audit
from app.services.calendar_service import import_calendar

DEMO_PASSWORD = "curalink-demo"


def reset_demo(db: Session) -> None:
    settings = get_settings()
    if not settings.demo_mode:
        raise RuntimeError("Demo reset is disabled outside demo mode.")
    db.close()
    from app.services.absence_service import TestInboxTransport

    TestInboxTransport.fail_next = 0
    # Pooled SQLite connections can hold locks that block DROP TABLE; start clean.
    if dbmod.engine().url.database not in (None, "", ":memory:"):
        dbmod.engine().dispose()
    dbmod.drop_all()
    dbmod.create_all()

    data_dir = settings.sample_data_dir
    users = json.loads((data_dir / "demo_users.json").read_text())
    # One salted hash reused across demo accounts keeps reset fast; all share the published demo password.
    pw = hash_password(DEMO_PASSWORD)
    for s in users["students"]:
        db.add(User(id=s["id"], role="student", display_name=s["display_name"], email=s["email"], password_hash=pw, timezone=settings.demo_timezone))
    for c in users["clinicians"]:
        db.add(User(id=c["id"], role="clinician", display_name=c["display_name"], email=c["email"], password_hash=pw, credentials=c["credentials"], clinician_verified=c["verified"], timezone=settings.demo_timezone))
    db.flush()

    availability.load_demo(db)
    db.flush()
    # Seeded encounters are real bookings: they occupy the clinician's time like any other appointment.
    for e in users["encounters"]:
        start = datetime.fromisoformat(e["starts_at"])
        appt_type = e["appointment_type"]
        profile = db.get(ClinicianProfile, e["clinician_id"])
        slot = ClinicSlot(id=f"bk_seed_{e['id']}", clinic_id=profile.clinic_id, clinic_name=profile.clinic_name, location=profile.location or "", appointment_type=appt_type,
                          starts_at=start, ends_at=start + availability.duration(appt_type), travel_minutes=profile.travel_minutes, clinician_id=e["clinician_id"], status="BOOKED", source_mode="demo")
        appt = Appointment(id=f"apt_seed_{e['id']}", student_id=e["student_id"], slot_id=slot.id, clinician_id=e["clinician_id"], appointment_type=appt_type, state="DEMO_CONFIRMED", idempotency_key=f"seed-{e['id']}")
        db.add(slot)
        db.flush()  # the booked interval must exist before the appointment that references it
        db.add(appt)
        db.flush()
        db.add(Encounter(id=e["id"], student_id=e["student_id"], clinician_id=e["clinician_id"], appointment_id=appt.id, starts_at=start, visit_type=e["visit_type"], status=e["status"]))
    db.commit()

    for s in users["students"]:
        if s["calendar"]:
            student = db.get(User, s["id"])
            import_calendar(db, student, (data_dir / s["calendar"]).read_bytes(), filename=s["calendar"], source_mode="demo")

    audit.record(db, actor_role="system", actor_id=None, action="DEMO_RESET", detail="Fictional demo data loaded")
    db.commit()
