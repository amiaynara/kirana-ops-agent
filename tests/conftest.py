import pytest

# Every env var backed by app.config.Settings. pydantic-settings ranks real
# process env vars above the `.env.<env>` file, so if any of these happen to
# be exported on the machine running the tests, they silently override the
# values tests set up via fixtures/.env files, causing non-deterministic
# failures. Strip them before every test, repo-wide (Phase 1+ tests need the
# same isolation).
_SETTINGS_ENV_VARS = [
    "ENV",
    "ANTHROPIC_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "DB_PATH",
    "LOG_LEVEL",
]


@pytest.fixture(autouse=True)
def _isolate_settings_env(monkeypatch):
    for var in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
