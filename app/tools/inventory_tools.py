import asyncio
from decimal import Decimal

from claude_agent_sdk import tool

from app.errors import DomainError
from app.services.inventory import InventoryService
from app.tools.decimal_parsing import parse_decimal


def build_inventory_tools(inventory: InventoryService):
    @tool("get_stock", "Look up current stock quantity for a product by its exact name.",
          {"product_name": str})
    async def get_stock(args):
        try:
            product = await asyncio.to_thread(inventory.find_product_by_name, name=args["product_name"])
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        if product is None:
            return {"content": [{"type": "text", "text": f"No product found named {args['product_name']!r}."}],
                    "is_error": True}
        return {"content": [{"type": "text",
                              "text": f"{product.name}: {product.qty_on_hand} {product.unit} in stock."}]}

    @tool("list_low_stock", "List every product at or below its reorder level.", {})
    async def list_low_stock(args):
        rows = await asyncio.to_thread(inventory.list_low_stock)
        if not rows:
            return {"content": [{"type": "text", "text": "Nothing is low on stock."}]}
        lines = [f"- {name}: {qty} left (reorder at {reorder})" for _, name, qty, reorder in rows]
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool("list_products", "List every product in the store with its unit, sell price, and GST slab.", {})
    async def list_products(args):
        rows = await asyncio.to_thread(inventory.list_products)
        if not rows:
            return {"content": [{"type": "text", "text": "No products in the store yet."}]}
        lines = [f"- {name} ({unit}): sell price {sell_price}, GST {gst_slab}%"
                 for _, name, unit, sell_price, gst_slab in rows]
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "receive_stock",
        "Record newly received stock for an existing product, identified by exact name.",
        {
            "type": "object",
            "properties": {
                "product_name": {"type": "string"},
                "qty": {"type": "string", "description": "Decimal quantity as a string, e.g. '50'"},
                "cost_price": {"type": "string", "description": "New cost price as a decimal string, optional"},
            },
            "required": ["product_name", "qty"],
        },
    )
    async def receive_stock(args):
        try:
            product = await asyncio.to_thread(inventory.find_product_by_name, name=args["product_name"])
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        if product is None:
            return {"content": [{"type": "text", "text": f"No product found named {args['product_name']!r}."}],
                    "is_error": True}
        qty, error = parse_decimal(args["qty"], field_name="qty")
        if error is not None:
            return error
        cost_price = None
        if args.get("cost_price"):
            cost_price, error = parse_decimal(args["cost_price"], field_name="cost_price")
            if error is not None:
                return error
        try:
            await asyncio.to_thread(
                inventory.receive_stock,
                product_id=product.id,
                qty=qty,
                cost_price=cost_price,
            )
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        return {"content": [{"type": "text",
                              "text": f"Received {args['qty']} {product.unit} of {product.name}."}]}

    @tool(
        "create_product",
        "Register a brand-new product/SKU in the store.",
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "category": {"type": "string"},
                "unit": {"type": "string", "enum": ["kg", "g", "litre", "ml", "packet", "dozen", "piece"]},
                "is_loose": {"type": "boolean"},
                "hsn_code": {"type": "string"},
                "gst_slab": {"type": "integer", "enum": [0, 5, 12, 18, 28]},
                "cost_price": {"type": "string"},
                "sell_price": {"type": "string"},
                "mrp": {"type": "string"},
                "reorder_level": {"type": "string"},
                "initial_qty": {"type": "string", "description": "Optional starting stock, decimal string"},
            },
            "required": ["name", "category", "unit", "is_loose", "hsn_code", "gst_slab",
                          "cost_price", "sell_price", "mrp", "reorder_level"],
        },
    )
    async def create_product(args):
        cost_price, error = parse_decimal(args["cost_price"], field_name="cost_price")
        if error is not None:
            return error
        sell_price, error = parse_decimal(args["sell_price"], field_name="sell_price")
        if error is not None:
            return error
        mrp, error = parse_decimal(args["mrp"], field_name="mrp")
        if error is not None:
            return error
        reorder_level, error = parse_decimal(args["reorder_level"], field_name="reorder_level")
        if error is not None:
            return error
        initial_qty = Decimal("0")
        if args.get("initial_qty"):
            initial_qty, error = parse_decimal(args["initial_qty"], field_name="initial_qty")
            if error is not None:
                return error
        try:
            product_id = await asyncio.to_thread(
                inventory.create_product,
                name=args["name"], category=args["category"], unit=args["unit"],
                is_loose=args["is_loose"], hsn_code=args["hsn_code"], gst_slab=args["gst_slab"],
                cost_price=cost_price, sell_price=sell_price,
                mrp=mrp, reorder_level=reorder_level,
                initial_qty=initial_qty,
            )
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        return {"content": [{"type": "text", "text": f"Created {args['name']} (product id {product_id})."}]}

    return [get_stock, list_low_stock, list_products, receive_stock, create_product]
