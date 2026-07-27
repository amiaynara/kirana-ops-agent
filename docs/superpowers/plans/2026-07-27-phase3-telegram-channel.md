# Phase 3 — Telegram Channel Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the same `AgentSession` core from Phase 2 to real Telegram, via `python-telegram-bot`, with per-chat session lifecycle management — the one genuine gap Phase 2's whole-branch review flagged (no multi-session manager existed yet).

**Architecture:** A `SessionRegistry` lazily creates and caches one `AgentSession` per Telegram `chat_id` (a dict; acceptable at this project's explicitly single-owner/single-shop scale — see design spec §1 non-goals — a race on first-message-from-a-brand-new-chat is possible but not data-corrupting, since the DB's own `BEGIN IMMEDIATE` protects data integrity regardless of which `AgentSession` instance issues the call). `TelegramChannel` registers exactly one generic `MessageHandler(filters.TEXT, ...)` — deliberately NO `CommandHandler` for anything, including `/new` — so slash-prefixed text (including `/new`) reaches our handler as plain text unchanged, and `AgentSession.send()` (already built and tested in Phase 2) handles the `/new` reset and the leading-slash escaping itself. `Update.update_id` passes straight through as `AgentSession.send()`'s `update_id`, which `finalize_bill` uses for idempotency — this is the same mechanism already proven in Phase 1/2, just fed from a real source now instead of a CLI-generated UUID.

**Tech Stack:** `python-telegram-bot` (verified installed version 22.8), long polling (`Application.run_polling()`) — no public webhook needed, simpler than managing inbound HTTPS for a take-home.

## Global Constraints

- Python >= 3.11 (unchanged)
- No `CommandHandler` registered for anything — a single `MessageHandler(filters.TEXT, ...)` must handle all text, `/`-prefixed or not, so `AgentSession`'s own slash-handling logic (verified in Phase 2) is the single source of truth for command-like text, not duplicated at the Telegram layer
- `Update.update_id` (stringified) is the idempotency key passed to `AgentSession.send(update_id=...)` — never a fresh UUID like the CLI channel used, since Telegram's own redelivery semantics are exactly what `finalize_bill`'s idempotency guard exists to handle
- A reply must never be sent as empty text — Telegram's `sendMessage` API rejects empty `text` with an HTTP 400, so any falsy reply from `AgentSession.send()` needs a fallback string
- Any exception from `AgentSession.send()` must be caught at the channel layer and turned into a plain-language reply — it must never crash the bot process or leave an update silently unanswered
- No placeholder/TODO code

## Verified Behavior (confirmed by live testing before this plan was written)

- `python-telegram-bot==22.8`. `telegram.Update`/`telegram.Message`/`telegram.Chat` can be constructed directly in tests without a live bot connection or network access — confirmed by constructing a real `Update` object and reading back `update_id`, `effective_chat.id`, `effective_message.text`.
- `filters.TEXT.check_update(update)` returns `True` for a message whose `text` starts with `/`, exactly the same as ordinary text — confirmed live. `filters.COMMAND` is a separate, independent filter; since this plan registers no `CommandHandler` at all and doesn't gate the `MessageHandler` on `~filters.COMMAND`, slash-prefixed text reaches our handler unmodified regardless of whether Telegram's servers additionally attach a `bot_command` message entity to it (which real Telegram delivery does for `/`-prefixed text, unlike the manually-constructed test objects used above).

---

### Task 1: `python-telegram-bot` dependency + `SessionRegistry`

**Files:**
- Modify: `pyproject.toml` (add dependency)
- Create: `app/session_registry.py`
- Test: `tests/test_session_registry.py`

**Interfaces:**
- Consumes: `AgentSession` from `app.agent_session`
- Produces: `SessionRegistry(session_factory, anthropic_api_key=None, model=None)` with `get_or_create(chat_id: str) -> AgentSession` (returns the same instance for the same `chat_id` on repeated calls, a fresh one for a new `chat_id`) and `async close_all() -> None`

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`'s `dependencies` list, add:
```toml
    "python-telegram-bot>=22.8,<23.0",
```
Run: `pip install -e ".[dev]"` to confirm it resolves cleanly (already installed in this venv from manual verification).

- [ ] **Step 2: Write the failing test**

`tests/test_session_registry.py`:
```python
from app.db import Base, make_engine, make_session_factory
from app.session_registry import SessionRegistry


