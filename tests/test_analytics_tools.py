import asyncio
from datetime import date
from decimal import Decimal

from app.db import Base, make_engine, make_session_factory
from app.services.analytics import AnalyticsService
from app.services.billing import BillingService
from app.services.inventory import InventoryService
from app.tools.analytics_tools import build_analytics_tools
from app.tools.artifact_context import ArtifactContext


def _make_services(tmp_path):
    engine = make_engine(str(tmp_path / "analytics_tools.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    return (
        InventoryService(session_factory),
        BillingService(session_factory),
        AnalyticsService(session_factory),
    )


def test_get_daily_summary_reports_totals(tmp_path):
    inventory, billing, analytics = _make_services(tmp_path)
    product_id = inventory.create_product(
        name="Maggi 70g", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19023090", gst_slab=12, cost_price=Decimal("10.00"),
        sell_price=Decimal("14.00"), mrp=Decimal("14.00"), reorder_level=Decimal("20"),
        initial_qty=Decimal("100"),
    )
    billing.start_bill(chat_id="chat-1", payment_mode="cash")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("4"))
    billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-1")

    ctx = ArtifactContext()
    tools = {t.name: t for t in build_analytics_tools(analytics, ctx)}
    result = asyncio.run(tools["get_daily_summary"].handler({}))

    assert not result.get("is_error")
    assert "Maggi" in result["content"][0]["text"]
    assert ctx.pop_all() == []  # get_daily_summary never produces a file artifact


def test_render_analysis_deck_sets_artifact(tmp_path):
    inventory, billing, analytics = _make_services(tmp_path)
    product_id = inventory.create_product(
        name="Parle-G", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19053100", gst_slab=5, cost_price=Decimal("8.00"),
        sell_price=Decimal("10.00"), mrp=Decimal("10.00"), reorder_level=Decimal("20"),
        initial_qty=Decimal("50"),
    )
    billing.start_bill(chat_id="chat-1", payment_mode="upi")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("3"))
    billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-1")

    ctx = ArtifactContext()
    tools = {t.name: t for t in build_analytics_tools(analytics, ctx)}
    today = date.today().isoformat()
    result = asyncio.run(tools["render_analysis_deck"].handler(
        {"start_date": today, "end_date": today}
    ))

    assert not result.get("is_error")
    payloads = ctx.pop_all()
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload.data[:2] == b"PK"
    assert payload.mime_type == (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )


def test_get_daily_summary_rejects_malformed_date(tmp_path):
    inventory, billing, analytics = _make_services(tmp_path)
    ctx = ArtifactContext()
    tools = {t.name: t for t in build_analytics_tools(analytics, ctx)}
    result = asyncio.run(tools["get_daily_summary"].handler(
        {"target_date": "not-a-date"}
    ))

    assert result.get("is_error") is True
    assert "must be a date in YYYY-MM-DD format" in result["content"][0]["text"]
    assert ctx.pop_all() == []


def test_render_analysis_deck_rejects_malformed_start_date(tmp_path):
    inventory, billing, analytics = _make_services(tmp_path)
    ctx = ArtifactContext()
    tools = {t.name: t for t in build_analytics_tools(analytics, ctx)}
    result = asyncio.run(tools["render_analysis_deck"].handler(
        {"start_date": "not-a-date", "end_date": "2024-01-01"}
    ))

    assert result.get("is_error") is True
    assert "must be a date in YYYY-MM-DD format" in result["content"][0]["text"]
    assert ctx.pop_all() == []


def test_render_analysis_deck_rejects_malformed_end_date(tmp_path):
    inventory, billing, analytics = _make_services(tmp_path)
    ctx = ArtifactContext()
    tools = {t.name: t for t in build_analytics_tools(analytics, ctx)}
    result = asyncio.run(tools["render_analysis_deck"].handler(
        {"start_date": "2024-01-01", "end_date": "invalid"}
    ))

    assert result.get("is_error") is True
    assert "must be a date in YYYY-MM-DD format" in result["content"][0]["text"]
    assert ctx.pop_all() == []


def test_render_analysis_deck_rejects_reversed_date_range(tmp_path):
    inventory, billing, analytics = _make_services(tmp_path)
    ctx = ArtifactContext()
    tools = {t.name: t for t in build_analytics_tools(analytics, ctx)}
    result = asyncio.run(tools["render_analysis_deck"].handler(
        {"start_date": "2024-01-31", "end_date": "2024-01-01"}
    ))

    assert result.get("is_error") is True
    assert "Refused:" in result["content"][0]["text"]
    assert ctx.pop_all() == []
