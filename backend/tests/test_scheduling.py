from tests.conftest import RIVERA_MON_1030
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


# ---- clinician-aware scheduling API --------------------------------------------------------------------

import threading

from tests.conftest import RIVERA_MON_1030
from tests.conftest import slot as avail_slot

SEARCH = "/api/v1/schedule/search"


def search(c, **kw):
    r = c.post(SEARCH, json={"appointment_type": "general_consultation", **kw})
    assert r.status_code == 200, r.text
    return r.json()


def ids(card):
    return [s["id"] for s in card["slots"]]


def card(result, clinician_id):
    return next(c for c in result["clinicians"] if c["clinician_id"] == clinician_id)


def test_students_see_multiple_clinicians_with_real_profiles(student):
    r = search(student, per_clinician=40)
    by = {c["clinician_id"]: c for c in r["clinicians"]}
    assert {"demo-clinician-1", "demo-clinician-2", "demo-clinician-3"} <= set(by)
    rivera = by["demo-clinician-1"]
    assert (rivera["name"], rivera["credentials"], rivera["specialty"], rivera["clinic_name"]) == ("Dr. Avery Rivera", "MD (fictional)", "Primary Care", "Demo Student Health Clinic")
    assert rivera["slots"] and by["demo-clinician-2"]["slots"]
    assert by["demo-clinician-3"]["offers_type"] is False and by["demo-clinician-3"]["slots"] == []  # mental-health only
    assert "pending.clinician@clinic.example.com" not in str(r)  # unverified clinicians are never offered
    assert all(s["source_mode"] == "demo" for c in r["clinicians"] for s in c["slots"])
    listing = student.get("/api/v1/clinicians").json()
    assert {c["name"] for c in listing["clinicians"]} == {"Dr. Avery Rivera", "Dr. Morgan Hale", "Priya Nair, NP"}


def test_specific_clinician_only(student):
    r = search(student, clinician_id="demo-clinician-2", per_clinician=40)
    assert [c["clinician_id"] for c in r["clinicians"]] == ["demo-clinician-2"]
    assert all(s["clinician_id"] == "demo-clinician-2" for s in r["options"])


def test_slots_come_only_from_stored_hours_and_respect_durations_and_timezones(student):
    r = search(student, clinician_id="demo-clinician-1", start="2026-10-26", days=1, per_clinician=40)
    starts = [s["starts_at"] for s in card(r, "demo-clinician-1")["slots"]]
    # Rivera Mon: 09:00-12:00 and 13:30-16:30, 30-minute visits on a 15-minute grid, minus seeded bookings
    # (Jordan 09:00-09:30, Taylor 13:30-14:00); demo "now" is 08:00.
    assert "2026-10-26T09:00:00-04:00" not in starts and "2026-10-26T13:30:00-04:00" not in starts
    assert all(s.startswith("2026-10-26T") for s in starts)
    assert "2026-10-26T11:30:00-04:00" in starts and "2026-10-26T11:45:00-04:00" not in starts  # must fit before 12:00
    assert "2026-10-26T16:00:00-04:00" in starts and "2026-10-26T16:15:00-04:00" not in starts
    vac = search(student, appointment_type="vaccination", clinician_id="demo-clinician-1", start="2026-10-26", days=1, per_clinician=40)
    s0 = vac["clinicians"][0]["slots"][0]
    assert s0["minutes"] == 15 and "2026-10-26T16:15:00-04:00" in [s["starts_at"] for s in vac["clinicians"][0]["slots"]]
    after_dst = search(student, clinician_id="demo-clinician-1", start="2026-11-02", days=1, per_clinician=40)
    first = after_dst["clinicians"][0]["slots"][0]
    assert first["starts_at"] == "2026-11-02T09:00:00-05:00" and first["id"] == "demo-clinician-1|2026-11-02T14:00Z|general_consultation"


def test_class_conflicts_and_travel_buffers_are_excluded(student):
    student.post("/api/v1/calendars/import-sample")
    r = search(student, clinician_id="demo-clinician-1", start="2026-10-26", days=1, per_clinician=40)
    starts = [s["starts_at"][11:16] for s in card(r, "demo-clinician-1")["slots"]]
    # Sam's Monday: CS 240 09:30-10:20, STAT 11:30-12:20, PHIL 13:30-14:20, COM 15:00-15:50 (+8 min travel)
    assert "10:30" in starts and "16:00" in starts
    assert not {"09:15", "09:30", "10:00", "11:15", "11:30", "14:00", "14:30", "15:00"} & set(starts)
    assert r["excluded"].get("CLASS_CONFLICT") and r["excluded"].get("TRAVEL_BUFFER_CONFLICT")


