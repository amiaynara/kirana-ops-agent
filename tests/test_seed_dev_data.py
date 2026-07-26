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
