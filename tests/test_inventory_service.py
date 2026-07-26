from decimal import Decimal

import pytest

from app.db import Base, make_engine, make_session_factory
from app.errors import (
    AmbiguousProductError,
    BelowCostError,
    ProductNotFoundError,
    ValidationError,
)
from app.models import Product
from app.services.inventory import InventoryService


@pytest.fixture
def inventory(tmp_path):
    engine = make_engine(str(tmp_path / "inventory.db"))
    Base.metadata.create_all(engine)
    return InventoryService(make_session_factory(engine))


def test_create_product_returns_id_with_zero_default_stock(inventory):
    product_id = inventory.create_product(
        name="Parle-G", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19053100", gst_slab=5, cost_price=Decimal("8.00"),
        sell_price=Decimal("10.00"), mrp=Decimal("10.00"), reorder_level=Decimal("20"),
    )
    assert isinstance(product_id, int)
    assert inventory.get_stock(product_id=product_id) == Decimal("0")


def test_create_product_with_initial_qty(inventory):
    product_id = inventory.create_product(
        name="Maggi 70g", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19023090", gst_slab=12, cost_price=Decimal("10.00"),
        sell_price=Decimal("14.00"), mrp=Decimal("14.00"), reorder_level=Decimal("20"),
        initial_qty=Decimal("50"),
    )
    assert inventory.get_stock(product_id=product_id) == Decimal("50")


def test_create_product_rejects_unknown_unit(inventory):
    with pytest.raises(ValidationError):
        inventory.create_product(
            name="Bad Unit", category="fmcg", unit="crate", is_loose=False,
            hsn_code="00000000", gst_slab=0, cost_price=Decimal("1"),
            sell_price=Decimal("2"), mrp=Decimal("2"), reorder_level=Decimal("1"),
        )


def test_create_product_rejects_unknown_gst_slab(inventory):
    with pytest.raises(ValidationError):
        inventory.create_product(
            name="Bad Slab", category="fmcg", unit="packet", is_loose=False,
            hsn_code="00000000", gst_slab=7, cost_price=Decimal("1"),
            sell_price=Decimal("2"), mrp=Decimal("2"), reorder_level=Decimal("1"),
        )


def test_create_product_refuses_selling_below_cost(inventory):
    with pytest.raises(BelowCostError):
        inventory.create_product(
            name="Underpriced", category="fmcg", unit="packet", is_loose=False,
            hsn_code="00000000", gst_slab=5, cost_price=Decimal("50.00"),
            sell_price=Decimal("40.00"), mrp=Decimal("60.00"), reorder_level=Decimal("1"),
        )


def test_create_product_rejects_negative_initial_qty(inventory):
    with pytest.raises(ValidationError):
        inventory.create_product(
            name="Negative Stock", category="fmcg", unit="packet", is_loose=False,
            hsn_code="00000000", gst_slab=5, cost_price=Decimal("1"),
            sell_price=Decimal("2"), mrp=Decimal("2"), reorder_level=Decimal("1"),
            initial_qty=Decimal("-5"),
        )


def test_receive_stock_increments_qty(inventory):
    product_id = inventory.create_product(
        name="Fortune Oil 1L", category="staples", unit="packet", is_loose=False,
        hsn_code="15121900", gst_slab=5, cost_price=Decimal("140.00"),
        sell_price=Decimal("165.00"), mrp=Decimal("175.00"), reorder_level=Decimal("5"),
        initial_qty=Decimal("10"),
    )
    inventory.receive_stock(product_id=product_id, qty=Decimal("50"))
    assert inventory.get_stock(product_id=product_id) == Decimal("60")


def test_receive_stock_refuses_cost_price_above_sell_price(inventory):
    product_id = inventory.create_product(
        name="Fortune Oil 1L", category="staples", unit="packet", is_loose=False,
        hsn_code="15121900", gst_slab=5, cost_price=Decimal("140.00"),
        sell_price=Decimal("165.00"), mrp=Decimal("175.00"), reorder_level=Decimal("5"),
        initial_qty=Decimal("10"),
    )
    with pytest.raises(BelowCostError):
        inventory.receive_stock(product_id=product_id, qty=Decimal("5"), cost_price=Decimal("200.00"))

    with inventory._session_factory() as session:
        product = session.get(Product, product_id)
        assert product.cost_price == Decimal("140.00")


