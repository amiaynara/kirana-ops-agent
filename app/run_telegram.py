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
    allowed_chat_ids = {
        chat_id.strip()
        for chat_id in settings.allowed_telegram_chat_ids.split(",")
        if chat_id.strip()
    }
    return TelegramChannel(
        bot_token=settings.telegram_bot_token,
        registry=registry,
        allowed_chat_ids=allowed_chat_ids or None,
    )


def main():
    settings = load_settings()
    channel = build_channel(settings)
    channel.run()


if __name__ == "__main__":
    main()
