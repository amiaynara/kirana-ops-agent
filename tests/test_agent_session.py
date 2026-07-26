from app.agent_session import AgentSession
from app.db import Base, make_engine, make_session_factory


def test_agent_session_constructs_with_all_tool_domains_registered(tmp_path):
    engine = make_engine(str(tmp_path / "session.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    session = AgentSession(chat_id="test-chat", session_factory=session_factory)

    tool_names = {t.name for t in session._all_tools}
    assert tool_names == {
        "get_stock", "list_low_stock", "list_products", "receive_stock", "create_product",
        "start_bill", "add_bill_item", "update_bill_item", "drop_bill_item",
        "get_bill_draft", "cancel_bill", "finalize_bill",
        "credit_customer", "settle_khata", "get_khata_balance",
        "set_preference", "get_preference",
    }
    assert session._options.tools == ["Skill"]
    assert session._options.strict_mcp_config is True
    assert session._options.permission_mode == "bypassPermissions"
    assert session.chat_id == "test-chat"


def test_agent_session_injects_existing_preferences_into_system_prompt(tmp_path):
    from app.services.preferences import PreferencesService

    engine = make_engine(str(tmp_path / "session_prefs.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    PreferencesService(session_factory).set_preference(key="default_payment_mode", value="upi")

    session = AgentSession(chat_id="test-chat", session_factory=session_factory)

    assert "default_payment_mode: upi" in session._options.system_prompt
