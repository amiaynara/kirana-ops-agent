from decimal import Decimal

from app.db import Base, make_engine, make_session_factory
from app.services.inventory import InventoryService
from scripts.seed_dev_data import SEED_PRODUCTS, seed


def test_seed_creates_all_products_with_positive_stock(tmp_path):
    engine = make_engine(str(tmp_path / "seed.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    created = seed(session_factory)

    assert len(created) == len(SEED_PRODUCTS)
    inventory = InventoryService(session_factory)
    for product_id, name in created:
        qty = inventory.get_stock(product_id=product_id)
        assert qty > Decimal("0"), f"{name} seeded with zero stock"


# Real, published GST slabs for each seeded SKU -- this is the guardrail a
# wrong-but-schema-valid slab (e.g. Aashirvaad Atta shipped at 0% instead of
# the correct 5%) would otherwise slip straight past: `gst_slab in {0,5,12,
# 18,28}` is satisfied by ANY of these values, so only checking that a slab
# is *one of the valid five* can never catch "valid but wrong for this SKU".
EXPECTED_GST_SLABS = {
    "Aashirvaad Atta 5kg": 5,       # branded/packaged atta in a unit container -> 5%, not nil
    "Tata Salt 1kg": 0,             # salt (HSN 2501) is nil-rated regardless of branding
    "Amul Butter 100g": 12,         # dairy butter
    "Fortune Sunflower Oil 1L": 5,  # edible/vegetable oil
    "Maggi 70g": 12,                # packaged instant noodles
    "Parle-G": 5,                   # biscuits <= Rs 100/kg
    "Surf Excel 1kg": 18,           # detergent
    "Sugar (loose)": 0,             # loose/unbranded
    "Rice (loose)": 0,              # loose/unbranded
    "Toor Dal (loose)": 0,          # loose/unbranded pulses
}


def test_seed_products_have_the_real_published_gst_slab(tmp_path):
    assert set(EXPECTED_GST_SLABS) == {p["name"] for p in SEED_PRODUCTS}, (
        "EXPECTED_GST_SLABS is out of sync with SEED_PRODUCTS -- update both together"
    )
    for spec in SEED_PRODUCTS:
        expected = EXPECTED_GST_SLABS[spec["name"]]
        assert spec["gst_slab"] == expected, (
            f"{spec['name']}: seeded at {spec['gst_slab']}% GST, "
            f"real published rate is {expected}%"
        )
