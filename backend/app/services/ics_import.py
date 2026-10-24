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
# Purdue/UniTime class names look like "CS 18000 Lec 001", "MA 26100 REC 2", "PHYS 17200 Lab".
_COURSE_RE = re.compile(r"\b([A-Z]{2,5})\s?(\d{3,5}[A-Z]?)\b(?:[\s-]+(?i:(LEC|LAB|REC|SD|PSO|LBR|SEM|STU|IND|DIS|PRA|CLN|EX|LECTURE|LABORATORY|RECITATION))\b)?(?:[\s-]+(\d{1,4}[A-Z]?))?")
_MAILTO = re.compile(r"^mailto:", re.I)


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
    title: str | None = None
    instructors: list[tuple[str | None, str | None]] = field(default_factory=list)  # (name, email) from ORGANIZER/ATTENDEE
    status: str | None = None
    term: str | None = None  # e.g. "Fall 2026"; from the series' first meeting date (see term_for)


@dataclass
class ParsedCalendar:
    timezone: str
    occurrences: list[Occurrence]
    warnings: list[str] = field(default_factory=list)
    name: str | None = None


def parse_course_code(text: str, anywhere: bool = False) -> tuple[str | None, str | None]:
    """Subject codes are uppercase (CS, MA, PHYS); SUMMARY must start with one, DESCRIPTION may contain one."""
    m = _COURSE_RE.search(text or "") if anywhere else _COURSE_RE.match((text or "").lstrip())
    if not m:
        return None, None
    return f"{m.group(1)} {m.group(2)}", m.group(4)


def _instructors(ev) -> list[tuple[str | None, str | None]]:
    """UniTime lists instructors as ORGANIZER and/or ATTENDEE (CN=name, mailto:email)."""
    out: list[tuple[str | None, str | None]] = []
    for prop in ("ORGANIZER", "ATTENDEE"):
        vals = ev.get(prop)
        if vals is None:
            continue
        for v in vals if isinstance(vals, list) else [vals]:
            name = str(v.params.get("CN")).strip('"') if getattr(v, "params", None) and v.params.get("CN") else None
            email = _MAILTO.sub("", str(v)).strip() or None
            if email and "@" not in email:
                email = None
            if (name or email) and (name, email) not in out:
                out.append((name, email))
    return out


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


# CURALINK_CONFIG: ACADEMIC_TERM
# Term boundaries used to LABEL a class series by its first meeting date (UniTime exports carry no term field).
# Purdue convention: Spring = Jan 1-May 15, Summer = May 16-Aug 14, Fall = Aug 15-Dec 31. Never inferred from course codes.
TERM_BOUNDARIES = (((1, 1), "Spring"), ((5, 16), "Summer"), ((8, 15), "Fall"))
MAX_SERIES_DAYS = 140  # a repeating class with no end date is limited to one term, never "every week forever"


def term_for(d: date) -> str:
    season = "Spring"
    for (m, day), name in TERM_BOUNDARIES:
        if (d.month, d.day) >= (m, day):
            season = name
    return f"{season} {d.year}"


def _local_date(v, zone: ZoneInfo) -> date:
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=zone)).astimezone(zone).date()
    return v


def series_spans(cal: Calendar, zone: ZoneInfo) -> dict[str, tuple[date, date, bool]]:
    """UID -> (first meeting, last possible meeting, open_ended) from each master VEVENT's DTSTART/RRULE."""
    spans: dict[str, tuple[date, date, bool]] = {}
    for ev in cal.walk("VEVENT"):
        dt = ev.get("DTSTART")
        if dt is None or ev.get("RECURRENCE-ID") is not None:
            continue
        uid = str(ev.get("UID") or "")
        first = _local_date(dt.dt, zone)
        rrule = ev.get("RRULE")
        open_ended = False
        if rrule:
            until = rrule.get("UNTIL")
            if until:
                last = _local_date(until[0], zone)
            elif rrule.get("COUNT"):
                last = first + timedelta(days=7 * int(rrule["COUNT"][0]) + 7)
            else:
                last, open_ended = first + timedelta(days=MAX_SERIES_DAYS), True
        else:
            last = first
        prev = spans.get(uid)
        spans[uid] = (min(first, prev[0]), max(last, prev[1]), open_ended or prev[2]) if prev else (first, last, open_ended)
    return spans


def parse_ics(data: bytes, window_start: date | None, window_end: date | None, default_tz: str) -> ParsedCalendar:
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

    try:
        spans = series_spans(cal, zone)
    except Exception as exc:  # broken DTSTART/RRULE values
        raise ApiError(422, "ICS_INVALID", "We couldn't read the dates in this calendar file. Try exporting it again or use the sample calendar.") from exc
    if window_start is None or window_end is None:
        # Expand EVERY series over its own dates (all terms in the file), capped at ~2 years.
        if spans:
            window_start = min(v[0] for v in spans.values())
            window_end = min(max(v[1] for v in spans.values()), window_start + timedelta(days=730)) + timedelta(days=1)
        else:
            window_start, window_end = date.today(), date.today() + timedelta(days=150)
    open_ended = [uid for uid, v in spans.items() if v[2]]
    if open_ended:
        warnings.append(f"{len(open_ended)} repeating event(s) had no end date; limited to {MAX_SERIES_DAYS} days from their first meeting.")
    start = datetime(window_start.year, window_start.month, window_start.day, tzinfo=zone)
    end = datetime(window_end.year, window_end.month, window_end.day, tzinfo=zone)
    try:
        expanded = recurring_ical_events.of(cal).between(start, end)
    except Exception as exc:
        raise ApiError(422, "ICS_RECURRENCE_ERROR", "We couldn't expand repeating events in this calendar.") from exc

    seen: set[tuple[str, datetime]] = set()
    occurrences: list[Occurrence] = []
    missing_summary = missing_end = cancelled = 0
    for i, ev in enumerate(expanded):
        dtstart = ev.get("DTSTART")
        if dtstart is None:
            continue
        status = str(ev.get("STATUS") or "").upper() or None
        if status == "CANCELLED":
            cancelled += 1
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
        span = spans.get(uid)
        if span and span[2] and start_utc.astimezone(zone).date() > span[1]:
            continue  # open-ended repeat beyond one term
        seen.add(key)
        summary = str(ev.get("SUMMARY") or "").strip()
        if not summary:
            summary = "Untitled event"
            missing_summary += 1
        description = str(ev.get("DESCRIPTION") or "").strip()
        code, section = parse_course_code(summary)
        title = None
        if code is None and description:
            # UniTime can show the course title as SUMMARY and put "Lec 001"/external id in DESCRIPTION.
            code, section = parse_course_code(description, anywhere=True)
            title = summary if code else None
        elif code and " - " in summary:
            title = summary.split(" - ", 1)[1].strip() or None
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
                title=title,
                instructors=_instructors(ev),
                status=status,
                term=term_for(span[0] if span else start_utc.astimezone(zone).date()),
            )
        )
    if missing_summary:
        warnings.append(f"{missing_summary} event(s) had no title; review them in your calendar.")
    if cancelled:
        warnings.append(f"{cancelled} cancelled meeting(s) in the file were skipped.")
    if missing_end:
        warnings.append(f"{missing_end} event(s) had no end time; we assumed 50 minutes.")
    if not occurrences:
        warnings.append("No events fell inside the current term window.")
    occurrences.sort(key=lambda o: (o.start_at, o.uid))
    name = cal.get("X-WR-CALNAME")
    return ParsedCalendar(timezone=tz_name, occurrences=occurrences, warnings=warnings, name=str(name) if name else None)