def test_get_stock_raises_for_unknown_product(inventory):
    with pytest.raises(ProductNotFoundError):
        inventory.get_stock(product_id=99999)


def test_list_low_stock_returns_only_products_at_or_below_reorder_level(inventory):
    low_id = inventory.create_product(
        name="Almost Out", category="fmcg", unit="packet", is_loose=False,
        hsn_code="00000000", gst_slab=0, cost_price=Decimal("1"),
        sell_price=Decimal("2"), mrp=Decimal("2"), reorder_level=Decimal("10"),
        initial_qty=Decimal("3"),
    )
    inventory.create_product(
        name="Well Stocked", category="fmcg", unit="packet", is_loose=False,
        hsn_code="00000000", gst_slab=0, cost_price=Decimal("1"),
        sell_price=Decimal("2"), mrp=Decimal("2"), reorder_level=Decimal("10"),
        initial_qty=Decimal("100"),
    )
    low_stock = inventory.list_low_stock()
    low_ids = [row[0] for row in low_stock]
    assert low_id in low_ids
    assert len(low_stock) == 1


def test_find_product_by_name_is_case_insensitive(inventory):
    product_id = inventory.create_product(
        name="Tata Salt 1kg", category="staples", unit="packet", is_loose=False,
        hsn_code="25010020", gst_slab=5, cost_price=Decimal("18.00"),
        sell_price=Decimal("22.00"), mrp=Decimal("24.00"), reorder_level=Decimal("5"),
    )
    found = inventory.find_product_by_name(name="tata salt 1kg")
    assert found is not None
    assert found.id == product_id


def test_find_product_by_name_returns_none_for_unknown(inventory):
    assert inventory.find_product_by_name(name="Nonexistent Product") is None


def test_find_product_by_name_raises_when_multiple_products_share_a_name(inventory):
    inventory.create_product(
        name="Duplicate Item", category="fmcg", unit="packet", is_loose=False,
        hsn_code="11111111", gst_slab=5, cost_price=Decimal("10.00"),
        sell_price=Decimal("12.00"), mrp=Decimal("15.00"), reorder_level=Decimal("5"),
    )
    inventory.create_product(
        name="Duplicate Item", category="fmcg", unit="packet", is_loose=False,
        hsn_code="22222222", gst_slab=5, cost_price=Decimal("20.00"),
        sell_price=Decimal("25.00"), mrp=Decimal("30.00"), reorder_level=Decimal("5"),
    )
    with pytest.raises(AmbiguousProductError):
        inventory.find_product_by_name(name="Duplicate Item")


def test_receive_stock_rejects_non_positive_qty(inventory):
    product_id = inventory.create_product(
        name="Fortune Oil 1L", category="staples", unit="packet", is_loose=False,
        hsn_code="15121900", gst_slab=5, cost_price=Decimal("140.00"),
        sell_price=Decimal("165.00"), mrp=Decimal("175.00"), reorder_level=Decimal("5"),
        initial_qty=Decimal("10"),
    )
    with pytest.raises(ValidationError):
        inventory.receive_stock(product_id=product_id, qty=Decimal("0"))


def test_list_products_returns_all_in_name_order(inventory):
    inventory.create_product(
        name="Zebra Soap", category="fmcg", unit="piece", is_loose=False,
        hsn_code="00000000", gst_slab=0, cost_price=Decimal("1"),
        sell_price=Decimal("2"), mrp=Decimal("2"), reorder_level=Decimal("1"),
    )
    inventory.create_product(
        name="Apple Juice", category="fmcg", unit="packet", is_loose=False,
        hsn_code="00000000", gst_slab=0, cost_price=Decimal("1"),
        sell_price=Decimal("2"), mrp=Decimal("2"), reorder_level=Decimal("1"),
    )
    products = inventory.list_products()
    names = [row[1] for row in products]
    assert names == sorted(names)
    assert names == ["Apple Juice", "Zebra Soap"]
