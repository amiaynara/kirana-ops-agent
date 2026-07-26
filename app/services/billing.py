import json
from decimal import Decimal

from app.billing_math import BillLineInput, compute_bill_totals
from app.errors import (
    InsufficientStockError,
    LineNotFoundError,
    MissingPaymentModeError,
    NoDraftBillError,
    ProductNotFoundError,
    ValidationError,
)
from app.models import Bill, BillItem, DraftBill, Product, ProcessedUpdate, StockMovement


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
            raise ValidationError("qty must be positive")
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
            raise ValidationError("qty must be positive")
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

    def finalize_bill(self, *, chat_id, telegram_update_id, payment_mode=None, payment_ref=None):
        with self._session_factory() as session:
            with session.begin():
                existing = session.get(ProcessedUpdate, telegram_update_id)
                if existing is not None and existing.bill_id is not None:
                    return existing.bill_id, True

                draft = session.get(DraftBill, chat_id)
                if draft is None:
                    raise NoDraftBillError(chat_id)
                items = json.loads(draft.payload_json)["items"]
                if not items:
                    raise NoDraftBillError(chat_id)

                resolved_mode = payment_mode or draft.payment_mode
                if not resolved_mode:
                    raise MissingPaymentModeError(chat_id)

                lines = []
                products_by_id = {}
                for item in items:
                    product = session.get(Product, item["product_id"])
                    if product is None:
                        raise ProductNotFoundError(item["product_id"])
                    products_by_id[product.id] = product
                    lines.append(BillLineInput(
                        product_id=product.id, product_name=product.name,
                        qty=Decimal(item["qty"]), unit_price=product.sell_price,
                        gst_slab=product.gst_slab,
                    ))

                # Validate every line before writing any of them. Note: this
                # validate-then-write ordering is defense in depth, not the
                # source of the atomicity guarantee. The actual guarantee that
                # no partial writes are ever persisted comes from this whole
                # method running inside a single `session.begin()` block
                # (opened above) — any exception raised anywhere in this
                # block, including mid-way through the write loop below, rolls
                # back everything written so far.
                for line in lines:
                    product = products_by_id[line.product_id]
                    if product.qty_on_hand < line.qty:
                        raise InsufficientStockError(product.name, line.qty, product.qty_on_hand)

                totals = compute_bill_totals(lines)

                bill = Bill(
                    chat_id=chat_id, status="finalized", payment_mode=resolved_mode,
                    payment_ref=payment_ref, subtotal=totals.subtotal,
                    cgst_total=totals.cgst_total, sgst_total=totals.sgst_total,
                    grand_total=totals.grand_total, idempotency_key=telegram_update_id,
                )
                session.add(bill)
                session.flush()

                for line_result in totals.lines:
                    session.add(BillItem(
                        bill_id=bill.id, product_id=line_result.product_id,
                        qty=line_result.qty, unit_price=line_result.unit_price,
                        gst_slab=line_result.gst_slab, cgst_amt=line_result.cgst_amt,
                        sgst_amt=line_result.sgst_amt, line_total=line_result.line_total,
                    ))
                    product = products_by_id[line_result.product_id]
                    product.qty_on_hand -= line_result.qty
                    session.add(StockMovement(
                        product_id=product.id, delta=-line_result.qty,
                        reason="sale", ref_bill_id=bill.id,
                    ))

                if existing is not None:
                    existing.bill_id = bill.id
                else:
                    session.add(ProcessedUpdate(telegram_update_id=telegram_update_id, bill_id=bill.id))
                session.delete(draft)

                return bill.id, False
