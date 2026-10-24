"""Deterministic absence impact engine (TRD §8, §16).

Given a clinician-chosen inclusive local date range, list the student's class
meetings that actually occur in it. Pure function; no inference of medical
justification and no expansion beyond the chosen range.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Meeting:
    event_id: str
    course_id: str | None
    course_code: str
    start: datetime  # UTC
    end: datetime  # UTC


@dataclass
class CourseImpact:
    course_id: str | None
    course_code: str
    meetings: list[dict] = field(default_factory=list)  # {event_id, date, start_local, end_local, minutes}

    @property
    def dates(self) -> list[str]:
        return sorted({m["date"] for m in self.meetings})


@dataclass
class Impact:
    start_date: date
    end_date: date
    days: list[dict]  # {date, weekday, weekend, meeting_count}
    courses: list[CourseImpact]

    @property
    def total_meetings(self) -> int:
        return sum(len(c.meetings) for c in self.courses)


def impacted(meetings: list[Meeting], start_date: date, end_date: date, tz: str) -> Impact:
    if end_date < start_date:
        raise ValueError("end_date before start_date")
    if (end_date - start_date).days > 30:
        raise ValueError("range longer than 31 days")
    zone = ZoneInfo(tz)
    lo = datetime.combine(start_date, datetime.min.time(), zone)
    hi = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), zone)
    by_course: dict[str, CourseImpact] = {}
    per_day: dict[date, int] = {}
    for m in sorted(meetings, key=lambda m: (m.start, m.course_code, m.event_id)):
        # Overlap rule: max(startA, startB) < min(endA, endB), after tz normalisation.
        if not (max(m.start, lo) < min(m.end, hi)):
            continue
        s, e = m.start.astimezone(zone), m.end.astimezone(zone)
        ci = by_course.setdefault(m.course_code, CourseImpact(m.course_id, m.course_code))
        ci.meetings.append({
            "event_id": m.event_id, "date": s.date().isoformat(), "start_local": s.strftime("%-I:%M %p"), "end_local": e.strftime("%-I:%M %p"),
            "minutes": int((m.end - m.start).total_seconds() // 60),
        })
        per_day[s.date()] = per_day.get(s.date(), 0) + 1
    days = []
    d = start_date
    while d <= end_date:
        days.append({"date": d.isoformat(), "weekday": d.strftime("%A"), "weekend": d.weekday() >= 5, "meeting_count": per_day.get(d, 0)})
        d += timedelta(days=1)
    return Impact(start_date, end_date, days, sorted(by_course.values(), key=lambda c: c.course_code))
