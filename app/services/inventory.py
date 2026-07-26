from decimal import Decimal

from sqlalchemy import func

from app.errors import (
    AmbiguousProductError,
    BelowCostError,
    ProductNotFoundError,
    ValidationError,
)
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
            raise ValidationError(f"unit must be one of {sorted(ALLOWED_UNITS)}, got {unit!r}")
        if gst_slab not in ALLOWED_GST_SLABS:
            raise ValidationError(f"gst_slab must be one of {sorted(ALLOWED_GST_SLABS)}, got {gst_slab!r}")
        if sell_price < cost_price:
            raise BelowCostError(sell_price, cost_price)
        if initial_qty < 0:
            raise ValidationError("initial_qty must not be negative")

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
            raise ValidationError("qty must be positive")
        with self._session_factory() as session:
            with session.begin():
                product = session.get(Product, product_id)
                if product is None:
                    raise ProductNotFoundError(product_id)
                if cost_price is not None:
                    effective_sell_price = product.sell_price
                    if effective_sell_price < cost_price:
                        raise BelowCostError(effective_sell_price, cost_price)
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

    def find_product_by_name(self, *, name):
        # Returns the ORM Product itself (not a tuple) since callers need the
        # full product (id, price, gst_slab, stock) to reason about a single
        # named product. Do not touch the returned object after the session
        # factory's context has closed.
        with self._session_factory() as session:
            matches = session.query(Product).filter(
                func.lower(Product.name) == name.lower()
            ).all()
            if not matches:
                return None
            if len(matches) == 1:
                return matches[0]
            raise AmbiguousProductError(name, [p.id for p in matches])

    def list_products(self):
        with self._session_factory() as session:
            products = session.query(Product).order_by(Product.name).all()
            return [(p.id, p.name, p.unit, p.sell_price, p.gst_slab) for p in products]