def test_availability_exceptions(student):
    thu = search(student, start="2026-10-29", days=1, per_clinician=40)
    assert card(thu, "demo-clinician-1")["slots"] == []  # conference day
    fri_hale = search(student, clinician_id="demo-clinician-2", start="2026-10-30", days=1, per_clinician=40)
    fri = [s["starts_at"][11:16] for s in fri_hale["clinicians"][0]["slots"]]
    assert fri[0] == "09:00" and fri[-1] == "11:30"  # extra Friday hours (no weekly Friday rule)
    nair_wed = search(student, appointment_type="mental_health", clinician_id="demo-clinician-3", start="2026-10-28", days=1, per_clinician=40)
    wed = [s["starts_at"][11:16] for s in nair_wed["clinicians"][0]["slots"]]
    assert wed and max(wed) == "11:15"  # training afternoon removed; 45-min visit must end by 12:00
    vacation = search(student, clinician_id="demo-clinician-1", start="2026-11-23", days=5, per_clinician=40)
    assert vacation["clinicians"][0]["slots"] == [] and vacation["alternatives"]["same_clinician"]


def test_booking_assigns_the_chosen_clinician_and_reaches_only_them(student, clinician, login):
    student.post("/api/v1/calendars/import-sample")
    r = student.post("/api/v1/appointments/confirm", json={"slot_id": RIVERA_MON_1030, "student_approved": True, "idempotency_key": "book-key-0001"}).json()
    appt = r["appointment"]
    assert (appt["clinician_id"], appt["clinician_name"], appt["appointment_type"]) == ("demo-clinician-1", "Dr. Avery Rivera", "general_consultation")
    assert appt["starts_at"] == "2026-10-26T10:30:00-04:00" and appt["ends_at"] == "2026-10-26T11:00:00-04:00"
    enc = student.get("/api/v1/students/me/encounters").json()[0]
    assert enc["clinician_name"] == "Dr. Avery Rivera" and enc["appointment_id"] == r["appointment_id"]
    assert "Sam Lee" in [e["student_name"] for e in clinician.get("/api/v1/clinician/encounters").json()]
    hale, _ = login("dr.hale@clinic.example.com")
    assert "Sam Lee" not in [e["student_name"] for e in hale.get("/api/v1/clinician/encounters").json()]
    assert hale.get(f"/api/v1/clinician/encounters/{enc['id']}").status_code == 403
    # The booked time disappears for everyone.
    again = search(student, clinician_id="demo-clinician-1", start="2026-10-26", days=1, per_clinician=40)
    assert RIVERA_MON_1030 not in ids(again["clinicians"][0])


def test_booked_clinician_time_is_excluded_for_other_students(student, login):
    student.post("/api/v1/appointments/confirm", json={"slot_id": RIVERA_MON_1030, "student_approved": True, "idempotency_key": "book-key-0002"})
    jordan, _ = login("jordan.kim@students.example.com")
    r = jordan.post(SEARCH, json={"appointment_type": "general_consultation", "clinician_id": "demo-clinician-1", "start": "2026-10-26", "days": 1, "per_clinician": 40}).json()
    starts = [s["starts_at"][11:16] for s in r["clinicians"][0]["slots"]]
    assert "10:30" not in starts and "10:15" not in starts and "10:45" not in starts  # whole 30-min interval blocked
    assert jordan.post("/api/v1/appointments/confirm", json={"slot_id": RIVERA_MON_1030, "student_approved": True, "idempotency_key": "book-key-0003"}).json()["code"] == "SLOT_UNAVAILABLE"


def test_confirm_is_explicit_and_idempotent(student):
    body = {"slot_id": RIVERA_MON_1030, "student_approved": False, "idempotency_key": "idem-key-0001"}
    assert student.post("/api/v1/appointments/confirm", json=body).status_code == 400
    body["student_approved"] = True
    a = student.post("/api/v1/appointments/confirm", json=body).json()
    b = student.post("/api/v1/appointments/confirm", json=body).json()
    assert a["appointment_id"] == b["appointment_id"] and len(student.get("/api/v1/appointments/me").json()) == 1


def test_stale_slot_is_rechecked_at_confirmation(student):
    sid = avail_slot("demo-clinician-1", "2026-10-26T14:30")
    assert student.post("/api/v1/demo/book-as-other", json={"slot_id": sid}).json()["status"] == "BOOKED_BY_SOMEONE_ELSE"
    r = student.post("/api/v1/appointments/confirm", json={"slot_id": sid, "student_approved": True, "idempotency_key": "stale-key-001"})
    assert r.status_code == 409 and r.json()["code"] == "SLOT_UNAVAILABLE" and r.json()["recoverable"]
    assert sid not in ids(search(student, clinician_id="demo-clinician-1", start="2026-10-26", days=1, per_clinician=40)["clinicians"][0])


