"""Runtime configuration. All secrets come from the environment and stay server-side."""

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        extra="ignore",
    )

    # Demo mode is the only supported mode for the hackathon. Pilot mode is
    # deliberately unimplemented: demo endpoints refuse to run outside demo.
    demo_mode: bool = True
    database_url: str = f"sqlite:///{REPO_ROOT / 'backend' / 'curalink_demo.db'}"
    sample_data_dir: Path = REPO_ROOT / "sample_data"
    cors_origins: str = "http://localhost:8443,http://127.0.0.1:8443,http://localhost:5173"

    # Fixed "today" so the fictional demo week is reproducible.
    demo_today: date = date(2026, 10, 26)
    demo_timezone: str = "America/Indiana/Indianapolis"

    session_cookie_name: str = "curalink_session"
    session_ttl_minutes: int = 8 * 60
    cookie_secure: bool = False

    # Delivery never leaves this allowlist in demo mode.
    test_email_allowlist: str = "example.com"

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
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowlisted_domains(self) -> list[str]:
        return [d.strip().lower() for d in self.test_email_allowlist.split(",") if d.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
