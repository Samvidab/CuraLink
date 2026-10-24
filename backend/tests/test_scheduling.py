from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.scheduling import Interval, Preferences, Slot, find_conflicts, overlap_minutes, rank_slots

TZ = ZoneInfo("America/Indiana/Indianapolis")
NOW = datetime(2026, 10, 26, 8, 0, tzinfo=TZ).astimezone(UTC)


def t(h, m=0, day=26):
    return datetime(2026, 10, day, h, m, tzinfo=TZ).astimezone(UTC)


def slot(id, start, end, travel=8, type_="routine_checkup", available=True):
    return Slot(id, start, end, type_, travel, available)


# ---- pure engine -------------------------------------------------------------

def test_overlap_rule_is_strict():
    assert overlap_minutes(t(9), t(10), t(10), t(11)) == 0  # touching is not overlapping
    assert overlap_minutes(t(9), t(10, 30), t(10), t(11)) == 30


def test_class_overlap_excludes_slot_and_later_free_slot_ranks():
    """AT-03: class 13:30–14:20 excludes a 14:00 slot; a later free slot ranks."""
    busy = [Interval(t(13, 30), t(14, 20), "PHIL 208", "ev1")]
    ranked, rejected = rank_slots([slot("s14", t(14), t(14, 30)), slot("s16", t(16), t(16, 30))], busy, Preferences(), NOW, TZ)
    assert [r.slot.id for r in ranked] == ["s16"]
    assert rejected[0].slot.id == "s14" and rejected[0].reason_code == "CLASS_CONFLICT"
    assert rejected[0].conflicts[0].overlap_minutes == 20


def test_travel_buffer_creates_conflict_without_literal_overlap():
    """AT-04."""
    busy = [Interval(t(9, 30), t(10, 20), "CS 240", "ev1")]
    s = slot("s", t(10, 25), t(10, 55), travel=25)
    assert find_conflicts(s, busy)[0].kind == "TRAVEL_BUFFER"
    ranked, rejected = rank_slots([s], busy, Preferences(), NOW, TZ)
    assert not ranked and rejected[0].reason_code == "TRAVEL_BUFFER_CONFLICT"


def test_ranking_is_deterministic_with_tiebreaks():
    a = slot("b", t(12), t(12, 30))
    b = slot("a", t(12), t(12, 30))
    r1, _ = rank_slots([a, b], [], Preferences(), NOW, TZ)
    r2, _ = rank_slots([b, a], [], Preferences(), NOW, TZ)
    assert [r.slot.id for r in r1] == [r.slot.id for r in r2] == ["a", "b"]


def test_unavailable_past_and_travel_limits_are_hard_constraints():
    slots = [slot("gone", t(12), t(12, 30), available=False), slot("past", t(7), t(7, 30)), slot("far", t(15), t(15, 30), travel=45)]
    ranked, rejected = rank_slots(slots, [], Preferences(max_travel_minutes=30), NOW, TZ)
    assert not ranked
    assert {r.slot.id: r.reason_code for r in rejected} == {"gone": "SLOT_UNAVAILABLE", "past": "IN_THE_PAST", "far": "TRAVEL_TOO_LONG"}


def test_explicitly_allowed_conflicts_are_shown_and_sink():
    busy = [Interval(t(13, 30), t(14, 20), "PHIL 208", "ev1")]
    ranked, _ = rank_slots([slot("c", t(14), t(14, 30)), slot("ok", t(17), t(17, 30))], busy, Preferences(allow_conflicts=True), NOW, TZ)
    assert [r.slot.id for r in ranked] == ["ok", "c"]
    assert ranked[1].conflicts and "HAS_CONFLICT_ALLOWED_BY_STUDENT" in ranked[1].reason_codes


def test_preferred_hours_are_soft():
    ranked, _ = rank_slots([slot("early", t(9), t(9, 30)), slot("noon", t(12), t(12, 30))], [], Preferences(earliest_hour=11), NOW, TZ)
    assert ranked[0].slot.id == "noon"
    assert "OUTSIDE_PREFERRED_HOURS" in ranked[1].reason_codes


# ---- API ---------------------------------------------------------------------

def _recs(client, type_="routine_checkup", **prefs):
    return client.post("/api/v1/schedule/recommendations", json={"appointment_type": type_, "preferences": prefs}).json()


def test_recommendations_use_imported_calendar(student):
    student.post("/api/v1/calendars/import-sample")
    body = _recs(student)
    assert body["calendar_considered"] is True and body["source_mode"] == "demo"
    ids = [o["slot"]["id"] for o in body["options"]]
    assert ids[:3] == ["slot_02", "slot_04", "slot_07"]
    # Every option is from the seeded inventory and labelled demo (AT-13, G4).
    assert all(o["source_mode"] == "demo" and o["slot"]["source_mode"] == "demo" for o in body["options"])
    rejected = {r["slot"]["id"]: r["reason_code"] for r in body["rejected"]}
    assert rejected["slot_01"] == "TRAVEL_BUFFER_CONFLICT"  # 9:00–9:30 vs CS 240 at 9:30 + 8 min travel
    assert rejected["slot_13"] == "TRAVEL_BUFFER_CONFLICT"  # AT-04 on real data
    assert "slot_18" in ids  # Fri 9:30 free because CS 240 is cancelled (EXDATE)


