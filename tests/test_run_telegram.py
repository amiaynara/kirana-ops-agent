import pytest

from app.run_telegram import build_channel
from app.config import Settings


def test_build_channel_raises_clear_error_without_bot_token(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(env="local", db_path=str(tmp_path / "run_telegram.db"), telegram_bot_token="")
    with pytest.raises(SystemExit, match="TELEGRAM_BOT_TOKEN"):
        build_channel(settings)


def test_build_channel_constructs_with_bot_token(tmp_path):
    settings = Settings(
        env="local", db_path=str(tmp_path / "run_telegram.db"),
        telegram_bot_token="123456:FAKE-TEST-TOKEN",
    )
    channel = build_channel(settings)
    assert channel is not None
