from decimal import Decimal

import pytest

from app.db import Base, make_engine, make_session_factory
from app.errors import InsufficientStockError, MissingPaymentModeError, NoDraftBillError
from app.models import Bill, BillItem, DraftBill, StockMovement
from app.services.billing import BillingService
from app.services.inventory import InventoryService


@pytest.fixture
def services(tmp_path):
    engine = make_engine(str(tmp_path / "finalize.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    return InventoryService(session_factory), BillingService(session_factory), session_factory


def _make_product(inventory, qty=Decimal("10")):
    return inventory.create_product(
        name="Tata Salt 1kg", category="staples", unit="packet", is_loose=False,
        hsn_code="25010020", gst_slab=5, cost_price=Decimal("18.00"),
        sell_price=Decimal("22.00"), mrp=Decimal("24.00"), reorder_level=Decimal("5"),
        initial_qty=qty,
    )


def test_finalize_bill_decrements_stock_and_returns_new_bill(services):
    inventory, billing, session_factory = services
    product_id = _make_product(inventory, qty=Decimal("10"))
    billing.start_bill(chat_id="chat-1", payment_mode="upi")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))

    bill_id, is_duplicate = billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-1")

    assert is_duplicate is False
    assert isinstance(bill_id, int)
    assert inventory.get_stock(product_id=product_id) == Decimal("8")

    with session_factory() as session:
        bill = session.get(Bill, bill_id)
        assert bill is not None
        assert bill.payment_mode == "upi"  # fell back to the draft's default, no override passed
        assert bill.subtotal == Decimal("44.00")
        assert bill.cgst_total == Decimal("1.10")
        assert bill.sgst_total == Decimal("1.10")
        assert bill.grand_total == Decimal("46.20")

        bill_items = session.query(BillItem).filter(BillItem.bill_id == bill_id).all()
        assert len(bill_items) == 1
        bill_item = bill_items[0]
        assert bill_item.cgst_amt == Decimal("1.10")
        assert bill_item.sgst_amt == Decimal("1.10")
        assert bill_item.line_total == Decimal("46.20")

        stock_movements = session.query(StockMovement).filter(
            StockMovement.product_id == product_id, StockMovement.reason == "sale"
        ).all()
        assert len(stock_movements) == 1
        stock_movement = stock_movements[0]
        assert stock_movement.delta == Decimal("-2")
        assert stock_movement.ref_bill_id == bill.id

        assert session.get(DraftBill, "chat-1") is None


def test_finalize_bill_is_idempotent_on_same_update_id(services):
    inventory, billing, session_factory = services
    product_id = _make_product(inventory, qty=Decimal("10"))
    billing.start_bill(chat_id="chat-1", payment_mode="upi")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))

    bill_id_1, dup1 = billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-1")
    bill_id_2, dup2 = billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-1")

    assert dup1 is False
    assert dup2 is True
    assert bill_id_2 == bill_id_1
    assert inventory.get_stock(product_id=product_id) == Decimal("8")  # decremented only once

    with session_factory() as session:
        assert session.query(Bill).count() == 1


def test_finalize_bill_refuses_oversell_with_no_partial_writes(services):
    # This is a regression test for the transaction boundary in finalize_bill:
    # the whole method body runs inside one `with session.begin():` block, so
    # any exception raised anywhere in it (including mid-way through writing
    # bill items / stock movements) rolls back everything atomically. That is
    # what guarantees no partial writes here - it is not a property of the
    # order in which lines are validated vs. written.
    inventory, billing, session_factory = services
    ok_product_id = _make_product(inventory, qty=Decimal("10"))
    oversell_product_id = inventory.create_product(
        name="Amul Butter 500g", category="dairy", unit="packet", is_loose=False,
        hsn_code="04051000", gst_slab=12, cost_price=Decimal("200.00"),
        sell_price=Decimal("250.00"), mrp=Decimal("270.00"), reorder_level=Decimal("2"),
        initial_qty=Decimal("6"),
    )
    billing.start_bill(chat_id="chat-1", payment_mode="cash")
    billing.add_item(chat_id="chat-1", product_id=ok_product_id, qty=Decimal("3"))
    billing.add_item(chat_id="chat-1", product_id=oversell_product_id, qty=Decimal("10"))

    with pytest.raises(InsufficientStockError):
        billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-x")

    assert inventory.get_stock(product_id=ok_product_id) == Decimal("10")
    assert inventory.get_stock(product_id=oversell_product_id) == Decimal("6")

    with session_factory() as session:
        assert session.query(Bill).count() == 0

    payment_mode, totals = billing.get_draft(chat_id="chat-1")
    assert payment_mode == "cash"
    assert len(totals.lines) == 2


def test_finalize_bill_raises_without_a_draft(services):
    inventory, billing, session_factory = services
    with pytest.raises(NoDraftBillError):
        billing.finalize_bill(chat_id="never-started", telegram_update_id="u-y")


def test_finalize_bill_raises_without_items(services):
    inventory, billing, session_factory = services
    billing.start_bill(chat_id="chat-1", payment_mode="cash")
    with pytest.raises(NoDraftBillError):
        billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-z")


def test_finalize_bill_raises_missing_payment_mode_when_none_ever_set(services):
    inventory, billing, session_factory = services
    product_id = _make_product(inventory, qty=Decimal("10"))
    billing.start_bill(chat_id="chat-1")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))

    with pytest.raises(MissingPaymentModeError):
        billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-1")


def test_finalize_bill_payment_mode_argument_overrides_draft_default(services):
    inventory, billing, session_factory = services
    product_id = _make_product(inventory, qty=Decimal("10"))
    billing.start_bill(chat_id="chat-1", payment_mode="upi")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))

    bill_id, is_duplicate = billing.finalize_bill(
        chat_id="chat-1", telegram_update_id="u-1", payment_mode="cash", payment_ref="txn-123",
    )

    assert is_duplicate is False
    with session_factory() as session:
        bill = session.get(Bill, bill_id)
        assert bill.payment_mode == "cash"
        assert bill.payment_ref == "txn-123"