def _make_registry(tmp_path):
    engine = make_engine(str(tmp_path / "registry.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    return SessionRegistry(session_factory=session_factory)


def test_get_or_create_returns_same_session_for_same_chat_id(tmp_path):
    registry = _make_registry(tmp_path)
    first = registry.get_or_create("chat-1")
    second = registry.get_or_create("chat-1")
    assert first is second


def test_get_or_create_returns_different_sessions_for_different_chat_ids(tmp_path):
    registry = _make_registry(tmp_path)
    chat_1 = registry.get_or_create("chat-1")
    chat_2 = registry.get_or_create("chat-2")
    assert chat_1 is not chat_2
    assert chat_1.chat_id == "chat-1"
    assert chat_2.chat_id == "chat-2"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_session_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.session_registry'`

- [ ] **Step 4: Write minimal implementation**

`app/session_registry.py`:
```python
from app.agent_session import AgentSession


class SessionRegistry:
    def __init__(self, *, session_factory, anthropic_api_key: str | None = None,
                 model: str | None = None):
        self._session_factory = session_factory
        self._anthropic_api_key = anthropic_api_key
        self._model = model
        self._sessions: dict[str, AgentSession] = {}

    def get_or_create(self, chat_id: str) -> AgentSession:
        session = self._sessions.get(chat_id)
        if session is None:
            session = AgentSession(
                chat_id=chat_id,
                session_factory=self._session_factory,
                model=self._model,
                anthropic_api_key=self._anthropic_api_key,
            )
            self._sessions[chat_id] = session
        return session

    async def close_all(self):
        for session in self._sessions.values():
            await session.close()
```

- [ ] **Step 5: Run test to verify it passes, then full suite**

Run: `pytest tests/test_session_registry.py -v` — expect 2 passed
Run: `pytest -v` — expect 135 passed (133 from Phase 2 + 2 new)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml app/session_registry.py tests/test_session_registry.py
git commit -m "feat: add python-telegram-bot dependency and per-chat SessionRegistry"
```

---

### Task 2: `TelegramChannel`

**Files:**
- Create: `app/channels/telegram_channel.py`
- Test: `tests/test_telegram_channel.py`

**Interfaces:**
- Consumes: `SessionRegistry` from `app.session_registry`; `Update`, `Message`, `Chat` from `telegram`; `Application`, `MessageHandler`, `filters`, `ContextTypes` from `telegram.ext`
- Produces: `TelegramChannel(bot_token: str, registry: SessionRegistry)` with an internal `_on_message(update, context)` handler (tested directly, without a live bot connection — `Update`/`Message`/`Chat` are constructed in-test) and `run() -> None` (starts long polling, not covered by the automated suite — see Step 6)

- [ ] **Step 1: Write the failing test**

`tests/test_telegram_channel.py`:
```python
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from telegram import Chat, Message, Update

from app.channels.telegram_channel import FALLBACK_REPLY, TelegramChannel


def _make_update(update_id, text, chat_id=123):
    chat = Chat(id=chat_id, type="private")
    message = Message(message_id=update_id, date=datetime.now(timezone.utc), chat=chat, text=text)
    message.set_bot(MagicMock())  # allow message.reply_text(...) to be called without a live bot
    message.reply_text = AsyncMock()
    return Update(update_id=update_id, message=message), message


def _make_channel(registry):
    # Application.builder().token(...).build() requires a plausible-looking token
    # string but makes no network call at construction time.
    return TelegramChannel(bot_token="123456:FAKE-TEST-TOKEN", registry=registry)


def test_on_message_replies_with_session_result(tmp_path):
    registry = MagicMock()
    session = MagicMock()
    session.send = AsyncMock(return_value="You've got 40 packets of Tata Salt in stock.")
    registry.get_or_create.return_value = session

    channel = _make_channel(registry)
    update, message = _make_update(update_id=1, text="how much tata salt is left?")

    asyncio.run(channel._on_message(update, MagicMock()))

    registry.get_or_create.assert_called_once_with("123")
    session.send.assert_awaited_once_with("how much tata salt is left?", update_id="1")
    message.reply_text.assert_awaited_once_with("You've got 40 packets of Tata Salt in stock.")


def test_on_message_falls_back_on_empty_reply(tmp_path):
    registry = MagicMock()
    session = MagicMock()
    session.send = AsyncMock(return_value="")
    registry.get_or_create.return_value = session

    channel = _make_channel(registry)
    update, message = _make_update(update_id=2, text="hello")

    asyncio.run(channel._on_message(update, MagicMock()))

    message.reply_text.assert_awaited_once_with(FALLBACK_REPLY)


def test_on_message_replies_gracefully_on_exception(tmp_path):
    registry = MagicMock()
    session = MagicMock()
    session.send = AsyncMock(side_effect=RuntimeError("boom"))
    registry.get_or_create.return_value = session

    channel = _make_channel(registry)
    update, message = _make_update(update_id=3, text="finalize the bill")

    asyncio.run(channel._on_message(update, MagicMock()))

    message.reply_text.assert_awaited_once()
    (reply_text,), _ = message.reply_text.await_args
    assert "went wrong" in reply_text.lower()


def test_on_message_passes_slash_text_through_unchanged(tmp_path):
    # TelegramChannel must NOT special-case "/"-prefixed text itself -- that's
    # AgentSession.send()'s job (verified in Phase 2). Confirm the raw text
    # (including the leading slash) reaches session.send() untouched.
    registry = MagicMock()
    session = MagicMock()
    session.send = AsyncMock(return_value="Started a fresh conversation.")
    registry.get_or_create.return_value = session

    channel = _make_channel(registry)
    update, message = _make_update(update_id=4, text="/new")

    asyncio.run(channel._on_message(update, MagicMock()))

    session.send.assert_awaited_once_with("/new", update_id="4")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_telegram_channel.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.channels.telegram_channel'`

- [ ] **Step 3: Write minimal implementation**

`app/channels/telegram_channel.py`:
```python
import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from app.session_registry import SessionRegistry

logger = logging.getLogger(__name__)

FALLBACK_REPLY = "Sorry, I didn't get a reply for that -- try again?"


class TelegramChannel:
    def __init__(self, *, bot_token: str, registry: SessionRegistry):
        self._registry = registry
        self._app = Application.builder().token(bot_token).build()
        # Deliberately no CommandHandler for anything, including "/new" --
        # AgentSession.send() already handles slash-prefixed text (reset on
        # "/new", escape-as-literal-text otherwise), verified live in Phase 2.
        # Registering a CommandHandler here would intercept that text before
        # it ever reached AgentSession, duplicating and potentially
        # contradicting that logic.
        self._app.add_handler(MessageHandler(filters.TEXT, self._on_message))

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None or message.text is None:
            return
        chat_id = str(update.effective_chat.id)
        session = self._registry.get_or_create(chat_id)
        try:
            reply = await session.send(message.text, update_id=str(update.update_id))
        except Exception:
            logger.exception(
                "AgentSession.send failed for chat_id=%s update_id=%s", chat_id, update.update_id,
            )
            reply = "Something went wrong on my end -- please try again in a moment."
        await message.reply_text(reply or FALLBACK_REPLY)

    def run(self) -> None:
        self._app.run_polling()
```

- [ ] **Step 4: Run test to verify it passes, then full suite**

Run: `pytest tests/test_telegram_channel.py -v` — expect 4 passed
Run: `pytest -v` — expect 139 passed

- [ ] **Step 5: Commit**

```bash
git add app/channels/telegram_channel.py tests/test_telegram_channel.py
git commit -m "feat: add TelegramChannel wrapping AgentSession via SessionRegistry"
```

- [ ] **Step 6: Manual live verification (requires a real Telegram bot token from BotFather — not part of the automated suite)**

This step needs a real bot token the automated tests can't provide. Once available:
1. Message @BotFather on Telegram, `/newbot`, follow the prompts, get a token like `123456789:AAG...`.
2. Set `TELEGRAM_BOT_TOKEN=<token>` in `.env.local`.
3. Run the bot (Task 3's entrypoint) and message it directly, driving at least: a stock query, a multi-item bill with an edit, an oversell attempt, a khata cycle, `/new` followed by confirming a previously-set preference still applies. Record what happened in the task report — this is the brief's own required scenario pass (§3 table) over real Telegram.

---

### Task 3: Telegram bot entrypoint

**Files:**
- Create: `app/run_telegram.py`
- Test: `tests/test_run_telegram.py` (construction-only sanity — no live bot connection)

**Interfaces:**
- Consumes: `load_settings` from `app.config`; `init_db`, `make_session_factory` from `app.db`; `SessionRegistry` from `app.session_registry`; `TelegramChannel` from `app.channels.telegram_channel`
- Produces: `main()` as the `python -m app.run_telegram` entrypoint; raises `SystemExit` with a clear message if `TELEGRAM_BOT_TOKEN` isn't configured

- [ ] **Step 1: Write the failing test**

`tests/test_run_telegram.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_telegram.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.run_telegram'`

- [ ] **Step 3: Write minimal implementation**

`app/run_telegram.py`:
```python
from app.channels.telegram_channel import TelegramChannel
from app.config import Settings, load_settings
from app.db import init_db, make_session_factory
from app.session_registry import SessionRegistry


def build_channel(settings: Settings) -> TelegramChannel:
    if not settings.telegram_bot_token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set -- get one from @BotFather on Telegram and set it "
            "in .env.local (see .env.example)."
        )
    engine = init_db(settings)
    session_factory = make_session_factory(engine)
    registry = SessionRegistry(
        session_factory=session_factory,
        anthropic_api_key=settings.anthropic_api_key or None,
    )
    return TelegramChannel(bot_token=settings.telegram_bot_token, registry=registry)


def main():
    settings = load_settings()
    channel = build_channel(settings)
    channel.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes, then full suite**

Run: `pytest tests/test_run_telegram.py -v` — expect 2 passed
Run: `pytest -v` — expect 141 passed

- [ ] **Step 5: Commit**

```bash
git add app/run_telegram.py tests/test_run_telegram.py
git commit -m "feat: add python -m app.run_telegram entrypoint"
```
