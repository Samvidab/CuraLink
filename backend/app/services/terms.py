"""Semester selection. Terms come from the imported events (see ics_import.term_for); nothing is invented.

The selected term filters every student-facing view: calendar, course list, scheduling conflicts and
absence class matching. Other terms stay stored and are never deleted.
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Calendar, CalendarEvent, Course, User


def today() -> date:
    s = get_settings()
    return s.demo_today if s.demo_mode else date.today()


def available(db: Session, student_id: str) -> list[dict]:
    rows = db.execute(
        select(CalendarEvent.term, func.min(CalendarEvent.start_at), func.max(CalendarEvent.end_at), func.count(CalendarEvent.id))
        .where(CalendarEvent.student_id == student_id, CalendarEvent.kind == "class", CalendarEvent.term.is_not(None))
        .group_by(CalendarEvent.term)
    ).all()
    courses = dict(db.execute(select(Course.term, func.count(Course.id)).where(Course.student_id == student_id).group_by(Course.term)).all())
    out = [{"term": t, "first_meeting": lo.date().isoformat(), "last_meeting": hi.date().isoformat(), "meetings": n, "courses": courses.get(t, 0), "source": "inferred from meeting dates"} for t, lo, hi, n in rows]
    return sorted(out, key=lambda r: r["first_meeting"])


def default_term(terms: list[dict]) -> str | None:
    """The term containing today; else the next upcoming; else the most recent."""
    if not terms:
        return None
    t = today().isoformat()
    for r in terms:
        if r["first_meeting"] <= t <= r["last_meeting"]:
            return r["term"]
    upcoming = [r for r in terms if r["first_meeting"] > t]
    return (upcoming[0] if upcoming else terms[-1])["term"]


def selected(db: Session, student: User) -> str | None:
    cal = db.scalar(select(Calendar).where(Calendar.student_id == student.id))
    terms = available(db, student.id)
    names = {r["term"] for r in terms}
    if cal and cal.selected_term in names:
        return cal.selected_term
    return default_term(terms)


def term_filter(term: str | None):
    """SQL filter for events in the selected term (personal blocks/untermed events always count)."""
    return (CalendarEvent.term == term) | CalendarEvent.term.is_(None) if term else True
