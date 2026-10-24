def test_health_reports_fallbacks_without_keys(anon):
    body = anon.get("/api/v1/health").json()
    assert body["demo_mode"] is True
    assert body["integrations"]["clinic_inventory"] == "demo"
    assert body["integrations"]["email_delivery"] == "test_only"


def test_unauthenticated_requests_get_401(anon):
    assert anon.get("/api/v1/me").status_code == 401
    assert anon.get("/api/v1/students/me/dashboard").status_code == 401
    assert anon.get("/api/v1/clinician/dashboard").status_code == 401


def test_demo_login_role_comes_from_server(student, clinician):
    assert student.get("/api/v1/me").json()["role"] == "student"
    me = clinician.get("/api/v1/me").json()
    assert me["role"] == "clinician" and "documents:sign" in me["permissions"]


def test_session_cookie_is_httponly(app):
    from fastapi.testclient import TestClient

    r = TestClient(app).post("/api/v1/auth/demo/login", json={"persona": "student"}, headers={"X-CuraLink-Client": "web"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_cross_role_access_is_403(student, clinician):
    assert student.get("/api/v1/clinician/dashboard").status_code == 403
    assert student.get("/api/v1/clinician/encounters/enc_jordan_1").status_code == 403
    assert clinician.get("/api/v1/students/me/dashboard").status_code == 403
    assert clinician.post("/api/v1/calendars/import-sample").status_code == 403


def test_clinician_sees_only_assigned_encounters(clinician, login):
    ids = {e["id"] for e in clinician.get("/api/v1/clinician/encounters").json()}
    assert ids == {"enc_jordan_1", "enc_taylor_1"}
    assert clinician.get("/api/v1/clinician/encounters/enc_jordan_1").status_code == 200
    # Assigned to Dr. Hale, not Dr. Rivera. Same response as a nonexistent id.
    r1 = clinician.get("/api/v1/clinician/encounters/enc_jordan_hale")
    r2 = clinician.get("/api/v1/clinician/encounters/does-not-exist")
    assert r1.status_code == r2.status_code == 403
    assert r1.json() == r2.json()
    hale, r = login("dr.hale@clinic.example.com")
    assert r.status_code == 200
    assert {e["id"] for e in hale.get("/api/v1/clinician/encounters").json()} == {"enc_jordan_hale"}


def test_dashboard_lists_have_no_symptom_fields(clinician):
    row = clinician.get("/api/v1/clinician/dashboard").json()["encounters"][0]
    assert set(row) == {"id", "student_name", "starts_at", "visit_type", "status", "status_label", "source_mode"}


def test_password_login_and_portal_checks(login):
    _, bad = login("dr.rivera@clinic.example.com", "wrong-password")
    assert bad.status_code == 401
    _, wrong_portal = login("sam.lee@students.example.com", expected_role="clinician")
    assert wrong_portal.status_code == 403 and wrong_portal.json()["code"] == "WRONG_PORTAL"
    _, unverified = login("pending.clinician@clinic.example.com", expected_role="clinician")
    assert unverified.status_code == 403 and unverified.json()["code"] == "CLINICIAN_NOT_VERIFIED"
    _, ok = login("DR.RIVERA@clinic.example.com", expected_role="clinician")
    assert ok.status_code == 200 and ok.json()["role"] == "clinician"


def test_role_cannot_be_injected_via_request(anon):
    r = anon.post("/api/v1/auth/demo/login", json={"persona": "admin"})
    assert r.status_code == 422


def test_state_change_without_client_header_is_rejected(student):
    del student.headers["X-CuraLink-Client"]
    assert student.post("/api/v1/calendars/import-sample").status_code == 403


def test_logout_revokes_session(student):
    assert student.post("/api/v1/auth/logout").status_code == 204
    assert student.get("/api/v1/me").status_code == 401


def test_validation_errors_do_not_echo_input(student):
    r = student.patch("/api/v1/students/me/profile", json={"display_name": "x" * 500})
    assert r.status_code == 422
    assert "xxxx" not in r.text


def test_seeded_times_keep_local_wall_clock(clinician):
    """Regression: aware non-UTC datetimes must be stored as UTC, not as local wall time."""
    rows = {e["id"]: e for e in clinician.get("/api/v1/clinician/encounters").json()}
    assert rows["enc_jordan_1"]["starts_at"] == "2026-10-26T09:00:00-04:00"
