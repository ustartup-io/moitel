"""Single source of truth for runtime configuration (pydantic-settings).

Required env: BOT_TOKEN, ADMIN_CHAT_ID, LANDING_URL.
Everything else has a safe MVP default. Cross-field hardening (payments /
webhook keys) is enforced only in prod via Settings.fail_fast_prod().
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root (repo dir). Works for source layout + editable installs.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEXTS_DIR = PROJECT_ROOT / "texts"


class Settings(BaseSettings):
    """Typed settings loaded from environment (and optional .env file)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- core (required) ---
    bot_token: SecretStr
    admin_chat_id: int
    landing_url: str

    # --- core (with defaults) ---
    database_url: str = "sqlite+aiosqlite:///./bot.db"
    environment: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"
    default_lang: str = "en"

    # --- payments (optional) ---
    payments_enabled: bool = False
    xrocket_api_key: SecretStr | None = None
    xrocket_base_url: str = "https://pay.xrocket.tg/"
    xrocket_mode: Literal["testnet", "live"] = "testnet"

    # --- webhook (optional) ---
    webhook_enabled: bool = False
    webhook_secret: SecretStr | None = None
    webhook_base_url: str | None = None

    @field_validator("default_lang")
    @classmethod
    def _validate_default_lang(cls, v: str) -> str:
        if v not in ("en", "ru"):
            raise ValueError("DEFAULT_LANG must be 'en' or 'ru'")
        return v

    def fail_fast_prod(self) -> None:
        """Extra cross-field validation, enforced only when ENVIRONMENT=prod.

        BOT_TOKEN is already required by the type system; here we make sure that
        optional-but-sensitive subsystems carry their secrets when enabled.
        """
        if self.environment != "prod":
            return
        missing: list[str] = []
        if not self.bot_token.get_secret_value():
            missing.append("BOT_TOKEN")
        if self.payments_enabled and not _secret_set(self.xrocket_api_key):
            missing.append("XROCKET_API_KEY (required when PAYMENTS_ENABLED=true)")
        if self.webhook_enabled:
            if not self.webhook_base_url:
                missing.append("WEBHOOK_BASE_URL (required when WEBHOOK_ENABLED=true)")
            if not _secret_set(self.webhook_secret):
                missing.append("WEBHOOK_SECRET (required when WEBHOOK_ENABLED=true)")
        if missing:
            raise RuntimeError("Missing required settings in prod: " + ", ".join(missing))


def _secret_set(secret: SecretStr | None) -> bool:
    return secret is not None and bool(secret.get_secret_value())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton Settings, after prod hardening checks."""
    settings = Settings()
    settings.fail_fast_prod()
    return settings
