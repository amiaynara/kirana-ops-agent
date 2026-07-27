from app.channels.cli_channel import CLIChannel
from app.db import Base, make_engine, make_session_factory


def test_cli_channel_constructs_an_agent_session(tmp_path):
    engine = make_engine(str(tmp_path / "cli.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    channel = CLIChannel(chat_id="local", session_factory=session_factory)

    assert channel._session.chat_id == "local"
