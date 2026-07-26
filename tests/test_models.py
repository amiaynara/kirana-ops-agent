from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.db import Base, make_engine, make_session_factory
from app.models import Bill, BillItem, Product


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(str(tmp_path / "models.db"))
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def test_create_all_creates_every_table(tmp_path):
    engine = make_engine(str(tmp_path / "models.db"))
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    expected = {
        "products", "customers", "khata_ledger", "draft_bills",
        "bills", "bill_items", "stock_movements",
        "owner_preferences", "processed_updates",
    }
    assert expected.issubset(tables)


def test_product_defaults(session_factory):
    with session_factory() as session:
        with session.begin():
            product = Product(
                name="Tata Salt 1kg", category="staples", unit="packet",
                hsn_code="25010020", gst_slab=5,
                cost_price=Decimal("18.00"), sell_price=Decimal("22.00"), mrp=Decimal("24.00"),
            )
            session.add(product)
        session.refresh(product)
        assert product.is_loose is False
        assert product.qty_on_hand == Decimal("0")


def test_bill_idempotency_key_is_unique(session_factory):
    with session_factory() as session:
        with session.begin():
            session.add(Bill(
                chat_id="chat-1", status="finalized", payment_mode="upi",
                subtotal=Decimal("100.00"), cgst_total=Decimal("2.50"),
                sgst_total=Decimal("2.50"), grand_total=Decimal("105.00"),
                idempotency_key="update-1",
            ))
    with pytest.raises(IntegrityError):
        with session_factory() as session:
            with session.begin():
                session.add(Bill(
                    chat_id="chat-2", status="finalized", payment_mode="cash",
                    subtotal=Decimal("50.00"), cgst_total=Decimal("0"),
                    sgst_total=Decimal("0"), grand_total=Decimal("50.00"),
                    idempotency_key="update-1",
                ))


def test_bill_item_requires_existing_bill(session_factory):
    with session_factory() as session:
        with session.begin():
            product = Product(
                name="Maggi 70g", category="fmcg", unit="packet",
                hsn_code="19023090", gst_slab=12,
                cost_price=Decimal("10.00"), sell_price=Decimal("14.00"), mrp=Decimal("14.00"),
            )
            session.add(product)
            session.flush()
            product_id = product.id
    with pytest.raises(IntegrityError):
        with session_factory() as session:
            with session.begin():
                session.add(BillItem(
                    bill_id=9999, product_id=product_id, qty=Decimal("1"),
                    unit_price=Decimal("14.00"), gst_slab=12,
                    cgst_amt=Decimal("0.84"), sgst_amt=Decimal("0.84"), line_total=Decimal("15.68"),
                ))
