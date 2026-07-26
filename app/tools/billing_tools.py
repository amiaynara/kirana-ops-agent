import asyncio
from dataclasses import dataclass

from claude_agent_sdk import tool

from app.errors import DomainError
from app.tools.decimal_parsing import parse_decimal


@dataclass
class UpdateContext:
    current_update_id: str | None = None


def _format_draft(payment_mode, totals):
    if not totals.lines:
        mode = f" Payment mode: {payment_mode}." if payment_mode else ""
        return f"Bill is empty.{mode}"
    lines = [
        f"- {line.qty} x {line.product_name} @ {line.unit_price} "
        f"(CGST {line.cgst_amt} + SGST {line.sgst_amt}) = {line.line_total}"
        for line in totals.lines
    ]
    summary = (f"Subtotal {totals.subtotal}, CGST {totals.cgst_total}, "
               f"SGST {totals.sgst_total}, Grand total {totals.grand_total}")
    mode = f"\nPayment mode: {payment_mode}" if payment_mode else "\nPayment mode: not set yet"
    return "\n".join(lines) + f"\n{summary}{mode}"


def build_billing_tools(billing, inventory, chat_id: str, update_context: UpdateContext):
    async def _resolve_product(name):
        return await asyncio.to_thread(inventory.find_product_by_name, name=name)

    @tool("start_bill", "Start a new bill, clearing any prior unfinished draft for this chat.",
          {"payment_mode": str})
    async def start_bill(args):
        try:
            await asyncio.to_thread(
                billing.start_bill, chat_id=chat_id, payment_mode=args.get("payment_mode") or None,
            )
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        return {"content": [{"type": "text", "text": "Started a new bill."}]}

    @tool("add_bill_item", "Add a product line to the current bill, identified by exact product name.",
          {"product_name": str, "qty": str})
    async def add_bill_item(args):
        try:
            product = await _resolve_product(args["product_name"])
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        if product is None:
            return {"content": [{"type": "text", "text": f"No product found named {args['product_name']!r}."}],
                    "is_error": True}
        qty, error = parse_decimal(args["qty"], field_name="qty")
        if error is not None:
            return error
        try:
            await asyncio.to_thread(
                billing.add_item, chat_id=chat_id, product_id=product.id, qty=qty,
            )
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        return {"content": [{"type": "text", "text": f"Added {args['qty']} x {product.name}."}]}

    @tool("update_bill_item", "Change the quantity of a product already on the current bill.",
          {"product_name": str, "qty": str})
    async def update_bill_item(args):
        try:
            product = await _resolve_product(args["product_name"])
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        if product is None:
            return {"content": [{"type": "text", "text": f"No product found named {args['product_name']!r}."}],
                    "is_error": True}
        qty, error = parse_decimal(args["qty"], field_name="qty")
        if error is not None:
            return error
        try:
            await asyncio.to_thread(
                billing.update_item, chat_id=chat_id, product_id=product.id, qty=qty,
            )
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        return {"content": [{"type": "text", "text": f"Updated {product.name} to {args['qty']}."}]}

    @tool("drop_bill_item", "Remove a product line from the current bill.", {"product_name": str})
    async def drop_bill_item(args):
        try:
            product = await _resolve_product(args["product_name"])
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        if product is None:
            return {"content": [{"type": "text", "text": f"No product found named {args['product_name']!r}."}],
                    "is_error": True}
        try:
            await asyncio.to_thread(billing.drop_item, chat_id=chat_id, product_id=product.id)
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        return {"content": [{"type": "text", "text": f"Removed {product.name} from the bill."}]}

    @tool("get_bill_draft", "Show the current in-progress bill and its running GST-inclusive total.", {})
    async def get_bill_draft(args):
        try:
            payment_mode, totals = await asyncio.to_thread(billing.get_draft, chat_id=chat_id)
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        return {"content": [{"type": "text", "text": _format_draft(payment_mode, totals)}]}

    @tool("cancel_bill", "Discard the current in-progress bill entirely.", {})
    async def cancel_bill(args):
        try:
            await asyncio.to_thread(billing.cancel_bill, chat_id=chat_id)
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        return {"content": [{"type": "text", "text": "Bill discarded."}]}

    @tool(
        "finalize_bill",
        "Finalize the current bill: decrements stock and produces the final GST-inclusive total. "
        "Only call this when the owner has explicitly confirmed they want to complete the sale.",
        {"payment_mode": str, "payment_ref": str},
    )
    async def finalize_bill(args):
        update_id = update_context.current_update_id
        if update_id is None:
            return {"content": [{"type": "text", "text": "Internal error: no update id bound to this turn."}],
                    "is_error": True}
        try:
            bill_id, is_duplicate = await asyncio.to_thread(
                billing.finalize_bill, chat_id=chat_id, telegram_update_id=update_id,
                payment_mode=args.get("payment_mode") or None, payment_ref=args.get("payment_ref") or None,
            )
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        note = " (already finalized earlier, not billed again)" if is_duplicate else ""
        return {"content": [{"type": "text", "text": f"Bill #{bill_id} finalized{note}."}]}

    return [start_bill, add_bill_item, update_bill_item, drop_bill_item,
            get_bill_draft, cancel_bill, finalize_bill]
