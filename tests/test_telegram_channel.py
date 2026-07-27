import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from telegram import Chat, Message, Update
from telegram.ext import filters

from app.agent_session import SendResult
from app.channels.telegram_channel import FALLBACK_REPLY, MAX_REPLY_CHUNK, TelegramChannel


def _make_update(monkeypatch, update_id, text, chat_id=123):
    chat = Chat(id=chat_id, type="private")
    message = Message(message_id=update_id, date=datetime.now(timezone.utc), chat=chat, text=text)
    message.set_bot(MagicMock())  # allow message.reply_text(...) to be called without a live bot
    # Message is a frozen, __slots__-based TelegramObject (PTB 22.x): there is no
    # instance slot for reply_text/reply_document and instances are frozen, so
    # instance-level stubbing (message.reply_text = ...) is impossible. Patch
    # the class methods instead; monkeypatch restores the originals
    # automatically on teardown.
    monkeypatch.setattr(Message, "reply_text", AsyncMock())
    monkeypatch.setattr(Message, "reply_document", AsyncMock())
    return Update(update_id=update_id, message=message), message


def _make_edited_update(monkeypatch, update_id, text, chat_id=123):
    chat = Chat(id=chat_id, type="private")
    message = Message(message_id=update_id, date=datetime.now(timezone.utc), chat=chat, text=text)
    message.set_bot(MagicMock())
    monkeypatch.setattr(Message, "reply_text", AsyncMock())
    return Update(update_id=update_id, edited_message=message), message


def _make_channel(registry, allowed_chat_ids=None):
    # Application.builder().token(...).build() requires a plausible-looking token
    # string but makes no network call at construction time.
    return TelegramChannel(
        bot_token="123456:FAKE-TEST-TOKEN", registry=registry, allowed_chat_ids=allowed_chat_ids,
    )


def test_on_message_replies_with_session_result(tmp_path, monkeypatch):
    registry = MagicMock()
    session = MagicMock()
    session.send = AsyncMock(return_value=SendResult(text="You've got 40 packets of Tata Salt in stock."))
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
    session.send = AsyncMock(return_value=SendResult(text=""))
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


def test_on_message_passes_non_new_slash_text_through_unchanged(tmp_path, monkeypatch):
    # TelegramChannel must NOT special-case "/"-prefixed text itself, except
    # for "/new" (handled separately below, Finding 4) -- everything else is
    # AgentSession.send()'s job (verified in Phase 2). Confirm the raw text
    # (including the leading slash) reaches session.send() untouched.
    registry = MagicMock()
    registry.reset.return_value = None
    session = MagicMock()
    session.send = AsyncMock(return_value=SendResult(text="Some internal diagnostics dump."))
    registry.get_or_create.return_value = session

    channel = _make_channel(registry)
    update, message = _make_update(monkeypatch, update_id=4, text="/help")

    asyncio.run(channel._on_message(update, MagicMock()))

    session.send.assert_awaited_once_with("/help", update_id="4")


# --- Finding 1: edited messages must bypass the handler entirely ---------


def test_text_and_update_type_message_filter_rejects_edited_message(monkeypatch):
    combined_filter = filters.TEXT & filters.UpdateType.MESSAGE

    chat = Chat(id=123, type="private")
    message = Message(message_id=1, date=datetime.now(timezone.utc), chat=chat, text="hello")
    new_update = Update(update_id=1, message=message)
    edited_update = Update(update_id=2, edited_message=message)

    assert combined_filter.check_update(new_update)
    assert not combined_filter.check_update(edited_update)


# --- Finding 2: chat allowlist -------------------------------------------


def test_on_message_processes_message_from_allowed_chat_id(tmp_path, monkeypatch):
    registry = MagicMock()
    session = MagicMock()
    session.send = AsyncMock(return_value=SendResult(text="40 packets of Tata Salt in stock."))
    registry.get_or_create.return_value = session

    channel = _make_channel(registry, allowed_chat_ids={"123"})
    update, message = _make_update(monkeypatch, update_id=5, text="how much salt?", chat_id=123)

    asyncio.run(channel._on_message(update, MagicMock()))

    registry.get_or_create.assert_called_once_with("123")
    message.reply_text.assert_awaited_once_with("40 packets of Tata Salt in stock.")


def test_on_message_silently_drops_message_from_disallowed_chat_id(tmp_path, monkeypatch):
    registry = MagicMock()
    session = MagicMock()
    session.send = AsyncMock(return_value=SendResult(text="should not be reached"))
    registry.get_or_create.return_value = session

    channel = _make_channel(registry, allowed_chat_ids={"999"})
    update, message = _make_update(monkeypatch, update_id=6, text="hi", chat_id=123)

    asyncio.run(channel._on_message(update, MagicMock()))

    registry.get_or_create.assert_not_called()
    message.reply_text.assert_not_awaited()


def test_on_message_with_no_allowlist_processes_any_chat_id(tmp_path, monkeypatch):
    # allowed_chat_ids=None (the default) preserves today's unrestricted
    # behavior for local dev where this isn't configured.
    registry = MagicMock()
    session = MagicMock()
    session.send = AsyncMock(return_value=SendResult(text="ok"))
    registry.get_or_create.return_value = session

    channel = _make_channel(registry, allowed_chat_ids=None)
    update, message = _make_update(monkeypatch, update_id=7, text="hi", chat_id=42424242)

    asyncio.run(channel._on_message(update, MagicMock()))

    registry.get_or_create.assert_called_once_with("42424242")
    message.reply_text.assert_awaited_once_with("ok")


