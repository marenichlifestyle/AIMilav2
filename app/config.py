from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


def _to_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@dataclass(slots=True)
class Settings:
    app_host: str
    app_port: int
    database_url: str
    openai_api_key: str
    openai_model: str
    openai_transcribe_model: str
    supabase_url: str
    supabase_service_role_key: str
    chatapp_default_license_id: str
    chatapp_default_messenger: str
    chatapp_token_table: str
    chatapp_cars_table: str
    telegram_bot_token: str
    telegram_manager_chat_id: str
    webhook_path: str
    log_level: str
    processing_delay_seconds: int
    max_media_mb: int

    @property
    def max_media_bytes(self) -> int:
        return self.max_media_mb * 1024 * 1024


def get_settings() -> Settings:
    webhook_path = os.getenv("WEBHOOK_PATH", "/webhook/chatapp").strip() or "/webhook/chatapp"
    if not webhook_path.startswith("/"):
        webhook_path = f"/{webhook_path}"

    database_url = _normalize_database_url(
        os.getenv("DATABASE_URL", "postgresql://app:app_password@postgres:5432/chatapp_ai")
    )

    return Settings(
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=_to_int("APP_PORT", 8000),
        database_url=database_url,
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
        openai_transcribe_model=os.getenv("OPENAI_TRANSCRIBE_MODEL", "whisper-1"),
        supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
        supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
        chatapp_default_license_id=os.getenv("CHATAPP_DEFAULT_LICENSE_ID", "68179"),
        chatapp_default_messenger=os.getenv("CHATAPP_DEFAULT_MESSENGER", "telegram"),
        chatapp_token_table=os.getenv("CHATAPP_TOKEN_TABLE", "ChatApp Token"),
        chatapp_cars_table=os.getenv("CHATAPP_CARS_TABLE", "CMExpert"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_manager_chat_id=os.getenv("TELEGRAM_MANAGER_CHAT_ID", "-4629820633"),
        webhook_path=webhook_path,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        processing_delay_seconds=_to_int("PROCESSING_DELAY_SECONDS", 12),
        max_media_mb=_to_int("MAX_MEDIA_MB", 20),
    )


settings = get_settings()
