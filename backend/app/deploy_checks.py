"""Startup self-check for a public deployment (ENVIRONMENT=production). Reports problems by NAME only;
secret values are never printed or logged."""

from app.config import Settings

DEFAULT_LOCAL_ORIGINS = ("localhost", "127.0.0.1")


def production_problems(s: Settings) -> list[str]:
    problems = []
    if not s.cookie_secure:
        problems.append("COOKIE_SECURE must be true (HTTPS-only session cookie).")
    if s.demo_controls == "open":
        problems.append("DEMO_CONTROLS must be 'token' or 'off' (data reset must not be public).")
    if s.demo_controls == "token" and (not s.demo_admin_token or len(s.demo_admin_token) < 24):
        problems.append("DEMO_ADMIN_TOKEN must be set to a random value of at least 24 characters.")
    if not s.signature_encryption_key:
        problems.append("SIGNATURE_ENCRYPTION_KEY must be set (no auto-generated key file in production).")
    if any(o and any(h in o for h in DEFAULT_LOCAL_ORIGINS) for o in s.cors_origin_list):
        problems.append("CORS_ORIGINS must list only the public HTTPS origin(s), not localhost.")
    if any(o.startswith("http://") for o in s.cors_origin_list):
        problems.append("CORS_ORIGINS must use https:// origins.")
    if not s.database_url.startswith("sqlite:////") and s.database_url.startswith("sqlite"):
        problems.append("DATABASE_URL must be an absolute path on the persistent volume (sqlite:////data/curalink.db).")
    return problems
