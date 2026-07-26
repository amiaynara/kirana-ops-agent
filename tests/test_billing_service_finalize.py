from decimal import Decimal

import pytest

from app.db import Base, make_engine, make_session_factory
from app.errors import InsufficientStockError, NoDraftBillError
from app.services.billing import BillingService
from app.services.inventory import InventoryService


@pytest.fixture
def services(tmp_path):
    engine = make_engine(str(tmp_path / "finalize.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    return InventoryService(session_factory), BillingService(session_factory)


def _make_product(inventory, qty=Decimal("10")):
    return inventory.create_product(
        name="Tata Salt 1kg", category="staples", unit="packet", is_loose=False,
        hsn_code="25010020", gst_slab=5, cost_price=Decimal("18.00"),
        sell_price=Decimal("22.00"), mrp=Decimal("24.00"), reorder_level=Decimal("5"),
        initial_qty=qty,
    )


def test_finalize_bill_decrements_stock_and_returns_new_bill(services):
    inventory, billing = services
    product_id = _make_product(inventory, qty=Decimal("10"))
    billing.start_bill(chat_id="chat-1", payment_mode="upi")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))

    bill_id, is_duplicate = billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-1")

    assert is_duplicate is False
    assert isinstance(bill_id, int)
    assert inventory.get_stock(product_id=product_id) == Decimal("8")


def test_finalize_bill_is_idempotent_on_same_update_id(services):
    inventory, billing = services
    product_id = _make_product(inventory, qty=Decimal("10"))
    billing.start_bill(chat_id="chat-1", payment_mode="upi")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))

    bill_id_1, dup1 = billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-1")
    bill_id_2, dup2 = billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-1")

    assert dup1 is False
    assert dup2 is True
    assert bill_id_2 == bill_id_1
    assert inventory.get_stock(product_id=product_id) == Decimal("8")  # decremented only once


def test_finalize_bill_refuses_oversell_with_no_partial_writes(services):
    inventory, billing = services
    product_id = _make_product(inventory, qty=Decimal("6"))
    billing.start_bill(chat_id="chat-1", payment_mode="cash")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("10"))

    with pytest.raises(InsufficientStockError):
        billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-x")

    assert inventory.get_stock(product_id=product_id) == Decimal("6")
    payment_mode, totals = billing.get_draft(chat_id="chat-1")
    assert payment_mode == "cash"
    assert len(totals.lines) == 1


def test_finalize_bill_raises_without_a_draft(services):
    inventory, billing = services
    with pytest.raises(NoDraftBillError):
        billing.finalize_bill(chat_id="never-started", telegram_update_id="u-y")


def test_finalize_bill_raises_without_items(services):
    inventory, billing = services
    billing.start_bill(chat_id="chat-1", payment_mode="cash")
    with pytest.raises(NoDraftBillError):
        billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-z")
