import asyncio

from mcp import types as mcp_types

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

    # Options that make Skills actually discoverable/usable -- a regression
    # here fails open (skills silently become undiscoverable, no crash).
    assert session._options.setting_sources == ["project"]
    assert session._options.skills == "all"
    assert session._options.cwd == str(session._options.cwd)  # sanity: it's set to something
    assert session._options.max_turns == 20

    # Confirm all 17 tools actually made it into the MCP server config (not
    # just into `_all_tools`). `McpSdkServerConfig["instance"]` is a private
    # mcp.server.lowlevel.server.Server; its registered list_tools handler is
    # the only way to introspect what Claude will actually see, so we invoke
    # it directly via the low-level mcp request/response types.
    mcp_server = session._options.mcp_servers["kirana"]["instance"]
    list_tools_handler = mcp_server.request_handlers[mcp_types.ListToolsRequest]
    list_tools_result = asyncio.run(
        list_tools_handler(mcp_types.ListToolsRequest(method="tools/list"))
    )
    assert len(list_tools_result.root.tools) == 17


def test_agent_session_injects_existing_preferences_into_system_prompt(tmp_path):
    from app.services.preferences import PreferencesService

    engine = make_engine(str(tmp_path / "session_prefs.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    PreferencesService(session_factory).set_preference(key="default_payment_mode", value="upi")

    session = AgentSession(chat_id="test-chat", session_factory=session_factory)

    assert "default_payment_mode: upi" in session._options.system_prompt
