import io
from datetime import datetime
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.db import Base, make_engine, make_session_factory
from app.errors import BillNotFoundError
from app.models import Bill, BillItem
from app.services.billing import BillingService
from app.services.inventory import InventoryService
from app.services.invoice import InvoiceService
from app.services.preferences import PreferencesService


def _make_services(tmp_path):
    engine = make_engine(str(tmp_path / "invoice.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    inventory = InventoryService(session_factory)
    billing = BillingService(session_factory)
    preferences = PreferencesService(session_factory)
    invoice = InvoiceService(session_factory, preferences)
    return inventory, billing, preferences, invoice


def _finalize_a_bill(inventory, billing, chat_id="chat-1", update_id="u-1"):
    product_id = inventory.create_product(
        name="Tata Salt 1kg", category="staples", unit="packet", is_loose=False,
        hsn_code="25010020", gst_slab=5, cost_price=Decimal("18.00"),
        sell_price=Decimal("22.00"), mrp=Decimal("24.00"), reorder_level=Decimal("5"),
        initial_qty=Decimal("10"),
    )
    billing.start_bill(chat_id=chat_id, payment_mode="upi")
    billing.add_item(chat_id=chat_id, product_id=product_id, qty=Decimal("2"))
    bill_id, _ = billing.finalize_bill(chat_id=chat_id, telegram_update_id=update_id)
    return bill_id


def test_render_invoice_pdf_produces_real_pdf_bytes(tmp_path):
    inventory, billing, preferences, invoice = _make_services(tmp_path)
    bill_id = _finalize_a_bill(inventory, billing)

    pdf_bytes = invoice.render_invoice_pdf(bill_id=bill_id)

    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 500


def test_render_invoice_pdf_includes_shop_preferences(tmp_path):
    inventory, billing, preferences, invoice = _make_services(tmp_path)
    preferences.set_preference(key="shop_name", value="Sharma Kirana Store")
    bill_id = _finalize_a_bill(inventory, billing)

    pdf_bytes = invoice.render_invoice_pdf(bill_id=bill_id)

    reader = PdfReader(io.BytesIO(pdf_bytes))
    extracted_text = "\n".join(page.extract_text() for page in reader.pages)
    assert "Sharma Kirana Store" in extracted_text


def test_render_invoice_pdf_raises_for_unknown_bill(tmp_path):
    _, _, _, invoice = _make_services(tmp_path)
    with pytest.raises(BillNotFoundError):
        invoice.render_invoice_pdf(bill_id=99999)


def test_render_invoice_pdf_shows_ist_date_and_time_not_utc(tmp_path):
    # Regression test (Finding 1): Bill.created_at is stored naive-but-UTC-
    # valued. The invoice must show the shop's local (IST) date/time, same as
    # AnalyticsService.get_daily_summary already correctly does -- not the
    # raw UTC value (verified live: the two documents disagreed on the date
    # for the same bill before this fix).
    inventory, billing, preferences, invoice = _make_services(tmp_path)
    bill_id = _finalize_a_bill(inventory, billing)

    # Reuse the same on-disk db via a second engine/session_factory, mirroring
    # the existing pattern in test_analytics_service.py's IST-boundary test.
    engine = make_engine(str(tmp_path / "invoice.db"))
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        with session.begin():
            bill = session.get(Bill, bill_id)
            # Naive, UTC-valued timestamp: 2026-01-01 20:00 UTC == 2026-01-02 01:30 IST.
            bill.created_at = datetime(2026, 1, 1, 20, 0, 0)

    pdf_bytes = invoice.render_invoice_pdf(bill_id=bill_id)

    reader = PdfReader(io.BytesIO(pdf_bytes))
    extracted_text = "\n".join(page.extract_text() for page in reader.pages)
    assert "02-Jan-2026" in extracted_text
    assert "01:30" in extracted_text
    # The raw UTC date/time must not leak through.
    assert "01-Jan-2026" not in extracted_text
    assert "20:00" not in extracted_text


def test_render_invoice_pdf_reconciles_both_totals_blocks_on_non_zero_round_off(tmp_path):
    # Regression test (Finding 2): the line-items-total + rounding-adjustment
    # block and the Subtotal/CGST/SGST/Grand-Total block reconcile two
    # different pairs of numbers. Mixing a round-off row into the
    # Subtotal/CGST/SGST/Grand-Total block made that block's own arithmetic
    # wrong (verified live). Two loose-staple lines at qty 0.5 x Rs 33.33,
    # gst_slab=0, reproduce the same genuine sub-paisa drift as
    # test_billing_math.test_bill_level_rounding_avoids_drift_vs_naive_per_line_rounding:
    # summed rounded line_totals (33.34) differ from grand_total (33.33) by a paisa.
    inventory, billing, preferences, invoice = _make_services(tmp_path)
    product_id_1 = inventory.create_product(
        name="Loose Sugar A", category="staples", unit="kg", is_loose=True,
        hsn_code="17019900", gst_slab=0, cost_price=Decimal("30.00"),
        sell_price=Decimal("33.33"), mrp=Decimal("35.00"), reorder_level=Decimal("1"),
        initial_qty=Decimal("5"),
    )
    product_id_2 = inventory.create_product(
        name="Loose Sugar B", category="staples", unit="kg", is_loose=True,
        hsn_code="17019900", gst_slab=0, cost_price=Decimal("30.00"),
        sell_price=Decimal("33.33"), mrp=Decimal("35.00"), reorder_level=Decimal("1"),
        initial_qty=Decimal("5"),
    )
    billing.start_bill(chat_id="chat-round", payment_mode="cash")
    billing.add_item(chat_id="chat-round", product_id=product_id_1, qty=Decimal("0.5"))
    billing.add_item(chat_id="chat-round", product_id=product_id_2, qty=Decimal("0.5"))
    bill_id, _ = billing.finalize_bill(chat_id="chat-round", telegram_update_id="u-round")

    # Pull the actual persisted Decimal values back out of the DB -- the
    # expected numbers below are derived from these, not hardcoded, so the
    # test stays correct if bill construction changes.
    engine = make_engine(str(tmp_path / "invoice.db"))
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        bill = session.get(Bill, bill_id)
        bill_items = session.query(BillItem).filter(BillItem.bill_id == bill_id).all()
        subtotal, cgst_total, sgst_total, grand_total = (
            bill.subtotal, bill.cgst_total, bill.sgst_total, bill.grand_total,
        )
        line_items_total = sum((item.line_total for item in bill_items), Decimal("0"))

    round_off = grand_total - line_items_total
    assert round_off != Decimal("0")  # sanity: this scenario genuinely drifts
    assert line_items_total + round_off == grand_total
    assert subtotal + cgst_total + sgst_total == grand_total

    pdf_bytes = invoice.render_invoice_pdf(bill_id=bill_id)

    reader = PdfReader(io.BytesIO(pdf_bytes))
    extracted_text = "\n".join(page.extract_text() for page in reader.pages)
    assert f"{line_items_total:.2f}" in extracted_text
    assert f"{round_off:.2f}" in extracted_text
    assert f"{subtotal:.2f}" in extracted_text
    assert f"{cgst_total:.2f}" in extracted_text
    assert f"{sgst_total:.2f}" in extracted_text
    assert f"{grand_total:.2f}" in extracted_text
