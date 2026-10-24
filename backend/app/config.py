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
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "low"  # conversational turns; raise for harder reasoning
    cartesia_api_key: str | None = None
    # Verified against docs.cartesia.ai (STT + TTS WebSocket references) on 2026-10-24.
    cartesia_version: str = "2026-08-14"
    cartesia_stt_url: str = "wss://api.cartesia.ai/stt/websocket"
    cartesia_stt_model: str = "ink-whisper"
    cartesia_tts_url: str = "wss://api.cartesia.ai/tts/websocket"
    cartesia_tts_model: str = "sonic-3.6"
    # Voice from Cartesia's documentation example; set your own in .env.
    cartesia_voice_id: str = "a0e99841-438c-4a64-b679-ae501e7d6091"
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
