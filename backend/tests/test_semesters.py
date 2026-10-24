"""Semester filtering + calendar placement for a multi-term UniTime export (Spring 2026 + Fall 2026).

Regression for: imported schedule showed previous-semester classes and nothing in the current week,
because expansion started at the file's EARLIEST event (+150 days) and courses were keyed by code only.
"""

import pytest

from app.config import get_settings
from app.services.ics_import import parse_ics, term_for

MULTI = (get_settings().sample_data_dir / "unitime_multiterm_sample.ics").read_bytes()
TZ = "America/Indiana/Indianapolis"


@pytest.fixture()
def multi(student):
    r = student.post("/api/v1/calendars/import", files={"file": ("unitime.ics", MULTI, "text/calendar")})
    assert r.status_code == 200, r.text
    return student


def _week(client, start, end, **params):
    return client.get("/api/v1/calendar/events", params={"start": start, "end": end, **params}).json()


def test_term_labels_come_from_dates_not_course_codes():
    assert [term_for(d) for d in map(__import__("datetime").date.fromisoformat, ["2026-01-12", "2026-05-20", "2026-08-24", "2026-12-31"])] == ["Spring 2026", "Summer 2026", "Fall 2026", "Fall 2026"]
    p = parse_ics(MULTI, None, None, TZ)
    assert {(o.course_code, o.term) for o in p.occurrences} == {
        ("MA 16500", "Spring 2026"), ("ENGL 10600", "Spring 2026"), ("CS 18000", "Fall 2026"), ("MA 26100", "Fall 2026"), ("COM 11400", "Fall 2026")}


def test_current_semester_is_default_and_spring_does_not_leak(multi):
    t = multi.get("/api/v1/calendar/terms").json()
    assert [x["term"] for x in t["terms"]] == ["Spring 2026", "Fall 2026"] and t["selected"] == "Fall 2026"
    d = multi.get("/api/v1/students/me/dashboard").json()
    assert d["term"] == "Fall 2026" and sorted(c["code"] for c in d["courses"]) == ["COM 11400", "CS 18000", "MA 26100"]
    week = _week(multi, "2026-10-26", "2026-11-02")
    assert week["term"] == "Fall 2026" and {e["course_code"] for e in week["events"]} == {"CS 18000", "MA 26100", "COM 11400"}
    # Historical classes are still stored and reviewable.
    review = multi.get("/api/v1/calendar/review").json()
    assert {(c["code"], c["term"]) for c in review["courses"]} >= {("MA 16500", "Spring 2026"), ("ENGL 10600", "Spring 2026")}


def test_events_land_on_correct_weekday_and_local_time(multi):
    ev = _week(multi, "2026-10-26", "2026-11-02")["events"]
    got = sorted((e["start_at"], e["end_at"], e["course_code"]) for e in ev)
    assert got == [
        ("2026-10-26T15:00:00-04:00", "2026-10-26T16:15:00-04:00", "COM 11400"),  # Mon
        ("2026-10-27T13:00:00-04:00", "2026-10-27T14:15:00-04:00", "CS 18000"),   # Tue, moved (RECURRENCE-ID)
        ("2026-10-28T08:30:00-04:00", "2026-10-28T09:20:00-04:00", "MA 26100"),   # Wed
        ("2026-10-28T15:00:00-04:00", "2026-10-28T16:15:00-04:00", "COM 11400"),  # Wed
        ("2026-10-29T10:30:00-04:00", "2026-10-29T11:45:00-04:00", "CS 18000"),   # Thu
    ]
    assert not [e for e in ev if e["start_at"].startswith("2026-10-28T14:30")]  # cancelled PHYS lab
    moved = [e for e in ev if e["rescheduled"]]
    assert len(moved) == 1 and moved[0]["location"] == "Fictional Hall 200"


def test_dst_change_keeps_local_class_time(multi):
    after = _week(multi, "2026-11-02", "2026-11-09")["events"]  # US DST ends Nov 1
    cs = [e for e in after if e["course_code"] == "CS 18000"]
    assert [e["start_at"] for e in cs] == ["2026-11-03T10:30:00-05:00", "2026-11-05T10:30:00-05:00"]


def test_series_respect_their_own_start_and_end_dates(multi):
    early = _week(multi, "2026-10-12", "2026-10-19")["events"]
    assert "COM 11400" not in {e["course_code"] for e in early}  # second-8-week course starts Oct 19
    finals = _week(multi, "2026-12-14", "2026-12-21")["events"]
    assert finals == []  # every Fall series has ended (UNTIL)
    thanksgiving = _week(multi, "2026-11-23", "2026-11-30")["events"]
    assert not [e for e in thanksgiving if e["course_code"] == "CS 18000" and e["start_at"].startswith("2026-11-26")]  # EXDATE


def test_selecting_a_term_updates_every_dependent_view(multi, clinician):
    assert multi.put("/api/v1/calendar/selected-term", json={"term": "Summer 2031"}).status_code == 422
    assert multi.put("/api/v1/calendar/selected-term", json={"term": "Spring 2026"}).json()["selected"] == "Spring 2026"
    d = multi.get("/api/v1/students/me/dashboard").json()
    assert sorted(c["code"] for c in d["courses"]) == ["ENGL 10600", "MA 16500"]
    spring_week = _week(multi, "2026-02-02", "2026-02-09")["events"]
    assert {e["course_code"] for e in spring_week} == {"MA 16500", "ENGL 10600"}
    assert _week(multi, "2026-10-26", "2026-11-02")["events"] == []  # Fall hidden while Spring is selected
    # Absence matching follows the selected term.
    multi.post("/api/v1/appointments/confirm", json={"slot_id": "slot_04", "student_approved": True, "idempotency_key": "term-key-0001"})
    imp = multi.post("/api/v1/absence-cases/preview", json={"start_date": "2026-10-27", "end_date": "2026-10-29"}).json()
    assert imp["courses"] == []
    multi.put("/api/v1/calendar/selected-term", json={"term": "Fall 2026"})
    imp = multi.post("/api/v1/absence-cases/preview", json={"start_date": "2026-10-27", "end_date": "2026-10-29"}).json()
    assert {c["course_code"] for c in imp["courses"]} == {"CS 18000", "MA 26100", "COM 11400"}


def test_scheduling_conflicts_use_the_selected_term(multi):
    # Wed Oct 28 14:45-15:15 slot overlaps Fall's COM 11400 (Wed 15:00) only when Fall is selected.
    recs = multi.post("/api/v1/schedule/recommendations", json={"appointment_type": "general_consultation"}).json()
    assert {r["slot"]["id"]: r["reason_code"] for r in recs["rejected"]}.get("slot_12") == "CLASS_CONFLICT"
    multi.put("/api/v1/calendar/selected-term", json={"term": "Spring 2026"})
    recs = multi.post("/api/v1/schedule/recommendations", json={"appointment_type": "general_consultation"}).json()
    assert "slot_12" in [o["slot"]["id"] for o in recs["options"]]


def test_open_ended_repeat_is_limited_to_one_term():
    data = MULTI.replace(b"RRULE:FREQ=WEEKLY;UNTIL=20261209T235900Z;BYDAY=WE;WKST=MO", b"RRULE:FREQ=WEEKLY;BYDAY=WE")
    p = parse_ics(data, None, None, TZ)
    ma = [o for o in p.occurrences if o.course_code == "MA 26100"]
    assert ma and max(o.start_at for o in ma).date().isoformat() <= "2027-01-13"
    assert any("no end date" in w for w in p.warnings)
