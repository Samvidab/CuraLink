"""Public-deployment safety: demo admin controls, data scoping, production self-check, same-origin SPA."""

import pytest

from app.config import Settings, get_settings
from app.deploy_checks import production_problems
from tests.conftest import _client


@pytest.fixture()
def settings(monkeypatch):
    s = get_settings()
    yield s


def test_demo_reset_is_closed_unless_open_or_token(app, settings, monkeypatch):
    c = _client(app)
    monkeypatch.setattr(settings, "demo_controls", "off")
    assert c.post("/api/v1/demo/reset").status_code == 404
    monkeypatch.setattr(settings, "demo_controls", "token")
    monkeypatch.setattr(settings, "demo_admin_token", "t" * 32)
    assert c.post("/api/v1/demo/reset").status_code == 404
    assert c.post("/api/v1/demo/reset", headers={"X-CuraLink-Admin": "wrong"}).status_code == 404
    assert c.post("/api/v1/demo/reset", headers={"X-CuraLink-Admin": "t" * 32}).status_code == 200
    student = _client(app)
    student.post("/api/v1/auth/demo/login", json={"persona": "student"})
    assert student.post("/api/v1/demo/book-as-other", json={"slot_id": "x|2026-10-26T14:30Z|general_consultation"}).status_code == 404
    assert student.post("/api/v1/demo/transport/fail-next").status_code == 404


def test_production_self_check_names_problems_without_values():
    bad = Settings(environment="production", cookie_secure=False, demo_controls="open", cors_origins="http://localhost:8443",
                   signature_encryption_key=None, anthropic_api_key="sk-ant-secret-value", database_url="sqlite:///relative.db")
    problems = production_problems(bad)
    assert len(problems) >= 5 and not any("sk-ant" in p for p in problems)
    good = Settings(environment="production", cookie_secure=True, demo_controls="token", demo_admin_token="x" * 40, cors_origins="https://curalink.example.app",
                    signature_encryption_key="k" * 44, database_url="sqlite:////data/curalink.db", secrets_dir="/data/secrets")
    assert production_problems(good) == []


def test_frontend_served_same_origin_with_spa_fallback(tmp_path, monkeypatch):
    from app import db as dbmod
    from app.main import create_app
    from app.seed import reset_demo

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "CuraLinkLogo2.png").write_bytes(b"png")
    monkeypatch.setattr(get_settings(), "frontend_dist", tmp_path)
    dbmod.configure("sqlite://")
    reset_demo(next(dbmod.get_db()))
    from fastapi.testclient import TestClient

    c = TestClient(create_app())
    assert c.get("/student/dashboard").text == "<div id=root></div>"  # client-side route
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert c.get("/CuraLinkLogo2.png").content == b"png"
    assert c.get("/api/v1/health").json()["status"] == "ok"
    assert c.get("/api/v1/nope").status_code == 404
    assert c.get("/../backend/curalink_demo.db").text == "<div id=root></div>"  # no path traversal


def test_test_inbox_only_shows_the_viewers_own_cases(app, student, login):
    jordan, _ = login("jordan.kim@students.example.com")
    assert jordan.get("/api/v1/demo/test-inbox").json() == []
    hale, _ = login("dr.hale@clinic.example.com")
    assert hale.get("/api/v1/demo/test-inbox").json() == []


def test_convex_settings_are_validated_in_production():
    base = dict(environment="production", cookie_secure=True, demo_controls="off", cors_origins="https://curalink.vercel.app",
                signature_encryption_key="k" * 44, database_url="sqlite:////data/curalink.db", secrets_dir="/data/secrets")
    bad = production_problems(Settings(**base, convex_site_url="http://x.convex.cloud", convex_sync_secret="short", origin_secret="tiny"))
    assert any("CONVEX_SITE_URL" in p for p in bad) and any("CONVEX_SYNC_SECRET" in p for p in bad) and any("PUBLIC_API_URL" in p for p in bad)
    assert any("ORIGIN_SECRET" in p for p in bad) and not any("short" in p or "tiny" in p for p in bad)
    good = Settings(**base, convex_site_url="https://happy-animal-123.convex.site", convex_sync_secret="s" * 40, public_api_url="https://api.example.com", origin_secret="o" * 40)
    assert production_problems(good) == []


def test_origin_secret_blocks_requests_that_bypass_the_proxy(app, monkeypatch):
    monkeypatch.setattr(get_settings(), "origin_secret", "o" * 40)
    c = _client(app)
    assert c.get("/api/v1/health").status_code == 200  # health stays reachable for monitoring
    assert c.post("/api/v1/auth/demo/login", json={"persona": "student"}).status_code == 403
    assert c.post("/api/v1/auth/demo/login", json={"persona": "student"}, headers={"x-origin-secret": "wrong"}).status_code == 403
    assert c.post("/api/v1/auth/demo/login", json={"persona": "student"}, headers={"x-origin-secret": "o" * 40}).status_code == 200


def test_api_docs_are_off_in_production(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setattr(get_settings(), "environment", "production")
    app = create_app()
    assert app.docs_url is None and app.openapi_url is None
