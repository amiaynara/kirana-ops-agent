import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from app.agent_session import SendResult
from app.channels.cli_channel import CLIChannel
from app.db import Base, make_engine, make_session_factory
from app.tools.artifact_context import ArtifactPayload


def test_cli_channel_constructs_an_agent_session(tmp_path):
    engine = make_engine(str(tmp_path / "cli.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    channel = CLIChannel(chat_id="local", session_factory=session_factory)

    assert channel._session.chat_id == "local"


def test_cli_channel_passes_anthropic_api_key_through_to_agent_session(tmp_path):
    engine = make_engine(str(tmp_path / "cli_key.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    channel = CLIChannel(chat_id="local", session_factory=session_factory, anthropic_api_key="sk-test-123")

    assert channel._session._options.env == {"ANTHROPIC_API_KEY": "sk-test-123"}


def test_cli_channel_leaves_env_empty_without_an_api_key(tmp_path):
    engine = make_engine(str(tmp_path / "cli_no_key.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    channel = CLIChannel(chat_id="local", session_factory=session_factory)

    assert channel._session._options.env == {}


def test_cli_channel_writes_artifact_to_disk_and_reports_path(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    engine = make_engine(str(tmp_path / "cli_artifact.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    channel = CLIChannel(chat_id="local", session_factory=session_factory)
    channel._session.send = AsyncMock(return_value=SendResult(
        text="Here's your invoice.",
        artifacts=[ArtifactPayload(data=b"%PDF-fake", filename="invoice-1.pdf", mime_type="application/pdf")],
    ))
    channel._session.close = AsyncMock()

    inputs = iter(["send me the invoice", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    asyncio.run(channel.run())

    saved_path = Path("data/artifacts/invoice-1.pdf")
    assert saved_path.exists()
    assert saved_path.read_bytes() == b"%PDF-fake"
    captured = capsys.readouterr()
    assert "invoice-1.pdf" in captured.out
    assert "kirana> Here's your invoice." in captured.out
    assert "SendResult(" not in captured.out
