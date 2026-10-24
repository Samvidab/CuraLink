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


@pytest.fixture()
def app():
    dbmod.configure("sqlite://")
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
