import io
import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from app.session_registry import SessionRegistry

logger = logging.getLogger(__name__)

FALLBACK_REPLY = "Sorry, I didn't get a reply for that -- try again?"

# Telegram messages are capped at 4096 characters and python-telegram-bot
# does not auto-split. Leave headroom below the hard limit.
MAX_REPLY_CHUNK = 4000


class TelegramChannel:
    def __init__(
        self,
        *,
        bot_token: str,
        registry: SessionRegistry,
        allowed_chat_ids: set[str] | None = None,
    ):
        self._registry = registry
        self._allowed_chat_ids = allowed_chat_ids
        self._app = Application.builder().token(bot_token).build()
        # Deliberately no CommandHandler for anything, including "/new" --
        # AgentSession.send() already handles slash-prefixed text (reset on
        # "/new", escape-as-literal-text otherwise), verified live in Phase 2.
        # Registering a CommandHandler here would intercept that text before
        # it ever reached AgentSession, duplicating and potentially
        # contradicting that logic.
        #
        # filters.TEXT alone matches edited_message/channel_post/
        # edited_channel_post too (PTB's BaseFilter.check_update returns True
        # for all of these against a plain content filter) -- an edited
        # message arrives with a brand-new update_id, so without this it
        # would be processed as an entirely new instruction with a fresh
        # idempotency key, silently double-applying stock receipts/khata
        # credits that have no dedup guard of their own. Restrict to
        # genuinely new messages only.
        self._app.add_handler(
            MessageHandler(filters.TEXT & filters.UpdateType.MESSAGE, self._on_message)
        )

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None or message.text is None:
            return
        chat_id = str(update.effective_chat.id)
        if self._allowed_chat_ids is not None and chat_id not in self._allowed_chat_ids:
            # Silently ignore -- don't reply, even with a refusal, so a
            # stranger probing the bot's username can't confirm it exists.
            logger.warning("Ignoring message from unrecognized chat_id=%s", chat_id)
            return

        text = message.text
        if text.strip().lower() == "/new":
            # Special-cased here (mirroring the check inside
            # AgentSession.send()) so a fresh AgentSession -- with
            # preferences re-read from the DB at construction time -- gets
            # built, rather than reusing the cached session's stale,
            # construction-time preference snapshot for the lifetime of the
            # process.
            popped = self._registry.reset(chat_id)
            if popped is not None:
                try:
                    await popped.close()
                except Exception:
                    pass
            self._registry.get_or_create(chat_id)
            await self._send_reply(message, "Started a fresh conversation.")
            return

        session = self._registry.get_or_create(chat_id)
        try:
            result = await session.send(text, update_id=str(update.update_id))
        except Exception:
            logger.exception(
                "AgentSession.send failed for chat_id=%s update_id=%s", chat_id, update.update_id,
            )
            await self._send_reply(message, "Something went wrong on my end -- please try again in a moment.")
            return
        await self._send_reply(message, result.text or FALLBACK_REPLY)
        if result.artifact is not None:
            try:
                await message.reply_document(
                    document=io.BytesIO(result.artifact.data),
                    filename=result.artifact.filename,
                )
            except Exception:
                logger.exception("reply_document failed while sending artifact")
                await self._send_reply(
                    message, "I generated the file but couldn't send it -- try asking again."
                )

    async def _send_reply(self, message, text: str) -> None:
        chunks = [text[i : i + MAX_REPLY_CHUNK] for i in range(0, len(text), MAX_REPLY_CHUNK)]
        for chunk in chunks:
            try:
                await message.reply_text(chunk)
            except Exception:
                logger.exception("reply_text failed while sending a chunk")

    def run(self) -> None:
        self._app.run_polling()
