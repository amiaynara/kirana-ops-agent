import os
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    env: Literal["local", "stage", "prod"] = "local"
    anthropic_api_key: str = ""
    telegram_bot_token: str = ""
    db_path: str = "./data/local.db"
    log_level: str = "INFO"
    # Comma-separated allowlist of Telegram chat IDs (env vars are strings,
    # so this stays a str here and gets parsed/split by the caller). Empty
    # string means "no restriction configured" -- fine for local/dev, but a
    # real deployment must set this or any stranger who finds the bot's
    # username gets full read/write access to the shop's data.
    allowed_telegram_chat_ids: str = ""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def _require_secrets_outside_local(self) -> "Settings":
        if self.env != "local" and (not self.anthropic_api_key or not self.telegram_bot_token):
            raise ValueError(
                f"anthropic_api_key and telegram_bot_token must be set when env={self.env!r}"
            )
        return self


def load_settings(env: str | None = None) -> Settings:
    env_name = env or os.environ.get("ENV", "local")
    env_file = f".env.{env_name}"
    return Settings(_env_file=env_file, env=env_name)
