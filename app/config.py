import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    env: str = "local"
    anthropic_api_key: str = ""
    telegram_bot_token: str = ""
    db_path: str = "./data/local.db"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


def load_settings(env: str | None = None) -> Settings:
    env_name = env or os.environ.get("ENV", "local")
    env_file = f".env.{env_name}"
    return Settings(_env_file=env_file, env=env_name)
