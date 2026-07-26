from decimal import Decimal

from app.errors import BelowCostError, ProductNotFoundError
from app.models import Product, StockMovement

ALLOWED_UNITS = {"kg", "g", "litre", "ml", "packet", "dozen", "piece"}
ALLOWED_GST_SLABS = {0, 5, 12, 18, 28}


class InventoryService:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def create_product(
        self, *, name, category, unit, is_loose, hsn_code, gst_slab,
        cost_price, sell_price, mrp, reorder_level, initial_qty=Decimal("0"),
    ):
        if unit not in ALLOWED_UNITS:
            raise ValueError(f"unit must be one of {sorted(ALLOWED_UNITS)}, got {unit!r}")
        if gst_slab not in ALLOWED_GST_SLABS:
            raise ValueError(f"gst_slab must be one of {sorted(ALLOWED_GST_SLABS)}, got {gst_slab!r}")
        if sell_price < cost_price:
            raise BelowCostError(sell_price, cost_price)
        if initial_qty < 0:
            raise ValueError("initial_qty must not be negative")

        with self._session_factory() as session:
            with session.begin():
                product = Product(
                    name=name, category=category, unit=unit, is_loose=is_loose,
                    hsn_code=hsn_code, gst_slab=gst_slab,
                    cost_price=cost_price, sell_price=sell_price, mrp=mrp,
                    qty_on_hand=initial_qty, reorder_level=reorder_level,
                )
                session.add(product)
                session.flush()
                product_id = product.id
                if initial_qty > 0:
                    session.add(StockMovement(product_id=product_id, delta=initial_qty, reason="purchase"))
            return product_id

    def receive_stock(self, *, product_id, qty, cost_price=None, mrp=None):
        if qty <= 0:
            raise ValueError("qty must be positive")
        with self._session_factory() as session:
            with session.begin():
                product = session.get(Product, product_id)
                if product is None:
                    raise ProductNotFoundError(product_id)
                product.qty_on_hand += qty
                if cost_price is not None:
                    product.cost_price = cost_price
                if mrp is not None:
                    product.mrp = mrp
                session.add(StockMovement(product_id=product_id, delta=qty, reason="purchase"))

    def get_stock(self, *, product_id):
        with self._session_factory() as session:
            product = session.get(Product, product_id)
            if product is None:
                raise ProductNotFoundError(product_id)
            return product.qty_on_hand

    def list_low_stock(self):
        with self._session_factory() as session:
            products = session.query(Product).filter(
                Product.qty_on_hand <= Product.reorder_level
            ).all()
            return [(p.id, p.name, p.qty_on_hand, p.reorder_level) for p in products]
