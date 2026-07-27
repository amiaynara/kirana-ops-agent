import asyncio

from app.channels.cli_channel import CLIChannel
from app.config import load_settings
from app.db import init_db, make_session_factory


def main():
    settings = load_settings()
    engine = init_db(settings)
    session_factory = make_session_factory(engine)
    channel = CLIChannel(
        chat_id="local", session_factory=session_factory,
        anthropic_api_key=settings.anthropic_api_key or None,
    )
    asyncio.run(channel.run())


if __name__ == "__main__":
    main()
