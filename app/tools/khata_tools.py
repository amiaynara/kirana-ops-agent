import asyncio
from decimal import Decimal

from claude_agent_sdk import tool

from app.errors import DomainError


def build_khata_tools(khata):
    @tool("credit_customer", "Add an amount to a customer's khata (credit) balance.",
          {"customer_name": str, "amount": str})
    async def credit_customer(args):
        try:
            await asyncio.to_thread(
                khata.credit_customer, customer_name=args["customer_name"], amount=Decimal(args["amount"]),
            )
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        return {"content": [{"type": "text",
                              "text": f"Put {args['amount']} on {args['customer_name']}'s khata."}]}

    @tool("settle_khata", "Record a payment against a customer's existing khata balance.",
          {"customer_name": str, "amount": str})
    async def settle_khata(args):
        try:
            await asyncio.to_thread(
                khata.settle_khata, customer_name=args["customer_name"], amount=Decimal(args["amount"]),
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

    return [credit_customer, settle_khata, get_khata_balance]