def test_recurrence_override_is_respected(student):
    student.post("/api/v1/calendars/import-sample")
    rejected = {r["slot"]["id"]: r for r in _recs(student, "general_consultation")["rejected"]}
    # STAT 350 moved to 14:30–15:20 on Wed, so the 14:45 slot conflicts with it.
    assert rejected["slot_12"]["reason_code"] == "CLASS_CONFLICT"
    assert rejected["slot_12"]["conflicts"][0]["label"] == "STAT 350"


def test_confirm_is_explicit_idempotent_and_demo_only(student, clinician):
    student.post("/api/v1/calendars/import-sample")
    assert student.post("/api/v1/appointments/confirm", json={"slot_id": "slot_04", "student_approved": False, "idempotency_key": "key-0000001"}).status_code == 400
    body = {"slot_id": "slot_04", "student_approved": True, "idempotency_key": "key-0000002"}
    r1 = student.post("/api/v1/appointments/confirm", json=body).json()
    r2 = student.post("/api/v1/appointments/confirm", json=body).json()
    assert r1["status"] == "DEMO_CONFIRMED" and r1["external_booking"] is False
    assert r1["appointment_id"] == r2["appointment_id"]
    assert len(student.get("/api/v1/appointments/me").json()) == 1
    # Booked slot drops out of recommendations; dashboard shows it.
    assert "slot_04" not in [o["slot"]["id"] for o in _recs(student)["options"]]
    assert student.get("/api/v1/students/me/dashboard").json()["next_appointment"]["id"] == r1["appointment_id"]
    # The assigned clinician (slot_04 -> demo-clinician-1) now sees the encounter.
    assert "Sam Lee" in [e["student_name"] for e in clinician.get("/api/v1/clinician/encounters").json()]


def test_stale_slot_returns_409_and_replans(student):
    """AT-05."""
    student.post("/api/v1/calendars/import-sample")
    assert student.post("/api/v1/demo/slots/slot_02/invalidate").json()["status"] == "UNAVAILABLE"
    r = student.post("/api/v1/appointments/confirm", json={"slot_id": "slot_02", "student_approved": True, "idempotency_key": "key-stale-01"})
    assert r.status_code == 409 and r.json()["code"] == "SLOT_UNAVAILABLE" and r.json()["recoverable"]
    body = _recs(student)
    assert body["options"][0]["slot"]["id"] == "slot_04"
    assert {"slot_02": "SLOT_UNAVAILABLE"}.items() <= {r["slot"]["id"]: r["reason_code"] for r in body["rejected"]}.items()


def test_confirm_rechecks_class_conflicts(student):
    student.post("/api/v1/calendars/import-sample")
    r = student.post("/api/v1/appointments/confirm", json={"slot_id": "slot_03", "student_approved": True, "idempotency_key": "key-conflict"})
    assert r.status_code == 409 and r.json()["code"] == "CLASS_CONFLICT"


def test_personal_block_is_respected(student):
    student.post("/api/v1/calendars/import-sample")
    blk = student.post("/api/v1/calendar/blocks", json={"start_at": "2026-10-26T14:00:00-04:00", "end_at": "2026-10-26T15:00:00-04:00", "label": "Lab shift"}).json()
    rejected = {r["slot"]["id"]: r["reason_code"] for r in _recs(student)["rejected"]}
    assert rejected["slot_04"] == "PERSONAL_BLOCK_CONFLICT"
    assert student.delete(f"/api/v1/calendar/blocks/{blk['id']}").status_code == 204
    assert "slot_04" in [o["slot"]["id"] for o in _recs(student)["options"]]


def test_cancel_releases_slot(student):
    student.post("/api/v1/calendars/import-sample")
    appt = student.post("/api/v1/appointments/confirm", json={"slot_id": "slot_04", "student_approved": True, "idempotency_key": "key-cancel-1"}).json()
    assert student.post(f"/api/v1/appointments/{appt['appointment_id']}/cancel").json()["state"] == "CANCELLED"
    assert "slot_04" in [o["slot"]["id"] for o in _recs(student)["options"]]


def test_scheduling_endpoints_are_student_only(clinician):
    assert clinician.post("/api/v1/schedule/recommendations", json={}).status_code == 403
    assert clinician.post("/api/v1/appointments/confirm", json={"slot_id": "slot_04", "student_approved": True, "idempotency_key": "key-doc-0001"}).status_code == 403
