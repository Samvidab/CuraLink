"""UniTime .ics parsing: validation, timezone detection and recurrence expansion.

Pure functions: no database access, so they are easy to unit test.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import recurring_ical_events
from icalendar import Calendar

from app.errors import ApiError

MAX_ICS_BYTES = 2 * 1024 * 1024
DEFAULT_DURATION = timedelta(minutes=50)
_COURSE_RE = re.compile(r"^\s*([A-Z]{2,5})\s?(\d{3,5})\b(?:\s+(?:LEC|LAB|REC|SD|PSO|LBR)?\s*(\w+))?", re.I)


@dataclass
class Occurrence:
    uid: str
    summary: str
    start_at: datetime  # UTC
    end_at: datetime  # UTC
    tzid: str
    location: str | None
    recurrence_id: str | None
    all_day: bool
    course_code: str | None
    section: str | None


@dataclass
class ParsedCalendar:
    timezone: str
    occurrences: list[Occurrence]
    warnings: list[str] = field(default_factory=list)
    name: str | None = None


def parse_course_code(summary: str) -> tuple[str | None, str | None]:
    m = _COURSE_RE.match(summary or "")
    if not m:
        return None, None
    return f"{m.group(1).upper()} {m.group(2)}", m.group(3)


def _valid_zone(name: str | None) -> str | None:
    if not name:
        return None
    try:
        ZoneInfo(str(name))
        return str(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _detect_timezone(cal: Calendar, default_tz: str, warnings: list[str]) -> str:
    candidates = [cal.get("X-WR-TIMEZONE")]
    candidates += [tz.get("TZID") for tz in cal.walk("VTIMEZONE")]
    for ev in cal.walk("VEVENT"):
        dt = ev.get("DTSTART")
        if dt is not None and getattr(dt, "params", None):
            candidates.append(dt.params.get("TZID"))
    for c in candidates:
        if c and (zone := _valid_zone(c)):
            return zone
    if any(candidates):
        warnings.append(f"Calendar timezone '{next(c for c in candidates if c)}' was not recognized; using {default_tz}.")
    else:
        warnings.append(f"Calendar did not specify a timezone; using {default_tz}.")
    return default_tz


def _to_utc(value, zone: ZoneInfo) -> tuple[datetime, bool]:
    """Return (utc_instant, is_all_day). Floating times are read in the calendar zone."""
    if isinstance(value, datetime):
        local = value if value.tzinfo else value.replace(tzinfo=zone)
        return local.astimezone(UTC), False
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=zone).astimezone(UTC), True
    raise ValueError("unsupported date value")


def validate_upload(filename: str | None, content_type: str | None, data: bytes) -> None:
    if len(data) > MAX_ICS_BYTES:
        raise ApiError(422, "ICS_TOO_LARGE", "Calendar files must be 2 MB or smaller.")
    if filename and not filename.lower().endswith(".ics"):
        raise ApiError(422, "ICS_WRONG_TYPE", "Upload a .ics calendar file exported from UniTime.")
    if content_type and content_type not in ("text/calendar", "application/octet-stream", "application/ics", ""):
        raise ApiError(422, "ICS_WRONG_TYPE", "Upload a .ics calendar file exported from UniTime.")
    if not data.lstrip(b"\xef\xbb\xbf \r\n\t").upper().startswith(b"BEGIN:VCALENDAR"):
        raise ApiError(422, "ICS_INVALID", "This file doesn't look like an iCalendar (.ics) file.")


def parse_ics(data: bytes, window_start: date, window_end: date, default_tz: str) -> ParsedCalendar:
    try:
        cal = Calendar.from_ical(data)
    except Exception as exc:  # icalendar raises a variety of errors
        raise ApiError(422, "ICS_INVALID", "We couldn't read this calendar file. Try exporting it again or use the sample calendar.") from exc

    warnings: list[str] = []
    tz_name = _detect_timezone(cal, default_tz, warnings)
    zone = ZoneInfo(tz_name)
    if cal.get("X-WR-TIMEZONE") is not None and not _valid_zone(cal.get("X-WR-TIMEZONE")):
        # The recurrence library honours X-WR-TIMEZONE; replace an unknown zone
        # with the one we resolved so expansion stays predictable.
        cal["X-WR-TIMEZONE"] = tz_name

    # RECURRENCE-ID overrides (moved/edited single meetings) keyed by original start.
    overrides = {
        (str(ev.get("UID")), _to_utc(ev["RECURRENCE-ID"].dt, zone)[0])
        for ev in cal.walk("VEVENT")
        if ev.get("RECURRENCE-ID") is not None
    }

    # Duplicate UIDs among *master* events (not RECURRENCE-ID overrides) usually
    # mean the same class was exported twice.
    masters: dict[str, int] = {}
    for ev in cal.walk("VEVENT"):
        if ev.get("RECURRENCE-ID") is None and ev.get("UID"):
            masters[str(ev["UID"])] = masters.get(str(ev["UID"]), 0) + 1
    for uid, count in masters.items():
        if count > 1:
            warnings.append(f"Event {uid} appeared {count} times; duplicate copies were ignored.")

    start = datetime(window_start.year, window_start.month, window_start.day, tzinfo=zone)
    end = datetime(window_end.year, window_end.month, window_end.day, tzinfo=zone)
    try:
        expanded = recurring_ical_events.of(cal).between(start, end)
    except Exception as exc:
        raise ApiError(422, "ICS_RECURRENCE_ERROR", "We couldn't expand repeating events in this calendar.") from exc

    seen: set[tuple[str, datetime]] = set()
    occurrences: list[Occurrence] = []
    missing_summary = missing_end = 0
    for i, ev in enumerate(expanded):
        dtstart = ev.get("DTSTART")
        if dtstart is None:
            continue
        uid = str(ev.get("UID") or f"no-uid-{i}")
        start_utc, all_day = _to_utc(dtstart.dt, zone)
        end_utc = None
        if ev.get("DTEND") is not None:
            end_utc, _ = _to_utc(ev["DTEND"].dt, zone)
        elif ev.get("DURATION") is not None:
            end_utc = start_utc + ev["DURATION"].dt
        # The expansion library fills a missing DTEND with DTSTART (RFC 5545);
        # a zero-length class meeting is treated as "no end time given".
        if end_utc is None or end_utc <= start_utc:
            end_utc = start_utc + (timedelta(days=1) if all_day else DEFAULT_DURATION)
            if not all_day:
                missing_end += 1
        key = (uid, start_utc)
        if key in seen:
            continue
        seen.add(key)
        summary = str(ev.get("SUMMARY") or "").strip()
        if not summary:
            summary = "Untitled event"
            missing_summary += 1
        code, section = parse_course_code(summary)
        rid = ev.get("RECURRENCE-ID")
        original = _to_utc(rid.dt, zone)[0] if rid is not None else None
        occurrences.append(
            Occurrence(
                uid=uid,
                summary=summary,
                start_at=start_utc,
                end_at=end_utc,
                tzid=tz_name,
                location=str(ev.get("LOCATION")) if ev.get("LOCATION") else None,
                # Only set for single-meeting overrides: the meeting's original start.
                recurrence_id=original.isoformat() if original and (uid, original) in overrides else None,
                all_day=all_day,
                course_code=code,
                section=section,
            )
        )
    if missing_summary:
        warnings.append(f"{missing_summary} event(s) had no title; review them in your calendar.")
    if missing_end:
        warnings.append(f"{missing_end} event(s) had no end time; we assumed 50 minutes.")
    if not occurrences:
        warnings.append("No events fell inside the current term window.")
    occurrences.sort(key=lambda o: (o.start_at, o.uid))
    name = cal.get("X-WR-CALNAME")
    return ParsedCalendar(timezone=tz_name, occurrences=occurrences, warnings=warnings, name=str(name) if name else None)
