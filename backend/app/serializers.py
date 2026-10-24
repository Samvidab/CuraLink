"""ORM -> wire conversions. Datetimes are rendered in the display timezone with offset."""

from datetime import datetime

from app.models import AuditEvent, Calendar, CalendarEvent, Course
from app.schemas import ActivityOut, CalendarEventOut, CalendarSummary, CourseOut
from app.timeutil import as_utc, to_local


def course(c: Course) -> CourseOut:
    return CourseOut(
        id=c.id, code=c.code, section=c.section, title=c.title, instructor_name=c.instructor_name,
        instructor_email=c.instructor_email, contact_status=c.contact_status, provenance=c.provenance, color=c.color,
    )


def event(e: CalendarEvent, tz: str, course_codes: dict[str, str]) -> CalendarEventOut:
    return CalendarEventOut(
        id=e.id,
        course_id=e.course_id,
        course_code=course_codes.get(e.course_id) if e.course_id else None,
        title=e.summary,
        start_at=to_local(e.start_at, tz),
        end_at=to_local(e.end_at, tz),
        location=e.location,
        all_day=e.all_day,
        kind=e.kind,
        rescheduled=bool(e.recurrence_id) and datetime.fromisoformat(e.recurrence_id) != as_utc(e.start_at),
        source=e.source,
    )


def calendar(c: Calendar) -> CalendarSummary:
    return CalendarSummary(
        calendar_id=c.id, source_mode=c.source_mode, filename=c.filename, timezone=c.timezone,
        imported_at=as_utc(c.imported_at), events_imported=c.events_imported, warnings=list(c.warnings or []),
    )


def activity(a: AuditEvent) -> ActivityOut:
    return ActivityOut(
        id=a.id, event_type=a.action, actor=a.actor_role, object_type=a.object_type, object_id=a.object_id,
        from_state=a.from_state, to_state=a.to_state, status=a.status, detail=a.detail, source_mode=a.source_mode,
        at=as_utc(a.at),
    )