def test_confirm_rechecks_student_conflicts_and_other_appointments(student):
    student.post("/api/v1/calendars/import-sample")
    clash = student.post("/api/v1/appointments/confirm", json={"slot_id": avail_slot("demo-clinician-1", "2026-10-26T09:30"), "student_approved": True, "idempotency_key": "clash-key-001"})
    assert clash.status_code == 409 and clash.json()["code"] == "CLASS_CONFLICT"
    student.post("/api/v1/appointments/confirm", json={"slot_id": RIVERA_MON_1030, "student_approved": True, "idempotency_key": "own-key-0001"})
    own = student.post("/api/v1/appointments/confirm", json={"slot_id": avail_slot("demo-clinician-2", "2026-10-26T10:30"), "student_approved": True, "idempotency_key": "own-key-0002"})
    assert own.status_code == 409  # can't be in two appointments at once
    hale = search(student, clinician_id="demo-clinician-2", start="2026-10-26", days=1, per_clinician=40)
    assert "10:30" not in [s["starts_at"][11:16] for s in hale["clinicians"][0]["slots"]]


def test_unknown_or_unavailable_clinician_requests(student):
    assert student.post(SEARCH, json={"clinician_id": "dr-nobody"}).status_code == 404
    r = search(student, clinician_id="demo-clinician-1", start="2026-10-29", days=1)  # conference day
    assert "Dr. Avery Rivera has no openings" in r["notice"]
    assert r["alternatives"]["same_clinician"] and all(s["clinician_id"] == "demo-clinician-1" for s in r["alternatives"]["same_clinician"])
    assert r["alternatives"]["other_clinicians"] and all(s["clinician_id"] != "demo-clinician-1" for s in r["alternatives"]["other_clinicians"])
    assert r["options"] == []  # the explicit preference is not silently replaced
    wrong_type = search(student, appointment_type="mental_health", clinician_id="demo-clinician-1")
    assert "doesn't offer mental health" in wrong_type["notice"]


def test_attribute_preference_uses_only_self_reported_profile_data(student):
    r = search(student, attribute={"gender": "woman"})
    assert [c["clinician_id"] for c in r["clinicians"]] == ["demo-clinician-1"]  # Nair has no stated attribute -> not assumed
    assert search(student, attribute={"gender": "nonbinary"})["notice"] == "No clinician matches that preference in this demo."


def test_cancel_frees_the_clinicians_time(student):
    a = student.post("/api/v1/appointments/confirm", json={"slot_id": RIVERA_MON_1030, "student_approved": True, "idempotency_key": "cancel-key-01"}).json()
    assert student.post(f"/api/v1/appointments/{a['appointment_id']}/cancel").json()["state"] == "CANCELLED"
    assert RIVERA_MON_1030 in ids(search(student, clinician_id="demo-clinician-1", start="2026-10-26", days=1, per_clinician=40)["clinicians"][0])


def test_personal_block_is_respected(student):
    student.post("/api/v1/calendar/blocks", json={"start_at": "2026-10-26T10:00:00-04:00", "end_at": "2026-10-26T11:15:00-04:00", "label": "Lab shift"})
    starts = [s["starts_at"][11:16] for s in search(student, clinician_id="demo-clinician-1", start="2026-10-26", days=1, per_clinician=40)["clinicians"][0]["slots"]]
    assert "10:30" not in starts and "10:00" not in starts


def test_scheduling_endpoints_are_student_only(clinician):
    assert clinician.post(SEARCH, json={}).status_code == 403
    assert clinician.post("/api/v1/appointments/confirm", json={"slot_id": RIVERA_MON_1030, "student_approved": True, "idempotency_key": "doc-key-0001"}).status_code == 403


