from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, load_settings


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    content = (
        "ENV=stage\n"
        "ANTHROPIC_API_KEY=sk-test-123\n"
        "TELEGRAM_BOT_TOKEN=bot-test-456\n"
        "DB_PATH=./data/test.db\n"
        "LOG_LEVEL=DEBUG\n"
    )
    Path(".env.stage").write_text(content)
    return tmp_path


def test_load_settings_reads_env_specific_file(env_file):
    settings = load_settings(env="stage")
    assert settings.env == "stage"
    assert settings.anthropic_api_key == "sk-test-123"
    assert settings.telegram_bot_token == "bot-test-456"
    assert settings.db_path == "./data/test.db"
    assert settings.log_level == "DEBUG"


def test_load_settings_defaults_env_from_ENV_var(env_file, monkeypatch):
    monkeypatch.setenv("ENV", "stage")
    settings = load_settings()
    assert settings.env == "stage"


def test_load_settings_falls_back_to_local_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ENV", raising=False)
    settings = load_settings()
    assert settings.env == "local"
    assert settings.db_path == "./data/local.db"
    assert settings.log_level == "INFO"


def test_invalid_env_value_raises():
    with pytest.raises(ValidationError):
        Settings(env="typo-env")


def test_non_local_env_with_empty_secrets_raises():
    with pytest.raises(ValidationError):
        Settings(env="stage", anthropic_api_key="", telegram_bot_token="")


def test_non_local_env_with_secrets_set_succeeds():
    settings = Settings(
        env="stage",
        anthropic_api_key="sk-ant-real",
        telegram_bot_token="bot-real",
    )
    assert settings.env == "stage"
    assert settings.anthropic_api_key == "sk-ant-real"
    assert settings.telegram_bot_token == "bot-real"
