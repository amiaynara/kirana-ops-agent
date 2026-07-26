import asyncio
from decimal import Decimal

from app.db import Base, make_engine, make_session_factory
from app.services.inventory import InventoryService
from app.tools.inventory_tools import build_inventory_tools


def _make_inventory(tmp_path):
    engine = make_engine(str(tmp_path / "inv_tools.db"))
    Base.metadata.create_all(engine)
    return InventoryService(make_session_factory(engine))


def _tools_by_name(inventory):
    return {t.name: t for t in build_inventory_tools(inventory)}


def test_get_stock_reports_quantity_for_known_product(tmp_path):
    inventory = _make_inventory(tmp_path)
    inventory.create_product(
        name="Tata Salt 1kg", category="staples", unit="packet", is_loose=False,
        hsn_code="25010020", gst_slab=5, cost_price=Decimal("18.00"),
        sell_price=Decimal("22.00"), mrp=Decimal("24.00"), reorder_level=Decimal("5"),
        initial_qty=Decimal("40"),
    )
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["get_stock"].handler({"product_name": "Tata Salt 1kg"}))
    assert not result.get("is_error")
    assert "40" in result["content"][0]["text"]


def test_get_stock_is_error_for_unknown_product(tmp_path):
    inventory = _make_inventory(tmp_path)
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["get_stock"].handler({"product_name": "Nonexistent"}))
    assert result.get("is_error") is True


def test_list_low_stock_reports_products_at_or_below_reorder(tmp_path):
    inventory = _make_inventory(tmp_path)
    inventory.create_product(
        name="Almost Out", category="fmcg", unit="packet", is_loose=False,
        hsn_code="00000000", gst_slab=0, cost_price=Decimal("1"), sell_price=Decimal("2"),
        mrp=Decimal("2"), reorder_level=Decimal("10"), initial_qty=Decimal("3"),
    )
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["list_low_stock"].handler({}))
    assert "Almost Out" in result["content"][0]["text"]


def test_list_products_lists_every_product(tmp_path):
    inventory = _make_inventory(tmp_path)
    inventory.create_product(
        name="Parle-G", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19053100", gst_slab=5, cost_price=Decimal("8.00"),
        sell_price=Decimal("10.00"), mrp=Decimal("10.00"), reorder_level=Decimal("20"),
    )
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["list_products"].handler({}))
    assert "Parle-G" in result["content"][0]["text"]


def test_receive_stock_increments_and_reports(tmp_path):
    inventory = _make_inventory(tmp_path)
    inventory.create_product(
        name="Maggi 70g", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19023090", gst_slab=12, cost_price=Decimal("10.00"),
        sell_price=Decimal("14.00"), mrp=Decimal("14.00"), reorder_level=Decimal("20"),
        initial_qty=Decimal("10"),
    )
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["receive_stock"].handler({"product_name": "Maggi 70g", "qty": "50"}))
    assert not result.get("is_error")
    assert inventory.get_stock(product_id=inventory.find_product_by_name(name="Maggi 70g").id) == Decimal("60")


def test_receive_stock_is_error_for_unknown_product(tmp_path):
    inventory = _make_inventory(tmp_path)
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["receive_stock"].handler({"product_name": "Nonexistent", "qty": "5"}))
    assert result.get("is_error") is True


def test_create_product_creates_and_reports(tmp_path):
    inventory = _make_inventory(tmp_path)
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["create_product"].handler({
        "name": "Surf Excel 1kg", "category": "fmcg", "unit": "packet", "is_loose": False,
        "hsn_code": "34022090", "gst_slab": 18, "cost_price": "95.00", "sell_price": "115.00",
        "mrp": "125.00", "reorder_level": "5",
    }))
    assert not result.get("is_error")
    assert inventory.find_product_by_name(name="Surf Excel 1kg") is not None


def test_create_product_is_error_below_cost(tmp_path):
    inventory = _make_inventory(tmp_path)
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["create_product"].handler({
        "name": "Underpriced", "category": "fmcg", "unit": "packet", "is_loose": False,
        "hsn_code": "00000000", "gst_slab": 5, "cost_price": "50.00", "sell_price": "40.00",
        "mrp": "60.00", "reorder_level": "1",
    }))
    assert result.get("is_error") is True


def test_get_stock_is_error_for_ambiguous_product_name(tmp_path):
    inventory = _make_inventory(tmp_path)
    inventory.create_product(
        name="Dup Product", category="fmcg", unit="packet", is_loose=False,
        hsn_code="00000000", gst_slab=0, cost_price=Decimal("1"), sell_price=Decimal("2"),
        mrp=Decimal("2"), reorder_level=Decimal("1"),
    )
    inventory.create_product(
        name="DUP PRODUCT", category="fmcg", unit="packet", is_loose=False,
        hsn_code="00000001", gst_slab=0, cost_price=Decimal("1"), sell_price=Decimal("2"),
        mrp=Decimal("2"), reorder_level=Decimal("1"),
    )
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["get_stock"].handler({"product_name": "dup product"}))
    assert result.get("is_error") is True


def test_receive_stock_is_error_for_malformed_qty(tmp_path):
    inventory = _make_inventory(tmp_path)
    inventory.create_product(
        name="Maggi 70g", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19023090", gst_slab=12, cost_price=Decimal("10.00"),
        sell_price=Decimal("14.00"), mrp=Decimal("14.00"), reorder_level=Decimal("20"),
        initial_qty=Decimal("10"),
    )
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["receive_stock"].handler({"product_name": "Maggi 70g", "qty": "not-a-number"}))
    assert result.get("is_error") is True


def test_receive_stock_is_error_for_ambiguous_product_name(tmp_path):
    inventory = _make_inventory(tmp_path)
    inventory.create_product(
        name="Dup Product", category="fmcg", unit="packet", is_loose=False,
        hsn_code="00000000", gst_slab=0, cost_price=Decimal("1"), sell_price=Decimal("2"),
        mrp=Decimal("2"), reorder_level=Decimal("1"),
    )
    inventory.create_product(
        name="DUP PRODUCT", category="fmcg", unit="packet", is_loose=False,
        hsn_code="00000001", gst_slab=0, cost_price=Decimal("1"), sell_price=Decimal("2"),
        mrp=Decimal("2"), reorder_level=Decimal("1"),
    )
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["receive_stock"].handler({"product_name": "dup product", "qty": "5"}))
    assert result.get("is_error") is True