def test_concurrent_bookings_cannot_double_book(tmp_path):
    """Two sessions race for the same clinician time (and an overlapping start) on a real file database."""
    from app import db as dbmod
    from app.config import get_settings
    from app.errors import ApiError
    from app.seed import reset_demo
    from app.services import availability
    from app.timeutil import demo_now

    dbmod.configure(f"sqlite:///{tmp_path / 'race.db'}")
    gen = dbmod.get_db()
    reset_demo(next(gen))
    gen.close()
    now = demo_now(get_settings().demo_today, get_settings().demo_timezone)

    def race(slot_ids):
        barrier, results = threading.Barrier(len(slot_ids)), []

        def worker(sid):
            g = dbmod.get_db()
            db = next(g)
            try:
                cand, profile = availability.validate(db, sid, now)
                barrier.wait(timeout=5)
                availability.book(db, cand, profile)
                db.commit()
                results.append("ok")
            except ApiError as exc:
                results.append(exc.code)
            except Exception as exc:  # SQLite busy/locked also means "lost the race"
                results.append(type(exc).__name__)
            finally:
                g.close()

        threads = [threading.Thread(target=worker, args=(s,)) for s in slot_ids]
        [t.start() for t in threads]
        [t.join() for t in threads]
        return results

    same = race([RIVERA_MON_1030, RIVERA_MON_1030])
    assert same.count("ok") == 1, same
    overlapping = race([avail_slot("demo-clinician-2", "2026-10-26T10:30"), avail_slot("demo-clinician-2", "2026-10-26T10:45", "vaccination")])
    assert overlapping.count("ok") == 1, overlapping
    g = dbmod.get_db()
    db = next(g)
    from sqlalchemy import select

    from app.models import ClinicSlot

    booked = db.scalars(select(ClinicSlot).where(ClinicSlot.status == "BOOKED", ClinicSlot.clinician_id.in_(["demo-clinician-1", "demo-clinician-2"]))).all()
    for a in booked:
        for b in booked:
            if a.id < b.id and a.clinician_id == b.clinician_id:
                assert not (a.starts_at < b.ends_at and b.starts_at < a.ends_at), (a.id, b.id)
    g.close()


# ---- assistant integration -------------------------------------------------------------------------------

def say(c, text, **kw):
    r = c.post("/api/v1/intake/messages", json={"message": text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_assistant_lists_clinicians_and_narrows_to_a_requested_one(student):
    student.post("/api/v1/calendars/import-sample")
    say(student, "I have a sore throat since yesterday")
    r = say(student, "Which doctors are available?")
    assert r["conversation_state"] == "COORDINATING_APPOINTMENT" and r["schedule"]
    with_slots = [c["name"] for c in r["schedule"]["clinicians"] if c["slots"]]
    assert {"Dr. Avery Rivera", "Dr. Morgan Hale"} <= set(with_slots) and "Available clinicians" in r["assistant_message"]
    r = say(student, "Can I see Dr. Rivera?")
    cards = r["schedule"]["clinicians"]
    assert [c["clinician_id"] for c in cards] == ["demo-clinician-1"] and "Rivera" in r["assistant_message"]
    backend = search(student, clinician_id="demo-clinician-1", per_clinician=4)
    assert ids(cards[0]) == ids(backend["clinicians"][0])  # the assistant shows exactly what the scheduler returns
    r = say(student, "tomorrow afternoon")
    s = r["schedule"]["clinicians"][0]["slots"]
    assert s and all(x["starts_at"].startswith("2026-10-27T1") and int(x["starts_at"][11:13]) >= 12 for x in s)
    r = say(student, "I don't have a preference, who has the earliest appointment?")
    assert len(r["schedule"]["clinicians"]) > 1 and "earliest" in r["assistant_message"].lower()


def test_assistant_explains_unavailable_clinician_and_offers_alternatives(student):
    r = say(student, "I only want to see Dr. Rivera on Thursday")
    assert "no openings" in r["assistant_message"] and "next openings" in r["assistant_message"]
    assert r["schedule"]["alternatives"]["same_clinician"]


def test_assistant_same_doctor_as_last_time_and_gender_preference(student):
    student.post("/api/v1/appointments/confirm", json={"slot_id": avail_slot("demo-clinician-2", "2026-10-26T10:30"), "student_approved": True, "idempotency_key": "last-time-001"})
    r = say(student, "Can I see the same doctor I saw last time?")
    assert [c["clinician_id"] for c in r["schedule"]["clinicians"]] == ["demo-clinician-2"]
    r = say(student, "Can you find me a female doctor?")
    assert [c["clinician_id"] for c in r["schedule"]["clinicians"]] == ["demo-clinician-1"]


def test_repeated_assistant_messages_never_book(student):
    for _ in range(3):
        say(student, "Book me with Dr. Rivera on Monday morning")
    say(student, "Book me with Dr. Rivera on Monday morning", client_turn_id="same-turn-1")
    say(student, "Book me with Dr. Rivera on Monday morning", client_turn_id="same-turn-1")
    assert student.get("/api/v1/appointments/me").json() == []  # only an explicit, confirmed booking creates one
