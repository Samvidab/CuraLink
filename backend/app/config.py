"""Runtime configuration. All secrets come from the environment and stay server-side."""

import os

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]  # also the bundle root when deployed as a Vercel function


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        extra="ignore",
    )

    # Demo mode is the only supported mode for the hackathon. Pilot mode is
    # deliberately unimplemented: demo endpoints refuse to run outside demo.
    demo_mode: bool = True
    database_url: str = f"sqlite:///{REPO_ROOT / 'backend' / 'curalink_demo.db'}"
    sample_data_dir: Path = BACKEND_DIR / "sample_data"  # inside backend/ so serverless bundles include it
    cors_origins: str = "http://localhost:8443,http://127.0.0.1:8443,http://localhost:5173"

    # Fixed "today" so the fictional demo week is reproducible.
    demo_today: date = date(2026, 10, 26)
    # CURALINK_CONFIG: SCHEDULING_TIMEZONE
    # Default timezone for students/clinicians and demo dates. Each clinic's own timezone (demo_availability.json)
    # is used to interpret clinician working hours; all instants are stored in UTC and DST-safe via zoneinfo.
    demo_timezone: str = "America/Indiana/Indianapolis"

    session_cookie_name: str = "curalink_session"
    session_ttl_minutes: int = 8 * 60
    cookie_secure: bool = False

    # CURALINK_CONFIG: DEPLOYMENT
    # local (default): developer laptop. production: a public deployment; startup refuses unsafe settings
    # (see app/deploy_checks.py and docs/DEPLOYMENT.md). Values are never logged.
    environment: Literal["local", "production"] = "local"
    # Demo admin controls (data reset, "book as another student", forced delivery failure):
    #   open  = anyone (local only)   token = requires header X-CuraLink-Admin: <DEMO_ADMIN_TOKEN>   off = disabled
    demo_controls: Literal["open", "token", "off"] = "open"
    demo_admin_token: str | None = None
    # Built frontend (frontend/dist) to serve from the API process: one same-origin deployable, so the
    # HttpOnly session cookie stays first-party and no cross-site CORS is needed.
    frontend_dist: Path | None = None
    # Public HTTPS origin of THIS API (e.g. https://203-0-113-7.sslip.io). Used as the Convex token issuer and for
    # the direct voice WebSocket URL when the frontend is hosted elsewhere (Vercel can't proxy WebSockets).
    public_api_url: str | None = None
    # Shared secret Vercel adds to every proxied /api request (x-origin-secret); requests that bypass Vercel are
    # refused. Exempt: /api/v1/health and the ticket-authenticated voice WebSocket.
    origin_secret: str | None = None
    # Where generated keys live (Convex token signing key). Production: on the persistent volume.
    secrets_dir: Path = REPO_ROOT / "backend" / ".secrets"

    # CURALINK_CONFIG: CONVEX
    # Convex keeps a persistent, real-time synchronized copy of committed records (frontend/convex). The backend
    # writes with CONVEX_SYNC_SECRET (also set in the Convex deployment as CURALINK_SYNC_SECRET); browsers read with
    # short-lived RS256 tokens from GET /api/v1/convex/token. Unset -> sync off (local development unchanged).
    convex_site_url: str | None = None  # https://<deployment>.convex.site
    convex_sync_secret: str | None = None
    # PEM private key for Convex tokens. Required where the disk isn't persistent (Vercel); otherwise generated
    # once into SECRETS_DIR. Multi-line values are fine in Vercel's environment settings.
    convex_jwt_private_key: str | None = None
    # The token issuer name Convex expects (its CURALINK_JWT_ISSUER). Defaults to PUBLIC_API_URL / local API.
    convex_jwt_issuer: str | None = None
    # Serverless platforms may freeze an instance after the response: push to Convex inside the request there.
    convex_sync_inline: bool = bool(os.environ.get("VERCEL"))
    # Set ONLY when the voice WebSocket is served from a different host than the page (then a single-use ticket is
    # used because the session cookie isn't sent cross-site). Same-origin deployments (Vercel Services) leave it empty.
    voice_ws_base: str | None = None
    # Largest photo upload. Vercel Functions accept request bodies up to 4.5 MB, so use 4 there.
    max_upload_mb: float = 12

    # Delivery never leaves this allowlist in demo mode.
    test_email_allowlist: str = "example.com"
    # CURALINK_CONFIG: DEMO_TEST_INBOX
    # Real-looking instructor addresses (e.g. from a UniTime export) are NEVER contacted in the demo. With this on,
    # a delivery the clinician approved for such an instructor is written to the isolated in-app test inbox under a
    # fictional alias (<course>.instructor@DEMO_INBOX_DOMAIN); the real address is kept only as display data.
    # Off -> those recipients are shown as "not permitted for demo delivery" and nothing is written.
    demo_inbox_redirect: bool = True
    demo_inbox_domain: str = "test-inbox.example.com"

    # Optional integrations. Absent keys => clearly labelled fallbacks.
    # CURALINK_CONFIG: ANTHROPIC_API_KEY
    # Create a key at https://console.anthropic.com/ (Settings -> API Keys) and put
    # ANTHROPIC_API_KEY=... in the repo-root .env (git-ignored). Read only here, server-side;
    # never prefix with VITE_ or reference it from frontend code. Missing -> scripted assistant.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "low"  # conversational turns; raise for harder reasoning
    # CURALINK_CONFIG: CARTESIA_API_KEY
    # Create a key in the Cartesia dashboard (https://play.cartesia.ai/ -> API Keys) and set
    # CARTESIA_API_KEY=... in .env. Used only by app/services/cartesia.py on the server.
    # Missing -> browser speech fallback (labelled "Browser speech · fallback", never "Cartesia").
    cartesia_api_key: str | None = None
    # Verified against docs.cartesia.ai (STT + TTS WebSocket references) on 2026-10-24.
    cartesia_version: str = "2026-08-14"
    cartesia_stt_url: str = "wss://api.cartesia.ai/stt/websocket"
    cartesia_stt_model: str = "ink-whisper"
    cartesia_tts_url: str = "wss://api.cartesia.ai/tts/websocket"
    cartesia_tts_model: str = "sonic-3.6"
    # CURALINK_CONFIG: CARTESIA_VOICE_ID
    # CuraLink's spoken voice. Pick a voice in the Cartesia playground (Voices -> copy ID) and set
    # CARTESIA_VOICE_ID=... in .env. Default is the voice from Cartesia's documentation example.
    cartesia_voice_id: str = "a0e99841-438c-4a64-b679-ae501e7d6091"
    enable_photo_observations: bool = True
    # CURALINK_CONFIG: VISION_MODEL
    # Model for NON-DIAGNOSTIC photo observations (app/services/llm_gateway.py::describe_image).
    # Defaults to ANTHROPIC_MODEL; override with VISION_MODEL=... Without an Anthropic key the
    # deterministic colour analysis in app/services/vision.py is used (labelled "not a medical model").
    vision_model: str | None = None

    # CURALINK_CONFIG: CLINIC_PROFILE  (values below are FICTIONAL demo defaults; see app/curalink_config.py)
    clinic_name: str = "Demo Student Health Clinic (fictional)"
    clinic_address: str = "100 Example Way, West Lafayette, IN 47906 (fictional)"
    clinic_phone: str = "(555) 010-0100"
    clinic_email: str = "clinic@clinic.example.com"

    # CURALINK_CONFIG: SIGNATURE_ENCRYPTION
    # 32-byte AES key, base64url-encoded: python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
    # Set SIGNATURE_ENCRYPTION_KEY in .env (or a secret manager in production). If unset in demo mode,
    # a local key is generated at backend/.secrets/signature.key (git-ignored). Never commit a key.
    signature_encryption_key: str | None = None

    # CURALINK_CONFIG: EMAIL_DELIVERY_MODE
    # Only "test_inbox" is implemented. Any other value refuses to send (see absence_service.transport()).
    # Approval, consent and signature gates are enforced regardless of this setting.
    email_delivery_mode: str = "test_inbox"
    # CURALINK_CONFIG: EMAIL_SENDER
    email_sender: str = "no-reply@clinic.example.com"

    # CURALINK_CONFIG: UNIVERSITY_DIRECTORY
    # Base URL of an AUTHORIZED university directory API/connector. Unset = disabled (no lookups).
    # TODO(CURALINK-MANUAL): obtain written authorization + API details from the university before enabling.
    university_directory_url: str | None = None
    # CURALINK_CONFIG: COURSE_CATALOG_SOURCE  ("demo_catalog" = sample_data/demo_courses.json; "none" disables)
    course_catalog_source: str = "demo_catalog"
    # CURALINK_CONFIG: ACADEMIC_TERM
    academic_term_id: str = "FALL-2026-DEMO"
    academic_term_start: date | None = None  # TODO(CURALINK-MANUAL): set official term dates for production
    academic_term_end: date | None = None
    voice_input_sample_rate: int = 16000
    voice_output_sample_rate: int = 24000

    @property
    def cors_origin_list(self) -> list[str]:
        explicit = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        if os.environ.get("VERCEL"):
            # On Vercel the page and API share one origin; allow exactly this deployment's own HTTPS hosts
            # (Vercel system variables), plus any explicitly configured non-local origins.
            own = [f"https://{h}" for h in (os.environ.get("VERCEL_PROJECT_PRODUCTION_URL"), os.environ.get("VERCEL_URL")) if h]
            return own + [o for o in explicit if "localhost" not in o and "127.0.0.1" not in o]
        return explicit

    @property
    def allowlisted_domains(self) -> list[str]:
        return [d.strip().lower() for d in self.test_email_allowlist.split(",") if d.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
