import asyncio

from claude_agent_sdk import tool

from app.errors import DomainError
from app.tools.decimal_parsing import parse_decimal


def build_khata_tools(khata):
    @tool(
        "credit_customer",
        "Add an amount to a customer's khata (credit) balance.",
        {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string"},
                "amount": {"type": "string"},
                "note": {"type": "string", "description": "Optional note, e.g. explaining a correction"},
            },
            "required": ["customer_name", "amount"],
        },
    )
    async def credit_customer(args):
        amount, error = parse_decimal(args["amount"], field_name="amount")
        if error is not None:
            return error
        try:
            await asyncio.to_thread(
                khata.credit_customer, customer_name=args["customer_name"], amount=amount,
                note=args.get("note") or None,
            )
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        return {"content": [{"type": "text",
                              "text": f"Put {args['amount']} on {args['customer_name']}'s khata."}]}

    @tool(
        "settle_khata",
        "Record a payment against a customer's existing khata balance.",
        {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string"},
                "amount": {"type": "string"},
                "note": {"type": "string", "description": "Optional note, e.g. explaining a correction"},
            },
            "required": ["customer_name", "amount"],
        },
    )
    async def settle_khata(args):
        amount, error = parse_decimal(args["amount"], field_name="amount")
        if error is not None:
            return error
        try:
            await asyncio.to_thread(
                khata.settle_khata, customer_name=args["customer_name"], amount=amount,
                note=args.get("note") or None,
            )
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        return {"content": [{"type": "text",
                              "text": f"{args['customer_name']} paid {args['amount']} off their khata."}]}

    @tool("get_khata_balance", "Look up a customer's current khata (credit) balance.",
          {"customer_name": str})
    async def get_khata_balance(args):
        try:
            balance = await asyncio.to_thread(khata.get_balance, customer_name=args["customer_name"])
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        return {"content": [{"type": "text", "text": f"{args['customer_name']}'s khata balance: {balance}"}]}

    @tool("list_customers", "List every customer known to the store's khata ledger.", {})
    async def list_customers(args):
        rows = await asyncio.to_thread(khata.list_customers)
        if not rows:
            return {"content": [{"type": "text", "text": "No customers on the khata ledger yet."}]}
        lines = [f"- {name}" for _, name in rows]
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    return [credit_customer, settle_khata, get_khata_balance, list_customers]
