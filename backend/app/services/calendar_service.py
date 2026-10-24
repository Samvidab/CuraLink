from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Calendar, CalendarEvent, Course, User
from app.services import audit, catalog
from app.services.ics_import import ParsedCalendar, parse_ics

_FALLBACK_COLORS = ["bg-sky-500", "bg-teal-500", "bg-violet-500", "bg-amber-500", "bg-rose-500", "bg-indigo-500"]


def term_window(today: date) -> tuple[date, date]:
    """Expand recurrences across the surrounding term only."""
    return today - timedelta(days=70), today + timedelta(days=70)


def import_calendar(db: Session, student: User, data: bytes, *, filename: str | None, source_mode: str) -> tuple[Calendar, ParsedCalendar]:
    settings = get_settings()
    # Expand over the file's own term (first meeting + ~one semester), so real exports for any term work.
    parsed = parse_ics(data, None, None, default_tz=student.timezone or settings.demo_timezone)

    # One active calendar per student in the MVP: replace the previous import.
    db.execute(delete(CalendarEvent).where(CalendarEvent.student_id == student.id))
    db.execute(delete(Calendar).where(Calendar.student_id == student.id))
    db.execute(delete(Course).where(Course.student_id == student.id, Course.provenance != "manual"))
    manual = {c.code: c for c in db.scalars(select(Course).where(Course.student_id == student.id))}

    cal = Calendar(
        id=f"cal_{uuid4().hex[:10]}",
        student_id=student.id,
        source_mode=source_mode,
        filename=filename,
        timezone=parsed.timezone,
        events_imported=len(parsed.occurrences),
        warnings=parsed.warnings,
    )
    db.add(cal)

    courses: dict[str, Course] = dict(manual)
    for occ in parsed.occurrences:
        if not occ.course_code or occ.course_code in courses:
            continue
        entry = catalog.lookup(occ.course_code)
        # Instructor data from the student's own UniTime export wins over the demo catalog.
        instr = next((i for o in parsed.occurrences if o.course_code == occ.course_code for i in o.instructors), None)
        if instr:
            name, email = instr
            status, provenance = ("VERIFIED" if email else "NEEDS_REVIEW"), "unitime_ics"
        elif entry:
            name, email, status, provenance = entry.get("instructor_name"), entry.get("instructor_email"), entry.get("contact_status", "MISSING"), "demo_catalog"
        else:
            name, email, status, provenance = None, None, "MISSING", "ics"
        title = occ.title or (entry or {}).get("title") or (occ.summary.split(" - ", 1)[1] if " - " in occ.summary else None)
        course = Course(
            id=f"crs_{uuid4().hex[:10]}",
            student_id=student.id,
            code=occ.course_code,
            section=occ.section,
            title=title,
            instructor_name=name,
            instructor_email=email,
            contact_status=status,
            provenance=provenance,
            color=(entry or {}).get("color") or _FALLBACK_COLORS[len(courses) % len(_FALLBACK_COLORS)],
        )
        db.add(course)
        courses[occ.course_code] = course
    db.flush()

    for occ in parsed.occurrences:
        db.add(
            CalendarEvent(
                id=f"ev_{uuid4().hex[:12]}",
                calendar_id=cal.id,
                student_id=student.id,
                uid=occ.uid,
                course_id=courses[occ.course_code].id if occ.course_code else None,
                summary=occ.summary,
                start_at=occ.start_at,
                end_at=occ.end_at,
                tzid=occ.tzid,
                location=occ.location,
                recurrence_id=occ.recurrence_id,
                all_day=occ.all_day,
                kind="class" if occ.course_code else "other",
                source=source_mode,
            )
        )
    audit.record(
        db,
        actor_role="student",
        actor_id=student.id,
        subject_student_id=student.id,
        action="CALENDAR_IMPORTED",
        object_type="calendar",
        object_id=cal.id,
        detail=f"{len(parsed.occurrences)} occurrences, {len(courses)} courses",
        source_mode=source_mode,
    )
    db.commit()
    return cal, parsed
