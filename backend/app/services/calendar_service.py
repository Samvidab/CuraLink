from datetime import date, timedelta
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Calendar, CalendarEvent, Course, User
from app.services import audit, instructor_directory
from app.services.ics_import import ParsedCalendar, parse_ics

_FALLBACK_COLORS = ["bg-sky-500", "bg-teal-500", "bg-violet-500", "bg-amber-500", "bg-rose-500", "bg-indigo-500"]


def term_window(today: date) -> tuple[date, date]:
    """Expand recurrences across the surrounding term only."""
    return today - timedelta(days=70), today + timedelta(days=70)


# CURALINK_CONFIG: CALENDAR_IMPORT
# Existing UniTime .ics import. Parsing/validation (size limit, accepted types, recurrence handling)
# lives in app/services/ics_import.py (MAX_ICS_BYTES, validate_upload, parse_ics); the HTTP endpoint is
# POST /api/v1/calendars/import in app/routers/student.py. Only iCalendar (.ics) is supported.
def import_calendar(db: Session, student: User, data: bytes, *, filename: str | None, source_mode: str) -> tuple[Calendar, ParsedCalendar]:
    settings = get_settings()
    # Expand over the file's own term (first meeting + ~one semester), so real exports for any term work.
    parsed = parse_ics(data, None, None, default_tz=student.timezone or settings.demo_timezone)

    # One active calendar per student in the MVP: replace the previous import.
    db.execute(delete(CalendarEvent).where(CalendarEvent.student_id == student.id))
    db.execute(delete(Calendar).where(Calendar.student_id == student.id))
    db.execute(delete(Course).where(Course.student_id == student.id, Course.provenance != "manual"))
    manual = {c.code: c for c in db.scalars(select(Course).where(Course.student_id == student.id))}

    cal = Calendar(selected_term=None,
        id=f"cal_{uuid4().hex[:10]}",
        student_id=student.id,
        source_mode=source_mode,
        filename=filename,
        timezone=parsed.timezone,
        events_imported=len(parsed.occurrences),
        warnings=parsed.warnings,
    )
    db.add(cal)

    # Courses are per (code, term): the same code in two semesters is two separate course records.
    courses: dict[tuple[str, str | None], Course] = {(c.code, c.term): c for c in manual.values()}
    for occ in parsed.occurrences:
        if not occ.course_code or (occ.course_code, occ.term) in courses:
            continue
        match = instructor_directory.resolve(occ.course_code, occ.section)
        # Instructor data from the student's own UniTime export wins over catalog/directory lookups.
        instr = next((i for o in parsed.occurrences if o.course_code == occ.course_code and o.term == occ.term for i in o.instructors), None)
        if instr:
            name, email = instr
            status, provenance = ("VERIFIED" if email else "NEEDS_REVIEW"), "unitime_ics"
            if not email and match.instructor_email and match.instructor_name == name:
                email, status, provenance = match.instructor_email, match.contact_status, match.provenance
        elif match.provenance != "none":
            name, email, status, provenance = match.instructor_name, match.instructor_email, match.contact_status, match.provenance
        else:
            name, email, status, provenance = None, None, "MISSING", "ics"
        title = occ.title or match.title or (occ.summary.split(" - ", 1)[1] if " - " in occ.summary else None)
        course = Course(
            id=f"crs_{uuid4().hex[:10]}",
            student_id=student.id,
            code=occ.course_code,
            section=occ.section,
            term=occ.term,
            title=title,
            instructor_name=name,
            instructor_email=email,
            contact_status=status,
            provenance=provenance,
            color=match.color or _FALLBACK_COLORS[len(courses) % len(_FALLBACK_COLORS)],
        )
        db.add(course)
        courses[(occ.course_code, occ.term)] = course
    db.flush()

    for occ in parsed.occurrences:
        db.add(
            CalendarEvent(
                id=f"ev_{uuid4().hex[:12]}",
                calendar_id=cal.id,
                student_id=student.id,
                uid=occ.uid,
                course_id=courses[(occ.course_code, occ.term)].id if occ.course_code else None,
                summary=occ.summary,
                start_at=occ.start_at,
                end_at=occ.end_at,
                tzid=occ.tzid,
                location=occ.location,
                recurrence_id=occ.recurrence_id,
                all_day=occ.all_day,
                kind="class" if occ.course_code else "other",
                source=source_mode,
                term=occ.term,
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