# --- Finding 3: long replies must be chunked, and reply_text must not crash the turn ---


def test_on_message_chunks_long_reply_into_multiple_reply_text_calls(tmp_path, monkeypatch):
    registry = MagicMock()
    session = MagicMock()
    long_reply = "x" * (MAX_REPLY_CHUNK * 2 + 500)
    session.send = AsyncMock(return_value=SendResult(text=long_reply))
    registry.get_or_create.return_value = session

    channel = _make_channel(registry)
    update, message = _make_update(monkeypatch, update_id=8, text="list all products")

    asyncio.run(channel._on_message(update, MagicMock()))

    assert message.reply_text.await_count == 3
    sent_chunks = [call.args[0] for call in message.reply_text.await_args_list]
    assert "".join(sent_chunks) == long_reply
    assert all(len(chunk) <= MAX_REPLY_CHUNK for chunk in sent_chunks)


def test_on_message_swallows_reply_text_failure_without_raising(tmp_path, monkeypatch):
    registry = MagicMock()
    session = MagicMock()
    session.send = AsyncMock(return_value=SendResult(text="a normal reply"))
    registry.get_or_create.return_value = session

    channel = _make_channel(registry)
    update, message = _make_update(monkeypatch, update_id=9, text="hi")
    # Message is frozen (see _make_update's note above) -- patch the class
    # method, not the instance, to make this particular call raise.
    monkeypatch.setattr(Message, "reply_text", AsyncMock(side_effect=RuntimeError("message too long")))

    # Must not raise even though reply_text blows up.
    asyncio.run(channel._on_message(update, MagicMock()))

    message.reply_text.assert_awaited_once()


# --- Finding 4: "/new" must re-read preferences into a brand-new session ---


def test_on_message_new_resets_registry_session_before_replying(tmp_path, monkeypatch):
    registry = MagicMock()
    stale_session = MagicMock()
    stale_session.close = AsyncMock()
    registry.reset.return_value = stale_session
    fresh_session = MagicMock()
    registry.get_or_create.return_value = fresh_session

    channel = _make_channel(registry)
    update, message = _make_update(monkeypatch, update_id=10, text="/new")

    asyncio.run(channel._on_message(update, MagicMock()))

    registry.reset.assert_called_once_with("123")
    stale_session.close.assert_awaited_once()
    registry.get_or_create.assert_called_once_with("123")
    message.reply_text.assert_awaited_once_with("Started a fresh conversation.")


def test_on_message_new_with_no_cached_session_does_not_await_close(tmp_path, monkeypatch):
    registry = MagicMock()
    registry.reset.return_value = None
    fresh_session = MagicMock()
    registry.get_or_create.return_value = fresh_session

    channel = _make_channel(registry)
    update, message = _make_update(monkeypatch, update_id=11, text="  /NeW  ")

    asyncio.run(channel._on_message(update, MagicMock()))

    registry.reset.assert_called_once_with("123")
    registry.get_or_create.assert_called_once_with("123")
    message.reply_text.assert_awaited_once_with("Started a fresh conversation.")


def test_new_causes_subsequent_get_or_create_to_see_freshly_read_preferences(tmp_path):
    # Full-stack version (no channel involved): confirms the registry-level
    # contract that Finding 4 depends on -- after reset(), get_or_create()
    # builds a brand-new AgentSession, which re-reads preferences from the DB
    # at construction time rather than reusing a stale snapshot.
    from app.db import Base, make_engine, make_session_factory
    from app.services.preferences import PreferencesService
    from app.session_registry import SessionRegistry

    engine = make_engine(str(tmp_path / "new_prefs.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    prefs = PreferencesService(session_factory)

    registry = SessionRegistry(session_factory=session_factory)
    first_session = registry.get_or_create("chat-1")
    assert "No standing preferences set yet." in first_session._options.system_prompt

    prefs.set_preference(key="default_payment_mode", value="upi")
    popped = registry.reset("chat-1")
    assert popped is first_session

    second_session = registry.get_or_create("chat-1")
    assert second_session is not first_session
    assert "default_payment_mode: upi" in second_session._options.system_prompt


# --- Task 5: artifact delivery over Telegram -----------------------------


def test_on_message_sends_artifact_as_telegram_document(tmp_path, monkeypatch):
    from app.tools.artifact_context import ArtifactPayload

    registry = MagicMock()
    session = MagicMock()
    session.send = AsyncMock(return_value=SendResult(
        text="Here's your invoice.",
        artifact=ArtifactPayload(data=b"%PDF-fake", filename="invoice-1.pdf", mime_type="application/pdf"),
    ))
    registry.get_or_create.return_value = session

    channel = _make_channel(registry)
    update, message = _make_update(monkeypatch, update_id=5, text="send me the invoice")

    asyncio.run(channel._on_message(update, MagicMock()))

    message.reply_text.assert_awaited_once_with("Here's your invoice.")
    message.reply_document.assert_awaited_once()
    _, kwargs = message.reply_document.await_args
    assert kwargs["filename"] == "invoice-1.pdf"
