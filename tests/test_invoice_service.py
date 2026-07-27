from decimal import Decimal

import pytest

from app.db import Base, make_engine, make_session_factory
from app.errors import BillNotFoundError
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

    assert b"Sharma Kirana Store" in pdf_bytes


def test_render_invoice_pdf_raises_for_unknown_bill(tmp_path):
    _, _, _, invoice = _make_services(tmp_path)
    with pytest.raises(BillNotFoundError):
        invoice.render_invoice_pdf(bill_id=99999)
