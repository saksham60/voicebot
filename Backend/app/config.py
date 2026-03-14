from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "hotel-digital-receptionist"
    environment: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    hotel_name: str = "Hotel Oman"
    hotel_timezone: str = "Asia/Calcutta"
    hotel_phone_number: str = ""
    public_base_url: str = "https://example.ngrok-free.app"

    openai_api_key: str = ""
    openai_realtime_model: str = "gpt-realtime"
    openai_realtime_voice: str = "marin"
    openai_transcription_model: str = "gpt-4o-mini-transcribe"

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_validate_requests: bool = False
    twilio_transfer_number: str = ""

    booking_provider_name: str = "manual-review"

    request_timeout_seconds: int = 30
    openai_connect_timeout_seconds: int = 20
    openai_heartbeat_seconds: int = 20

    @computed_field(return_type=Path)
    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @computed_field(return_type=Path)
    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @computed_field(return_type=Path)
    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "calls.db"

    @computed_field(return_type=str)
    @property
    def twilio_voice_webhook_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/twilio/voice"

    @computed_field(return_type=str)
    @property
    def twilio_post_connect_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/twilio/post-connect"

    @computed_field(return_type=str)
    @property
    def twilio_media_stream_url(self) -> str:
        base = self.public_base_url.rstrip("/")
        if base.startswith("https://"):
            return f"wss://{base[len('https://'):]}/twilio/media-stream"
        if base.startswith("http://"):
            return f"ws://{base[len('http://'):]}/twilio/media-stream"
        return f"{base}/twilio/media-stream"

    @computed_field(return_type=bool)
    @property
    def call_transfer_enabled(self) -> bool:
        return bool(self.twilio_transfer_number.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
