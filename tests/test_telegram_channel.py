import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from telegram import Chat, Message, Update

from app.channels.telegram_channel import FALLBACK_REPLY, TelegramChannel


def _make_update(monkeypatch, update_id, text, chat_id=123):
    chat = Chat(id=chat_id, type="private")
    message = Message(message_id=update_id, date=datetime.now(timezone.utc), chat=chat, text=text)
    message.set_bot(MagicMock())  # allow message.reply_text(...) to be called without a live bot
    # Message is a frozen, __slots__-based TelegramObject (PTB 22.x): there is no
    # instance slot for reply_text and instances are frozen, so instance-level
    # stubbing (message.reply_text = ...) is impossible. Patch the class method
    # instead; monkeypatch restores the original automatically on teardown.
    monkeypatch.setattr(Message, "reply_text", AsyncMock())
    return Update(update_id=update_id, message=message), message


def _make_channel(registry):
    # Application.builder().token(...).build() requires a plausible-looking token
    # string but makes no network call at construction time.
    return TelegramChannel(bot_token="123456:FAKE-TEST-TOKEN", registry=registry)


def test_on_message_replies_with_session_result(tmp_path, monkeypatch):
    registry = MagicMock()
    session = MagicMock()
    session.send = AsyncMock(return_value="You've got 40 packets of Tata Salt in stock.")
    registry.get_or_create.return_value = session

    channel = _make_channel(registry)
    update, message = _make_update(monkeypatch, update_id=1, text="how much tata salt is left?")

    asyncio.run(channel._on_message(update, MagicMock()))

    registry.get_or_create.assert_called_once_with("123")
    session.send.assert_awaited_once_with("how much tata salt is left?", update_id="1")
    message.reply_text.assert_awaited_once_with("You've got 40 packets of Tata Salt in stock.")


def test_on_message_falls_back_on_empty_reply(tmp_path, monkeypatch):
    registry = MagicMock()
    session = MagicMock()
    session.send = AsyncMock(return_value="")
    registry.get_or_create.return_value = session

    channel = _make_channel(registry)
    update, message = _make_update(monkeypatch, update_id=2, text="hello")

    asyncio.run(channel._on_message(update, MagicMock()))

    message.reply_text.assert_awaited_once_with(FALLBACK_REPLY)


def test_on_message_replies_gracefully_on_exception(tmp_path, monkeypatch):
    registry = MagicMock()
    session = MagicMock()
    session.send = AsyncMock(side_effect=RuntimeError("boom"))
    registry.get_or_create.return_value = session

    channel = _make_channel(registry)
    update, message = _make_update(monkeypatch, update_id=3, text="finalize the bill")

    asyncio.run(channel._on_message(update, MagicMock()))

    message.reply_text.assert_awaited_once()
    (reply_text,), _ = message.reply_text.await_args
    assert "went wrong" in reply_text.lower()


def test_on_message_passes_slash_text_through_unchanged(tmp_path, monkeypatch):
    # TelegramChannel must NOT special-case "/"-prefixed text itself -- that's
    # AgentSession.send()'s job (verified in Phase 2). Confirm the raw text
    # (including the leading slash) reaches session.send() untouched.
    registry = MagicMock()
    session = MagicMock()
    session.send = AsyncMock(return_value="Started a fresh conversation.")
    registry.get_or_create.return_value = session

    channel = _make_channel(registry)
    update, message = _make_update(monkeypatch, update_id=4, text="/new")

    asyncio.run(channel._on_message(update, MagicMock()))

    session.send.assert_awaited_once_with("/new", update_id="4")
