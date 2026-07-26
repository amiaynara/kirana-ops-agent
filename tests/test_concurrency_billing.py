import threading
from decimal import Decimal

from app.db import Base, make_engine, make_session_factory
from app.errors import InsufficientStockError
from app.models import Product
from app.services.billing import BillingService
from app.services.inventory import InventoryService


def test_concurrent_finalize_does_not_oversell(tmp_path):
    engine = make_engine(str(tmp_path / "concurrency_billing.db"))
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    inventory = InventoryService(Session)
    billing = BillingService(Session)

    product_id = inventory.create_product(
        name="Aashirvaad Atta 5kg", category="staples", unit="packet", is_loose=False,
        hsn_code="11010000", gst_slab=0, cost_price=Decimal("220.00"),
        sell_price=Decimal("250.00"), mrp=Decimal("260.00"),
        reorder_level=Decimal("5"), initial_qty=Decimal("1"),
    )

    for chat_id in ("chat-a", "chat-b"):
        billing.start_bill(chat_id=chat_id, payment_mode="cash")
        billing.add_item(chat_id=chat_id, product_id=product_id, qty=Decimal("1"))

    results = {}
    errors = {}

    def finalize(chat_id, update_id):
        try:
            results[chat_id] = billing.finalize_bill(chat_id=chat_id, telegram_update_id=update_id)
        except Exception as exc:  # noqa: BLE001 - capturing the failure mode under test
            errors[chat_id] = exc

    t_a = threading.Thread(target=finalize, args=("chat-a", "update-a"))
    t_b = threading.Thread(target=finalize, args=("chat-b", "update-b"))
    t_a.start()
    t_b.start()
    t_a.join(timeout=10)
    t_b.join(timeout=10)

    assert len(results) == 1, f"expected exactly one success, got {results}"
    assert len(errors) == 1, f"expected exactly one refusal, got {errors}"
    assert isinstance(list(errors.values())[0], InsufficientStockError)

    with Session() as session:
        product = session.get(Product, product_id)
        assert product.qty_on_hand == Decimal("0"), "stock must never go negative or double-decrement"


def test_concurrent_receive_stock_and_finalize_do_not_lose_updates(tmp_path):
    engine = make_engine(str(tmp_path / "concurrency_mixed.db"))
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    inventory = InventoryService(Session)
    billing = BillingService(Session)

    product_id = inventory.create_product(
        name="Maggi 70g", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19023090", gst_slab=12, cost_price=Decimal("10.00"),
        sell_price=Decimal("14.00"), mrp=Decimal("14.00"),
        reorder_level=Decimal("20"), initial_qty=Decimal("10"),
    )
    billing.start_bill(chat_id="chat-c", payment_mode="cash")
    billing.add_item(chat_id="chat-c", product_id=product_id, qty=Decimal("4"))

    errors = {}

    def receive():
        try:
            inventory.receive_stock(product_id=product_id, qty=Decimal("50"))
        except Exception as exc:  # noqa: BLE001 - capturing the failure mode under test
            errors["receive"] = exc

    def finalize():
        try:
            billing.finalize_bill(chat_id="chat-c", telegram_update_id="update-c")
        except Exception as exc:  # noqa: BLE001 - capturing the failure mode under test
            errors["finalize"] = exc

    t1 = threading.Thread(target=receive)
    t2 = threading.Thread(target=finalize)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"concurrent stock-in + sale raised: {errors}"
    with Session() as session:
        product = session.get(Product, product_id)
        assert product.qty_on_hand == Decimal("56")  # 10 + 50 - 4, regardless of interleaving order
