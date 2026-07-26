import asyncio
from decimal import Decimal

from app.db import Base, make_engine, make_session_factory
from app.services.billing import BillingService
from app.services.inventory import InventoryService
from app.tools.billing_tools import UpdateContext, build_billing_tools


def _make_services(tmp_path):
    engine = make_engine(str(tmp_path / "bill_tools.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    return InventoryService(session_factory), BillingService(session_factory)


def _make_product(inventory, qty=Decimal("10")):
    inventory.create_product(
        name="Tata Salt 1kg", category="staples", unit="packet", is_loose=False,
        hsn_code="25010020", gst_slab=5, cost_price=Decimal("18.00"),
        sell_price=Decimal("22.00"), mrp=Decimal("24.00"), reorder_level=Decimal("5"),
        initial_qty=qty,
    )


def _make_duplicate_named_products(inventory):
    inventory.create_product(
        name="Dup Product", category="fmcg", unit="packet", is_loose=False,
        hsn_code="00000000", gst_slab=0, cost_price=Decimal("1"), sell_price=Decimal("2"),
        mrp=Decimal("2"), reorder_level=Decimal("1"), initial_qty=Decimal("10"),
    )
    inventory.create_product(
        name="DUP PRODUCT", category="fmcg", unit="packet", is_loose=False,
        hsn_code="00000001", gst_slab=0, cost_price=Decimal("1"), sell_price=Decimal("2"),
        mrp=Decimal("2"), reorder_level=Decimal("1"), initial_qty=Decimal("10"),
    )


def _tools_by_name(billing, inventory, chat_id="chat-1", update_context=None):
    return {t.name: t for t in build_billing_tools(billing, inventory, chat_id, update_context or UpdateContext())}


def test_start_bill_then_get_bill_draft_is_empty(tmp_path):
    inventory, billing = _make_services(tmp_path)
    tools = _tools_by_name(billing, inventory)
    asyncio.run(tools["start_bill"].handler({"payment_mode": "upi"}))
    result = asyncio.run(tools["get_bill_draft"].handler({}))
    assert "empty" in result["content"][0]["text"].lower()


def test_add_bill_item_appears_in_draft(tmp_path):
    inventory, billing = _make_services(tmp_path)
    _make_product(inventory)
    tools = _tools_by_name(billing, inventory)
    asyncio.run(tools["start_bill"].handler({}))
    result = asyncio.run(tools["add_bill_item"].handler({"product_name": "Tata Salt 1kg", "qty": "2"}))
    assert not result.get("is_error")
    draft = asyncio.run(tools["get_bill_draft"].handler({}))
    assert "Tata Salt 1kg" in draft["content"][0]["text"]


def test_add_bill_item_is_error_for_unknown_product(tmp_path):
    inventory, billing = _make_services(tmp_path)
    tools = _tools_by_name(billing, inventory)
    asyncio.run(tools["start_bill"].handler({}))
    result = asyncio.run(tools["add_bill_item"].handler({"product_name": "Nonexistent", "qty": "1"}))
    assert result.get("is_error") is True


def test_update_bill_item_changes_qty(tmp_path):
    inventory, billing = _make_services(tmp_path)
    _make_product(inventory)
    tools = _tools_by_name(billing, inventory)
    asyncio.run(tools["start_bill"].handler({}))
    asyncio.run(tools["add_bill_item"].handler({"product_name": "Tata Salt 1kg", "qty": "2"}))
    asyncio.run(tools["update_bill_item"].handler({"product_name": "Tata Salt 1kg", "qty": "6"}))
    draft = asyncio.run(tools["get_bill_draft"].handler({}))
    assert "6" in draft["content"][0]["text"]


def test_drop_bill_item_removes_line(tmp_path):
    inventory, billing = _make_services(tmp_path)
    _make_product(inventory)
    tools = _tools_by_name(billing, inventory)
    asyncio.run(tools["start_bill"].handler({}))
    asyncio.run(tools["add_bill_item"].handler({"product_name": "Tata Salt 1kg", "qty": "2"}))
    asyncio.run(tools["drop_bill_item"].handler({"product_name": "Tata Salt 1kg"}))
    draft = asyncio.run(tools["get_bill_draft"].handler({}))
    assert "empty" in draft["content"][0]["text"].lower()


def test_cancel_bill_discards_draft(tmp_path):
    inventory, billing = _make_services(tmp_path)
    tools = _tools_by_name(billing, inventory)
    asyncio.run(tools["start_bill"].handler({}))
    result = asyncio.run(tools["cancel_bill"].handler({}))
    assert not result.get("is_error")
    draft = asyncio.run(tools["get_bill_draft"].handler({}))
    assert draft.get("is_error") is True  # NoDraftBillError, since it was cancelled


def test_finalize_bill_decrements_stock_and_uses_update_context(tmp_path):
    inventory, billing = _make_services(tmp_path)
    _make_product(inventory, qty=Decimal("10"))
    update_context = UpdateContext()
    tools = _tools_by_name(billing, inventory, update_context=update_context)
    asyncio.run(tools["start_bill"].handler({"payment_mode": "cash"}))
    asyncio.run(tools["add_bill_item"].handler({"product_name": "Tata Salt 1kg", "qty": "2"}))

    update_context.current_update_id = "update-1"
    result = asyncio.run(tools["finalize_bill"].handler({}))
    assert not result.get("is_error")
    assert inventory.get_stock(product_id=inventory.find_product_by_name(name="Tata Salt 1kg").id) == Decimal("8")


def test_finalize_bill_is_error_on_oversell(tmp_path):
    inventory, billing = _make_services(tmp_path)
    _make_product(inventory, qty=Decimal("1"))
    update_context = UpdateContext()
    tools = _tools_by_name(billing, inventory, update_context=update_context)
    asyncio.run(tools["start_bill"].handler({"payment_mode": "cash"}))
    asyncio.run(tools["add_bill_item"].handler({"product_name": "Tata Salt 1kg", "qty": "10"}))

    update_context.current_update_id = "update-2"
    result = asyncio.run(tools["finalize_bill"].handler({}))
    assert result.get("is_error") is True


def test_add_bill_item_is_error_for_ambiguous_product_name(tmp_path):
    inventory, billing = _make_services(tmp_path)
    _make_duplicate_named_products(inventory)
    tools = _tools_by_name(billing, inventory)
    asyncio.run(tools["start_bill"].handler({}))
    result = asyncio.run(tools["add_bill_item"].handler({"product_name": "dup product", "qty": "1"}))
    assert result.get("is_error") is True


def test_update_bill_item_is_error_for_ambiguous_product_name(tmp_path):
    inventory, billing = _make_services(tmp_path)
    _make_duplicate_named_products(inventory)
    tools = _tools_by_name(billing, inventory)
    asyncio.run(tools["start_bill"].handler({}))
    result = asyncio.run(tools["update_bill_item"].handler({"product_name": "dup product", "qty": "1"}))
    assert result.get("is_error") is True


def test_drop_bill_item_is_error_for_ambiguous_product_name(tmp_path):
    inventory, billing = _make_services(tmp_path)
    _make_duplicate_named_products(inventory)
    tools = _tools_by_name(billing, inventory)
    asyncio.run(tools["start_bill"].handler({}))
    result = asyncio.run(tools["drop_bill_item"].handler({"product_name": "dup product"}))
    assert result.get("is_error") is True
