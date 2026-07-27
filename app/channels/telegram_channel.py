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
