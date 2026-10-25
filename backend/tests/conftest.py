import os
import pytest
from fastapi.testclient import TestClient

from app import db as dbmod
from app.main import create_app
from app.seed import DEMO_PASSWORD, reset_demo

HEADERS = {"X-CuraLink-Client": "web"}


@pytest.fixture(autouse=True)
def _no_live_integrations(monkeypatch):
    """Tests never call real services, even if the developer's .env has keys. Tests that need a
    'live' path stub it explicitly."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", None)
    monkeypatch.setattr(get_settings(), "cartesia_api_key", None)
    from app.services import llm_gateway

    monkeypatch.setitem(llm_gateway.STATUS, "auth_failed", False)
    monkeypatch.setitem(llm_gateway.STATUS, "last_error", None)


# Run the whole suite on Postgres with: TEST_DATABASE_URL=postgresql://... uv run pytest
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite://")


def _end_leftover_pg_sessions() -> None:
    """Postgres only: a test that inspected the DB directly may leave its session open in a transaction, and the next
    test's DROP TABLE would wait on it forever. End every other connection to the test database first."""
    import psycopg

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as c:
        c.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid()")


@pytest.fixture()
def app():
    if TEST_DATABASE_URL.startswith("postgres"):
        _end_leftover_pg_sessions()
    dbmod.configure(TEST_DATABASE_URL)
    gen = dbmod.get_db()
    reset_demo(next(gen))
    gen.close()
    return create_app()


def _client(app) -> TestClient:
    c = TestClient(app)
    c.headers.update(HEADERS)
    return c


@pytest.fixture()
def anon(app):
    return _client(app)


@pytest.fixture()
def student(app):
    c = _client(app)
    assert c.post("/api/v1/auth/demo/login", json={"persona": "student"}).status_code == 200
    return c


@pytest.fixture()
def clinician(app):
    c = _client(app)
    assert c.post("/api/v1/auth/demo/login", json={"persona": "clinician"}).status_code == 200
    return c


@pytest.fixture()
def login(app):
    def _login(email: str, password: str = DEMO_PASSWORD, expected_role: str | None = None):
        c = _client(app)
        r = c.post("/api/v1/auth/login", json={"email": email, "password": password, "expected_role": expected_role})
        return c, r

    return _login


def slot(clinician_id: str = "demo-clinician-1", local: str = "2026-10-26T10:30", appointment_type: str = "general_consultation") -> str:
    """Build an availability slot id (clinician|UTC start|type) from a local Indianapolis time."""
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    start = datetime.fromisoformat(local).replace(tzinfo=ZoneInfo("America/Indiana/Indianapolis")).astimezone(UTC)
    return f"{clinician_id}|{start.strftime('%Y-%m-%dT%H:%MZ')}|{appointment_type}"


RIVERA_MON_1030 = slot()
