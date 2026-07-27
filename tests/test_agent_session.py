import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from claude_agent_sdk import ResultMessage
from mcp import types as mcp_types

from app.agent_session import AgentSession, SendResult
from app.db import Base, make_engine, make_session_factory


def _make_session(tmp_path, name="session_send.db"):
    engine = make_engine(str(tmp_path / name))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    return AgentSession(chat_id="test-chat", session_factory=session_factory)


def _make_result_message(result="ok", is_error=False):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id="fake-session",
        result=result,
    )


def _install_fake_client(session, *, query_side_effect=None):
    fake_client = MagicMock()
    fake_client.connect = AsyncMock()
    fake_client.disconnect = AsyncMock()
    if query_side_effect is not None:
        fake_client.query = AsyncMock(side_effect=query_side_effect)
    else:
        fake_client.query = AsyncMock()

    async def _receive_response():
        yield _make_result_message()

    fake_client.receive_response = MagicMock(side_effect=lambda: _receive_response())
    session._client = fake_client
    return fake_client


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
        "credit_customer", "settle_khata", "get_khata_balance", "list_customers",
        "set_preference", "get_preference",
        "render_invoice_pdf", "get_daily_summary", "render_analysis_deck",
    }
    assert session._options.tools == ["Skill"]
    assert session._options.strict_mcp_config is True
    assert session._options.permission_mode == "bypassPermissions"
    assert session.chat_id == "test-chat"

    # Options that make Skills actually discoverable/usable -- a regression
    # here fails open (skills silently become undiscoverable, no crash).
    assert session._options.setting_sources == ["project"]
    # Explicit allowlist, not "all" -- "all" leaks 12+ Claude Code CLI-bundled
    # skills (dataviz, update-config, security-review, ...) into this bot.
    assert session._options.skills == [
        "inventory", "billing", "khata", "preferences", "invoicing", "analytics",
    ]
    assert session._options.cwd == str(session._options.cwd)  # sanity: it's set to something
    assert session._options.max_turns == 20
    # Model is pinned, not left to whatever the ambient `claude` CLI resolves to.
    assert session._options.model == "claude-sonnet-5"

    # Confirm all 18 tools actually made it into the MCP server config (not
    # just into `_all_tools`). `McpSdkServerConfig["instance"]` is a private
    # mcp.server.lowlevel.server.Server; its registered list_tools handler is
    # the only way to introspect what Claude will actually see, so we invoke
    # it directly via the low-level mcp request/response types.
    mcp_server = session._options.mcp_servers["kirana"]["instance"]
    list_tools_handler = mcp_server.request_handlers[mcp_types.ListToolsRequest]
    list_tools_result = asyncio.run(
        list_tools_handler(mcp_types.ListToolsRequest(method="tools/list"))
    )
    assert len(list_tools_result.root.tools) == 21

    # Regression check for a real bug: start_bill/finalize_bill used the
    # simple-dict schema shorthand ({"payment_mode": str}), which the SDK's
    # schema builder marks as ALL required -- even though both fields are
    # meant to be optional (the handlers already do `args.get(...) or None`).
    # A `.handler()`-direct test cannot catch this since it bypasses schema
    # validation entirely -- this has to inspect the registered tool schema.
    tools_by_name = {t.name: t for t in list_tools_result.root.tools}
    assert tools_by_name["start_bill"].inputSchema.get("required", []) == []
    assert tools_by_name["finalize_bill"].inputSchema.get("required", []) == []


def test_agent_session_registers_invoicing_and_analytics_tools(tmp_path):
    engine = make_engine(str(tmp_path / "session_artifacts.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    session = AgentSession(chat_id="test-chat", session_factory=session_factory)

    tool_names = {t.name for t in session._all_tools}
    assert {"render_invoice_pdf", "get_daily_summary", "render_analysis_deck"} <= tool_names


def test_agent_session_injects_existing_preferences_into_system_prompt(tmp_path):
    from app.services.preferences import PreferencesService

    engine = make_engine(str(tmp_path / "session_prefs.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    PreferencesService(session_factory).set_preference(key="default_payment_mode", value="upi")

    session = AgentSession(chat_id="test-chat", session_factory=session_factory)

    assert "default_payment_mode: upi" in session._options.system_prompt


def test_send_escapes_leading_slash_text_before_querying_client(tmp_path):
    # Regression test for the Critical slash-interception fix: Claude Code's
    # CLI-level slash-command parser intercepts a literal "/context" before
    # the model ever sees it (verified live). send() must never hand a
    # leading-"/" owner message to query() unescaped.
    session = _make_session(tmp_path)
    fake_client = _install_fake_client(session)

    result = asyncio.run(session.send("/context", update_id="u1"))

    assert result.text == "ok"
    fake_client.query.assert_awaited_once()
    (queried_text,), _ = fake_client.query.await_args
    assert queried_text != "/context"
    assert "/context" in queried_text  # escaped as literal text, not dropped


@pytest.mark.parametrize("command_text", ["/new", "  /NeW  "])
def test_send_new_resets_connection_without_querying_client(tmp_path, command_text):
    session = _make_session(tmp_path)
    fake_client = _install_fake_client(session)
    session._connected = True

    result = asyncio.run(session.send(command_text, update_id="u1"))

    assert result.text == "Started a fresh conversation."
    fake_client.query.assert_not_awaited()
    fake_client.disconnect.assert_awaited_once()
    assert session._connected is False


def test_send_resets_connected_flag_on_failure(tmp_path):
    session = _make_session(tmp_path)
    _install_fake_client(session, query_side_effect=RuntimeError("boom"))
    session._connected = True

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(session.send("hello", update_id="u1"))

    assert session._connected is False


def test_send_returns_send_result_with_no_artifact_by_default(tmp_path):
    session = _make_session(tmp_path)
    _install_fake_client(session)

    result = asyncio.run(session.send("how much sugar is left?", update_id="u1"))

    assert isinstance(result, SendResult)
    assert result.text == "ok"
    assert result.artifact is None


def test_send_returns_artifact_when_a_tool_populated_it(tmp_path):
    session = _make_session(tmp_path)
    _install_fake_client(session)
    session._artifact_context.set(data=b"%PDF-fake", filename="invoice-1.pdf", mime_type="application/pdf")

    result = asyncio.run(session.send("send me that as a pdf", update_id="u1"))

    assert result.artifact is not None
    assert result.artifact.filename == "invoice-1.pdf"
    # Popped, not left behind for the next turn:
    assert session._artifact_context.pop() is None


def test_send_discards_stale_artifact_after_a_failed_turn(tmp_path):
    # Regression test: a tool sets an artifact mid-turn, then the turn fails
    # (query() raises). The stale artifact must not survive to leak into the
    # next -- unrelated -- successful turn on the same session.
    session = _make_session(tmp_path)
    fake_client = _install_fake_client(session, query_side_effect=RuntimeError("boom"))
    session._connected = True

    session._artifact_context.set(data=b"%PDF-fake", filename="stale.pdf", mime_type="application/pdf")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(session.send("hello", update_id="u1"))

    # Reconfigure the fake client to succeed normally on the next turn.
    fake_client.query = AsyncMock()
    session._connected = False

    result = asyncio.run(session.send("how much sugar is left?", update_id="u2"))

    assert result.artifact is None


def test_agent_session_skills_allowlist_includes_invoicing_and_analytics(tmp_path):
    engine = make_engine(str(tmp_path / "session_skills.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    session = AgentSession(chat_id="test-chat", session_factory=session_factory)

    assert set(session._options.skills) == {
        "inventory", "billing", "khata", "preferences", "invoicing", "analytics",
    }
