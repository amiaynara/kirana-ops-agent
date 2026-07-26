from decimal import Decimal

import pytest

from app.db import Base, make_engine, make_session_factory
from app.errors import (
    LineNotFoundError,
    NoDraftBillError,
    ProductNotFoundError,
    ValidationError,
)
from app.services.billing import BillingService
from app.services.inventory import InventoryService


@pytest.fixture
def services(tmp_path):
    engine = make_engine(str(tmp_path / "billing.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    return InventoryService(session_factory), BillingService(session_factory)


def _make_product(inventory, name="Tata Salt 1kg", gst_slab=5, sell_price=Decimal("22.00")):
    return inventory.create_product(
        name=name, category="staples", unit="packet", is_loose=False,
        hsn_code="25010020", gst_slab=gst_slab, cost_price=Decimal("18.00"),
        sell_price=sell_price, mrp=Decimal("24.00"), reorder_level=Decimal("5"),
        initial_qty=Decimal("100"),
    )


def test_start_bill_then_get_draft_is_empty(services):
    inventory, billing = services
    billing.start_bill(chat_id="chat-1", payment_mode="upi")
    payment_mode, totals = billing.get_draft(chat_id="chat-1")
    assert payment_mode == "upi"
    assert totals.lines == []
    assert totals.grand_total == Decimal("0")


def test_add_item_appears_in_draft_totals(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))
    _, totals = billing.get_draft(chat_id="chat-1")
    assert len(totals.lines) == 1
    assert totals.lines[0].qty == Decimal("2")
    assert totals.subtotal == Decimal("44.00")


def test_add_item_twice_for_same_product_replaces_not_duplicates(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("5"))
    _, totals = billing.get_draft(chat_id="chat-1")
    assert len(totals.lines) == 1
    assert totals.lines[0].qty == Decimal("5")


def test_update_item_changes_qty(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))
    billing.update_item(chat_id="chat-1", product_id=product_id, qty=Decimal("6"))
    _, totals = billing.get_draft(chat_id="chat-1")
    assert totals.lines[0].qty == Decimal("6")


def test_update_item_raises_for_line_not_in_draft(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    with pytest.raises(LineNotFoundError):
        billing.update_item(chat_id="chat-1", product_id=product_id, qty=Decimal("1"))


def test_drop_item_removes_line(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))
    billing.drop_item(chat_id="chat-1", product_id=product_id)
    _, totals = billing.get_draft(chat_id="chat-1")
    assert totals.lines == []


def test_drop_item_raises_for_line_not_in_draft(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    with pytest.raises(LineNotFoundError):
        billing.drop_item(chat_id="chat-1", product_id=product_id)


def test_add_item_raises_for_unknown_product(services):
    inventory, billing = services
    billing.start_bill(chat_id="chat-1")
    with pytest.raises(ProductNotFoundError):
        billing.add_item(chat_id="chat-1", product_id=99999, qty=Decimal("1"))


def test_add_item_without_start_bill_raises(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    with pytest.raises(NoDraftBillError):
        billing.add_item(chat_id="never-started", product_id=product_id, qty=Decimal("1"))


def test_cancel_bill_removes_draft(services):
    inventory, billing = services
    billing.start_bill(chat_id="chat-1")
    billing.cancel_bill(chat_id="chat-1")
    with pytest.raises(NoDraftBillError):
        billing.get_draft(chat_id="chat-1")


def test_add_item_rejects_non_positive_qty(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    with pytest.raises(ValidationError):
        billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("0"))


def test_update_item_rejects_non_positive_qty(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))
    with pytest.raises(ValidationError):
        billing.update_item(chat_id="chat-1", product_id=product_id, qty=Decimal("-1"))


def test_start_bill_overwrites_prior_incomplete_draft(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("3"))
    billing.start_bill(chat_id="chat-1", payment_mode="cash")
    payment_mode, totals = billing.get_draft(chat_id="chat-1")
    assert payment_mode == "cash"
    assert totals.lines == []
