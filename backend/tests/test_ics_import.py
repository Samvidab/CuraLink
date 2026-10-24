from datetime import date
from zoneinfo import ZoneInfo

import pytest

from app.config import get_settings
from app.errors import ApiError
from app.services.ics_import import parse_course_code, parse_ics, validate_upload

TZ = "America/Indiana/Indianapolis"
SAMPLE = (get_settings().sample_data_dir / "sample.ics").read_bytes()


def _local(occ):
    return occ.start_at.astimezone(ZoneInfo(TZ))


def _parse(data=SAMPLE, start=date(2026, 10, 26), end=date(2026, 11, 7)):
    return parse_ics(data, start, end, TZ)


def test_recurring_course_expands_mwf_with_local_hours_across_dst():
    """AT-01, plus the Nov 1 DST change must not shift local class times."""
    parsed = _parse()
    assert parsed.timezone == TZ
    cs = [o for o in parsed.occurrences if o.course_code == "CS 240"]
    days = [_local(o).date() for o in cs]
    # Mon 26, Wed 28, (Fri 30 cancelled), Mon 2, Wed 4, Fri 6
    assert days == [date(2026, 10, 26), date(2026, 10, 28), date(2026, 11, 2), date(2026, 11, 4), date(2026, 11, 6)]
    assert {(_local(o).hour, _local(o).minute) for o in cs} == {(9, 30)}
    # UTC offset differs before/after DST even though local time is constant.
    assert cs[0].start_at.hour == 13 and cs[2].start_at.hour == 14


def test_exdate_is_excluded():
    """AT-02 (EXDATE)."""
    parsed = _parse(start=date(2026, 10, 30), end=date(2026, 10, 31))
    assert not [o for o in parsed.occurrences if o.course_code == "CS 240"]
    assert [o for o in parsed.occurrences if o.course_code == "STAT 350"]


def test_recurrence_id_override_moves_single_occurrence():
    parsed = _parse(start=date(2026, 10, 28), end=date(2026, 10, 29))
    stat = [o for o in parsed.occurrences if o.course_code == "STAT 350"]
    assert len(stat) == 1
    assert (_local(stat[0]).hour, _local(stat[0]).minute) == (14, 30)
    assert stat[0].location == "Demo Science Center 210"


def test_duplicate_uid_is_not_repeated():
    """AT-02 (duplicate UID)."""
    dup = SAMPLE.replace(b"END:VCALENDAR", b"""BEGIN:VEVENT
UID:demo-phil208-lec001@curalink.example.com
SUMMARY:PHIL 208 LEC 001 - Ethics of Data
DTSTART;TZID=America/Indiana/Indianapolis:20260824T133000
DTEND;TZID=America/Indiana/Indianapolis:20260824T142000
RRULE:FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20261211T235959Z
END:VEVENT
END:VCALENDAR""")
    parsed = _parse(dup, date(2026, 10, 26), date(2026, 10, 27))
    phil = [o for o in parsed.occurrences if o.course_code == "PHIL 208"]
    assert len(phil) == 1
    assert any("duplicate" in w for w in parsed.warnings)


def test_invalid_tzid_falls_back_predictably():
    """AT-02 (invalid TZID)."""
    data = b"""BEGIN:VCALENDAR
VERSION:2.0
X-WR-TIMEZONE:Mars/Olympus_Mons
BEGIN:VEVENT
UID:x1
SUMMARY:MA 261 LEC 004
DTSTART:20261026T100000
DTEND:20261026T105000
END:VEVENT
END:VCALENDAR"""
    parsed = _parse(data)
    assert parsed.timezone == TZ
    assert any("not recognized" in w for w in parsed.warnings)
    assert (_local(parsed.occurrences[0]).hour, parsed.occurrences[0].course_code) == (10, "MA 261")


def test_missing_end_and_all_day_events():
    data = b"""BEGIN:VCALENDAR
VERSION:2.0
X-WR-TIMEZONE:America/Indiana/Indianapolis
BEGIN:VEVENT
UID:a
SUMMARY:Reading day
DTSTART;VALUE=DATE:20261027
END:VEVENT
BEGIN:VEVENT
UID:b
DTSTART;TZID=America/Indiana/Indianapolis:20261027T120000
END:VEVENT
END:VCALENDAR"""
    parsed = _parse(data)
    by_uid = {o.uid: o for o in parsed.occurrences}
    assert by_uid["a"].all_day
    assert (by_uid["b"].end_at - by_uid["b"].start_at).seconds == 50 * 60
    assert by_uid["b"].summary == "Untitled event"
    assert len(parsed.warnings) == 2


@pytest.mark.parametrize(
    "name,ctype,data,code",
    [
        ("notes.pdf", "application/pdf", b"%PDF", "ICS_WRONG_TYPE"),
        ("cal.ics", "text/calendar", b"hello", "ICS_INVALID"),
        ("cal.ics", "text/calendar", b"BEGIN:VCALENDAR" + b"x" * (2 * 1024 * 1024), "ICS_TOO_LARGE"),
    ],
)
def test_upload_validation(name, ctype, data, code):
    with pytest.raises(ApiError) as exc:
        validate_upload(name, ctype, data)
    assert exc.value.code == code


def test_malformed_calendar_is_recoverable_error():
    with pytest.raises(ApiError) as exc:
        parse_ics(b"BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:notadate\nEND:VEVENT\nEND:VCALENDAR", date(2026, 10, 1), date(2026, 11, 1), TZ)
    assert exc.value.status == 422 and exc.value.recoverable


def test_course_code_parsing():
    assert parse_course_code("CS 240 LEC 001 - Programming in C") == ("CS 240", "001")
    assert parse_course_code("MA26100 REC 2") == ("MA 26100", "2")
    assert parse_course_code("Dentist") == (None, None)
