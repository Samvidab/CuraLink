SAMPLE_PATH = "../sample_data/sample.ics"


def test_new_student_starts_without_calendar(student):
    d = student.get("/api/v1/students/me/dashboard").json()
    assert d["calendar"] is None and d["todays_classes"] == [] and d["next_appointment"] is None
    assert d["display_name"] == "Sam Lee"


def test_sample_import_populates_dashboard(student):
    r = student.post("/api/v1/calendars/import-sample").json()
    assert r["source_mode"] == "demo" and r["timezone"] == "America/Indiana/Indianapolis"
    statuses = {c["code"]: c["contact_status"] for c in r["courses"]}
    assert statuses == {"CS 240": "VERIFIED", "STAT 350": "VERIFIED", "PHIL 208": "MISSING", "COM 217": "NEEDS_REVIEW"}
    # No invented address for the course without a verified contact.
    assert next(c for c in r["courses"] if c["code"] == "PHIL 208")["instructor_email"] is None
    d = student.get("/api/v1/students/me/dashboard").json()
    assert [c["course_code"] for c in d["todays_classes"]] == ["CS 240", "STAT 350", "PHIL 208", "COM 217"]
    assert d["todays_classes"][0]["start_at"] == "2026-10-26T09:30:00-04:00"
    assert d["activity"][0]["event_type"] == "CALENDAR_IMPORTED"


def test_upload_ics_and_week_events(student):
    with open(SAMPLE_PATH, "rb") as f:
        r = student.post("/api/v1/calendars/import", files={"file": ("my-unitime.ics", f, "text/calendar")})
    assert r.status_code == 200 and r.json()["source_mode"] == "uploaded"
    week = student.get("/api/v1/calendar/events", params={"start": "2026-10-26", "end": "2026-11-02"}).json()
    by_day: dict[str, list[str]] = {}
    for e in week["events"]:
        by_day.setdefault(e["start_at"][:10], []).append(e["course_code"])
    assert "CS 240" not in by_day["2026-10-30"]  # EXDATE
    assert "2026-10-27" not in by_day  # no Tuesday classes
    moved = [e for e in week["events"] if e["rescheduled"]]
    assert len(moved) == 1 and moved[0]["start_at"] == "2026-10-28T14:30:00-04:00"


def test_bad_upload_is_rejected_with_recoverable_error(student):
    r = student.post("/api/v1/calendars/import", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "ICS_WRONG_TYPE" and body["recoverable"] is True


def test_delete_calendar(student):
    student.post("/api/v1/calendars/import-sample")
    assert student.delete("/api/v1/calendars/me").status_code == 204
    assert student.get("/api/v1/students/me/dashboard").json()["calendar"] is None


def test_profile_update(student):
    assert student.patch("/api/v1/students/me/profile", json={"display_name": "Sam L."}).json()["display_name"] == "Sam L."
