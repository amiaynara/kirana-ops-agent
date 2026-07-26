import os
from pathlib import Path

import pytest

from app.config import load_settings


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    content = (
        "ENV=test\n"
        "ANTHROPIC_API_KEY=sk-test-123\n"
        "TELEGRAM_BOT_TOKEN=bot-test-456\n"
        "DB_PATH=./data/test.db\n"
        "LOG_LEVEL=DEBUG\n"
    )
    Path(".env.test").write_text(content)
    return tmp_path


def test_load_settings_reads_env_specific_file(env_file):
    settings = load_settings(env="test")
    assert settings.env == "test"
    assert settings.anthropic_api_key == "sk-test-123"
    assert settings.telegram_bot_token == "bot-test-456"
    assert settings.db_path == "./data/test.db"
    assert settings.log_level == "DEBUG"


def test_load_settings_defaults_env_from_ENV_var(env_file, monkeypatch):
    monkeypatch.setenv("ENV", "test")
    settings = load_settings()
    assert settings.env == "test"


def test_load_settings_falls_back_to_local_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ENV", raising=False)
    settings = load_settings()
    assert settings.env == "local"
    assert settings.db_path == "./data/local.db"
    assert settings.log_level == "INFO"
