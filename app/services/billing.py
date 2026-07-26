import json
from decimal import Decimal

from app.billing_math import BillLineInput, compute_bill_totals
from app.errors import LineNotFoundError, NoDraftBillError, ProductNotFoundError
from app.models import DraftBill, Product


class BillingService:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def start_bill(self, *, chat_id, payment_mode=None):
        with self._session_factory() as session:
            with session.begin():
                draft = session.get(DraftBill, chat_id)
                if draft is None:
                    draft = DraftBill(chat_id=chat_id, payload_json=json.dumps({"items": []}))
                    session.add(draft)
                else:
                    draft.payload_json = json.dumps({"items": []})
                draft.payment_mode = payment_mode

    def add_item(self, *, chat_id, product_id, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        with self._session_factory() as session:
            with session.begin():
                draft = session.get(DraftBill, chat_id)
                if draft is None:
                    raise NoDraftBillError(chat_id)
                product = session.get(Product, product_id)
                if product is None:
                    raise ProductNotFoundError(product_id)
                items = [item for item in json.loads(draft.payload_json)["items"]
                         if item["product_id"] != product_id]
                items.append({"product_id": product_id, "qty": str(qty)})
                draft.payload_json = json.dumps({"items": items})

    def update_item(self, *, chat_id, product_id, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        with self._session_factory() as session:
            with session.begin():
                draft = session.get(DraftBill, chat_id)
                if draft is None:
                    raise NoDraftBillError(chat_id)
                items = json.loads(draft.payload_json)["items"]
                for item in items:
                    if item["product_id"] == product_id:
                        item["qty"] = str(qty)
                        break
                else:
                    raise LineNotFoundError(product_id)
                draft.payload_json = json.dumps({"items": items})

    def drop_item(self, *, chat_id, product_id):
        with self._session_factory() as session:
            with session.begin():
                draft = session.get(DraftBill, chat_id)
                if draft is None:
                    raise NoDraftBillError(chat_id)
                items = json.loads(draft.payload_json)["items"]
                remaining = [item for item in items if item["product_id"] != product_id]
                if len(remaining) == len(items):
                    raise LineNotFoundError(product_id)
                draft.payload_json = json.dumps({"items": remaining})

    def cancel_bill(self, *, chat_id):
        with self._session_factory() as session:
            with session.begin():
                draft = session.get(DraftBill, chat_id)
                if draft is None:
                    raise NoDraftBillError(chat_id)
                session.delete(draft)

    def get_draft(self, *, chat_id):
        with self._session_factory() as session:
            draft = session.get(DraftBill, chat_id)
            if draft is None:
                raise NoDraftBillError(chat_id)
            items = json.loads(draft.payload_json)["items"]
            lines = []
            for item in items:
                product = session.get(Product, item["product_id"])
                if product is None:
                    raise ProductNotFoundError(item["product_id"])
                lines.append(BillLineInput(
                    product_id=product.id, product_name=product.name,
                    qty=Decimal(item["qty"]), unit_price=product.sell_price,
                    gst_slab=product.gst_slab,
                ))
            return draft.payment_mode, compute_bill_totals(lines)
