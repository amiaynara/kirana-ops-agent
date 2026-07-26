from decimal import Decimal

from app.config import load_settings
from app.db import Base, make_engine, make_session_factory
from app.services.inventory import InventoryService

SEED_PRODUCTS = [
    dict(name="Aashirvaad Atta 5kg", category="staples", unit="packet", is_loose=False,
         hsn_code="11010000", gst_slab=0, cost_price=Decimal("220.00"),
         sell_price=Decimal("250.00"), mrp=Decimal("260.00"),
         reorder_level=Decimal("5"), initial_qty=Decimal("20")),
    dict(name="Tata Salt 1kg", category="staples", unit="packet", is_loose=False,
         hsn_code="25010020", gst_slab=5, cost_price=Decimal("18.00"),
         sell_price=Decimal("22.00"), mrp=Decimal("24.00"),
         reorder_level=Decimal("10"), initial_qty=Decimal("40")),
    dict(name="Amul Butter 100g", category="dairy", unit="packet", is_loose=False,
         hsn_code="04051000", gst_slab=12, cost_price=Decimal("48.00"),
         sell_price=Decimal("58.00"), mrp=Decimal("62.00"),
         reorder_level=Decimal("10"), initial_qty=Decimal("30")),
    dict(name="Fortune Sunflower Oil 1L", category="staples", unit="packet", is_loose=False,
         hsn_code="15121900", gst_slab=5, cost_price=Decimal("140.00"),
         sell_price=Decimal("165.00"), mrp=Decimal("175.00"),
         reorder_level=Decimal("5"), initial_qty=Decimal("15")),
    dict(name="Maggi 70g", category="fmcg", unit="packet", is_loose=False,
         hsn_code="19023090", gst_slab=12, cost_price=Decimal("10.00"),
         sell_price=Decimal("14.00"), mrp=Decimal("14.00"),
         reorder_level=Decimal("20"), initial_qty=Decimal("100")),
    dict(name="Parle-G", category="fmcg", unit="packet", is_loose=False,
         hsn_code="19053100", gst_slab=5, cost_price=Decimal("8.00"),
         sell_price=Decimal("10.00"), mrp=Decimal("10.00"),
         reorder_level=Decimal("20"), initial_qty=Decimal("100")),
    dict(name="Surf Excel 1kg", category="fmcg", unit="packet", is_loose=False,
         hsn_code="34022090", gst_slab=18, cost_price=Decimal("95.00"),
         sell_price=Decimal("115.00"), mrp=Decimal("125.00"),
         reorder_level=Decimal("5"), initial_qty=Decimal("15")),
    dict(name="Sugar (loose)", category="staples", unit="kg", is_loose=True,
         hsn_code="17019900", gst_slab=0, cost_price=Decimal("38.00"),
         sell_price=Decimal("44.00"), mrp=Decimal("44.00"),
         reorder_level=Decimal("10"), initial_qty=Decimal("50")),
    dict(name="Rice (loose)", category="staples", unit="kg", is_loose=True,
         hsn_code="10063090", gst_slab=0, cost_price=Decimal("42.00"),
         sell_price=Decimal("48.00"), mrp=Decimal("48.00"),
         reorder_level=Decimal("10"), initial_qty=Decimal("50")),
    dict(name="Toor Dal (loose)", category="staples", unit="kg", is_loose=True,
         hsn_code="07136000", gst_slab=0, cost_price=Decimal("95.00"),
         sell_price=Decimal("108.00"), mrp=Decimal("108.00"),
         reorder_level=Decimal("10"), initial_qty=Decimal("30")),
]


def seed(session_factory):
    inventory = InventoryService(session_factory)
    created = []
    for spec in SEED_PRODUCTS:
        product_id = inventory.create_product(**spec)
        created.append((product_id, spec["name"]))
    return created


def main():
    settings = load_settings()
    engine = make_engine(settings.db_path)
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    for product_id, name in seed(session_factory):
        print(f"seeded #{product_id}: {name}")


if __name__ == "__main__":
    main()
