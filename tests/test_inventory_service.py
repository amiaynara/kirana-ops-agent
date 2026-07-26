from decimal import Decimal

import pytest

from app.db import Base, make_engine, make_session_factory
from app.errors import BelowCostError, ProductNotFoundError
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
    with pytest.raises(ValueError):
        inventory.create_product(
            name="Bad Unit", category="fmcg", unit="crate", is_loose=False,
            hsn_code="00000000", gst_slab=0, cost_price=Decimal("1"),
            sell_price=Decimal("2"), mrp=Decimal("2"), reorder_level=Decimal("1"),
        )


def test_create_product_rejects_unknown_gst_slab(inventory):
    with pytest.raises(ValueError):
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


def test_receive_stock_increments_qty(inventory):
    product_id = inventory.create_product(
        name="Fortune Oil 1L", category="staples", unit="packet", is_loose=False,
        hsn_code="15121900", gst_slab=5, cost_price=Decimal("140.00"),
        sell_price=Decimal("165.00"), mrp=Decimal("175.00"), reorder_level=Decimal("5"),
        initial_qty=Decimal("10"),
    )
    inventory.receive_stock(product_id=product_id, qty=Decimal("50"))
    assert inventory.get_stock(product_id=product_id) == Decimal("60")


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
