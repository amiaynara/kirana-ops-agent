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
