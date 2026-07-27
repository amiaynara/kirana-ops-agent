from datetime import date
from decimal import Decimal

from app.db import Base, make_engine, make_session_factory
from app.services.analytics import AnalyticsService
from app.services.billing import BillingService
from app.services.inventory import InventoryService


def _make_services(tmp_path):
    engine = make_engine(str(tmp_path / "analytics.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    return (
        InventoryService(session_factory),
        BillingService(session_factory),
        AnalyticsService(session_factory),
    )


def _finalize_a_bill(inventory, billing, product_id, qty, chat_id, update_id, mode="upi"):
    billing.start_bill(chat_id=chat_id, payment_mode=mode)
    billing.add_item(chat_id=chat_id, product_id=product_id, qty=qty)
    return billing.finalize_bill(chat_id=chat_id, telegram_update_id=update_id)


def test_get_daily_summary_reflects_todays_finalized_bills(tmp_path):
    inventory, billing, analytics = _make_services(tmp_path)
    product_id = inventory.create_product(
        name="Maggi 70g", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19023090", gst_slab=12, cost_price=Decimal("10.00"),
        sell_price=Decimal("14.00"), mrp=Decimal("14.00"), reorder_level=Decimal("20"),
        initial_qty=Decimal("100"),
    )
    _finalize_a_bill(inventory, billing, product_id, Decimal("4"), "chat-1", "u-1", mode="cash")
    _finalize_a_bill(inventory, billing, product_id, Decimal("2"), "chat-2", "u-2", mode="upi")

    summary = analytics.get_daily_summary()

    assert summary["date"] == date.today()
    assert summary["bill_count"] == 2
    assert summary["total_sales"] > Decimal("0")
    assert summary["tax_collected"] > Decimal("0")
    assert set(summary["by_payment_mode"].keys()) == {"cash", "upi"}
    assert summary["top_items"][0][0] == "Maggi 70g"


def test_get_daily_summary_for_empty_day_returns_zeroes(tmp_path):
    _, _, analytics = _make_services(tmp_path)

    summary = analytics.get_daily_summary(target_date=date(2020, 1, 1))

    assert summary["bill_count"] == 0
    assert summary["total_sales"] == Decimal("0")
    assert summary["top_items"] == []


def test_render_analysis_deck_produces_a_valid_pptx(tmp_path):
    inventory, billing, analytics = _make_services(tmp_path)
    product_id = inventory.create_product(
        name="Parle-G", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19053100", gst_slab=5, cost_price=Decimal("8.00"),
        sell_price=Decimal("10.00"), mrp=Decimal("10.00"), reorder_level=Decimal("20"),
        initial_qty=Decimal("50"),
    )
    _finalize_a_bill(inventory, billing, product_id, Decimal("3"), "chat-1", "u-1")

    today = date.today()
    pptx_bytes = analytics.render_analysis_deck(start_date=today, end_date=today)

    assert pptx_bytes[:2] == b"PK"  # pptx is a zip archive
    assert len(pptx_bytes) > 1000
