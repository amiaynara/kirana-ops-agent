# Phase 2 — Tools, Skills, Agent Core, CLI Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Phase 1's services into a real, running Claude Agent SDK session reachable from a local CLI — no Telegram dependency yet, per the local-first roadmap priority.

**Architecture:** One `ClaudeSDKClient` per chat (`AgentSession`), holding conversation state across turns. Each domain's tools are built as plain lists of `SdkMcpTool` objects (via `@tool`) by a `build_*_tools()` factory closing over that domain's Service instance — this keeps every tool handler directly unit-testable (call `.handler(args)` on the returned object) without spinning up the SDK. `AgentSession` merges all four domains' tools into one in-process MCP server, restricts the built-in tool surface to nothing but `Skill` (no `Bash`/`Edit`/`Write`/`Task` — this is a shopkeeper bot, not a coding agent), and injects the owner's standing preferences into the system prompt fresh at every session construction (so `/new` clears conversation but not memory). Skills load from `.claude/skills/*/SKILL.md` via `setting_sources=["project"]`.

**Tech Stack:** `claude-agent-sdk` (Python, verified installed version `0.2.128`), asyncio, the Phase 1 service layer.

## Global Constraints

- Python >= 3.11 (unchanged from Phase 0/1)
- All money/quantity values cross the tool boundary as **decimal strings** (`"2.5"`, not JSON numbers) to avoid float precision loss — parsed via `Decimal(...)` inside each handler
- `chat_id` is NEVER a tool parameter the model supplies — it is closed over by the tool factory at `AgentSession` construction time, since it identifies which Telegram/CLI conversation this is, not something the LLM chooses
- `telegram_update_id` (needed only by `finalize_bill`, for idempotency) is supplied by the channel layer per-message via a shared mutable `UpdateContext`, not by the model — see Task 3
- Every tool that calls into a service catches `DomainError` and returns `{"content": [...], "is_error": True}` with the refusal message relayed verbatim — never let a `DomainError` propagate past the tool boundary
- `ClaudeAgentOptions` for this bot MUST set `tools=["Skill"]` (verified: default `tools=None` exposes the full Claude Code built-in toolset including `Bash`/`Edit`/`Write`/`Task` — unacceptable for a hosted shopkeeper bot) and `strict_mcp_config=True` (ignore any ambient MCP config on the host)
- No placeholder/TODO code

## Verified SDK Behavior (confirmed by live testing before this plan was written, not assumed from docs)

- Package: `claude-agent-sdk==0.2.128`. `ClaudeSDKClient(options).connect()` → repeated `.query(text)` + `async for msg in .receive_response()` → `.disconnect()` genuinely holds multi-turn conversation state (verified: a 3-turn exchange where turn 3 correctly recalled items added in turns 1 and 2).
- `@tool(name, description, input_schema)` — `input_schema` may be a simple `{"param": type}` dict (all-required) or a full JSON Schema dict (needed for optional params via `"required": [...]`). Returns an `SdkMcpTool` with a `.handler` attribute — the plain async function — directly callable in tests without going through the SDK's dispatch.
- `create_sdk_mcp_server(name, version, tools=[...])` returns an `McpSdkServerConfig` for `ClaudeAgentOptions.mcp_servers`.
- **`ClaudeAgentOptions(tools=None)` (the default) exposes the FULL Claude Code built-in tool suite** (`Bash`, `Edit`, `Write`, `Task`, etc.) alongside any custom MCP tools — confirmed via a live `SystemMessage(subtype='init')` listing all of them. `tools=[]` disables all built-ins. `tools=["Skill"]` enables only the `Skill` tool (needed for Skills to actually be invocable — confirmed `tools=[]` silently prevents Skill invocation even with `setting_sources=["project"]` and `skills="all"` set).
- `setting_sources=["project"]` + `skills="all"` + `tools=["Skill"]` + `cwd=<repo root>` — confirmed a project-level `.claude/skills/<name>/SKILL.md` is discovered and actually invoked by the model (verified with a throwaway skill whose instructions were followed).
- No `ANTHROPIC_API_KEY` was required in this dev environment because the ambient `claude` CLI (which the SDK shells out to as its transport) was already authenticated. **A Fly.io deployment container will need its own auth** — either `ANTHROPIC_API_KEY` set as a secret, or the CLI logged in some other way. This is a Phase 5 concern, not a code change here.
- Cost/tool-surface note: the default options (ambient hooks, full built-in tool suite) cost ~$0.32 for one trivial exchange in this dev environment (loading unrelated global Claude Code config); the locked-down config this plan uses (`tools=["Skill"]`, `strict_mcp_config=True`, `setting_sources=["project"]`) cost ~$0.006 for the same exchange. Always use the locked-down config.

---

### Task 1: `claude-agent-sdk` dependency + `PreferencesService`

**Files:**
- Modify: `pyproject.toml` (add dependency)
- Create: `app/services/preferences.py`
- Test: `tests/test_preferences_service.py`

**Interfaces:**
- Consumes: `OwnerPreference` from `app.models`
- Produces: `PreferencesService(session_factory)` with `get_preference(*, key, default=None) -> str | None`, `set_preference(*, key, value) -> None`, `get_all_preferences() -> dict[str, str]`

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`'s `dependencies` list, add (it is already installed in the venv from manual verification, this just declares it):
```toml
    "claude-agent-sdk>=0.2.128,<0.3.0",
```

Run: `pip install -e ".[dev]"` to confirm it resolves cleanly.

- [ ] **Step 2: Write the failing test**

`tests/test_preferences_service.py`:
```python
from app.db import Base, make_engine, make_session_factory
from app.services.preferences import PreferencesService


def _make_service(tmp_path):
    engine = make_engine(str(tmp_path / "prefs.db"))
    Base.metadata.create_all(engine)
    return PreferencesService(make_session_factory(engine))


def test_get_preference_returns_default_when_unset(tmp_path):
    prefs = _make_service(tmp_path)
    assert prefs.get_preference(key="default_payment_mode") is None
    assert prefs.get_preference(key="default_payment_mode", default="cash") == "cash"


def test_set_then_get_preference(tmp_path):
    prefs = _make_service(tmp_path)
    prefs.set_preference(key="default_payment_mode", value="upi")
    assert prefs.get_preference(key="default_payment_mode") == "upi"


def test_set_preference_updates_existing(tmp_path):
    prefs = _make_service(tmp_path)
    prefs.set_preference(key="shop_name", value="Sharma Kirana Store")
    prefs.set_preference(key="shop_name", value="Sharma General Store")
    assert prefs.get_preference(key="shop_name") == "Sharma General Store"


def test_get_all_preferences_returns_all_as_dict(tmp_path):
    prefs = _make_service(tmp_path)
    prefs.set_preference(key="default_payment_mode", value="upi")
    prefs.set_preference(key="shop_name", value="Sharma Kirana Store")
    assert prefs.get_all_preferences() == {
        "default_payment_mode": "upi",
        "shop_name": "Sharma Kirana Store",
    }
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_preferences_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.preferences'`

- [ ] **Step 4: Write minimal implementation**

`app/services/preferences.py`:
```python
from app.models import OwnerPreference


class PreferencesService:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def get_preference(self, *, key, default=None):
        with self._session_factory() as session:
            pref = session.get(OwnerPreference, key)
            return pref.value if pref is not None else default

    def set_preference(self, *, key, value):
        with self._session_factory() as session:
            with session.begin():
                pref = session.get(OwnerPreference, key)
                if pref is None:
                    session.add(OwnerPreference(key=key, value=value))
                else:
                    pref.value = value

    def get_all_preferences(self):
        with self._session_factory() as session:
            prefs = session.query(OwnerPreference).order_by(OwnerPreference.key).all()
            return {p.key: p.value for p in prefs}
```

- [ ] **Step 5: Run test to verify it passes, then full suite**

Run: `pytest tests/test_preferences_service.py -v` — expect 4 passed
Run: `pytest -v` — expect 74 passed (70 from Phase 1 + 4 new)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml app/services/preferences.py tests/test_preferences_service.py
git commit -m "feat: add claude-agent-sdk dependency and PreferencesService"
```

---

### Task 2: Inventory tools

**Files:**
- Create: `app/tools/__init__.py`
- Create: `app/tools/inventory_tools.py`
- Test: `tests/test_inventory_tools.py`

**Interfaces:**
- Consumes: `InventoryService` from `app.services.inventory`; `DomainError` from `app.errors`
- Produces: `build_inventory_tools(inventory: InventoryService) -> list[SdkMcpTool]` — 5 tools: `get_stock`, `list_low_stock`, `list_products`, `receive_stock`, `create_product`. Each `SdkMcpTool.handler` is `async def handler(args: dict) -> dict`, directly callable in tests via `asyncio.run(handler(args))`.

- [ ] **Step 1: Write the failing test**

`tests/test_inventory_tools.py`:
```python
import asyncio
from decimal import Decimal

from app.db import Base, make_engine, make_session_factory
from app.services.inventory import InventoryService
from app.tools.inventory_tools import build_inventory_tools


def _make_inventory(tmp_path):
    engine = make_engine(str(tmp_path / "inv_tools.db"))
    Base.metadata.create_all(engine)
    return InventoryService(make_session_factory(engine))


def _tools_by_name(inventory):
    return {t.name: t for t in build_inventory_tools(inventory)}


def test_get_stock_reports_quantity_for_known_product(tmp_path):
    inventory = _make_inventory(tmp_path)
    inventory.create_product(
        name="Tata Salt 1kg", category="staples", unit="packet", is_loose=False,
        hsn_code="25010020", gst_slab=5, cost_price=Decimal("18.00"),
        sell_price=Decimal("22.00"), mrp=Decimal("24.00"), reorder_level=Decimal("5"),
        initial_qty=Decimal("40"),
    )
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["get_stock"].handler({"product_name": "Tata Salt 1kg"}))
    assert not result.get("is_error")
    assert "40" in result["content"][0]["text"]


def test_get_stock_is_error_for_unknown_product(tmp_path):
    inventory = _make_inventory(tmp_path)
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["get_stock"].handler({"product_name": "Nonexistent"}))
    assert result.get("is_error") is True


def test_list_low_stock_reports_products_at_or_below_reorder(tmp_path):
    inventory = _make_inventory(tmp_path)
    inventory.create_product(
        name="Almost Out", category="fmcg", unit="packet", is_loose=False,
        hsn_code="00000000", gst_slab=0, cost_price=Decimal("1"), sell_price=Decimal("2"),
        mrp=Decimal("2"), reorder_level=Decimal("10"), initial_qty=Decimal("3"),
    )
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["list_low_stock"].handler({}))
    assert "Almost Out" in result["content"][0]["text"]


def test_list_products_lists_every_product(tmp_path):
    inventory = _make_inventory(tmp_path)
    inventory.create_product(
        name="Parle-G", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19053100", gst_slab=5, cost_price=Decimal("8.00"),
        sell_price=Decimal("10.00"), mrp=Decimal("10.00"), reorder_level=Decimal("20"),
    )
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["list_products"].handler({}))
    assert "Parle-G" in result["content"][0]["text"]


def test_receive_stock_increments_and_reports(tmp_path):
    inventory = _make_inventory(tmp_path)
    inventory.create_product(
        name="Maggi 70g", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19023090", gst_slab=12, cost_price=Decimal("10.00"),
        sell_price=Decimal("14.00"), mrp=Decimal("14.00"), reorder_level=Decimal("20"),
        initial_qty=Decimal("10"),
    )
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["receive_stock"].handler({"product_name": "Maggi 70g", "qty": "50"}))
    assert not result.get("is_error")
    assert inventory.get_stock(product_id=inventory.find_product_by_name(name="Maggi 70g").id) == Decimal("60")


def test_receive_stock_is_error_for_unknown_product(tmp_path):
    inventory = _make_inventory(tmp_path)
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["receive_stock"].handler({"product_name": "Nonexistent", "qty": "5"}))
    assert result.get("is_error") is True


def test_create_product_creates_and_reports(tmp_path):
    inventory = _make_inventory(tmp_path)
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["create_product"].handler({
        "name": "Surf Excel 1kg", "category": "fmcg", "unit": "packet", "is_loose": False,
        "hsn_code": "34022090", "gst_slab": 18, "cost_price": "95.00", "sell_price": "115.00",
        "mrp": "125.00", "reorder_level": "5",
    }))
    assert not result.get("is_error")
    assert inventory.find_product_by_name(name="Surf Excel 1kg") is not None


def test_create_product_is_error_below_cost(tmp_path):
    inventory = _make_inventory(tmp_path)
    tools = _tools_by_name(inventory)
    result = asyncio.run(tools["create_product"].handler({
        "name": "Underpriced", "category": "fmcg", "unit": "packet", "is_loose": False,
        "hsn_code": "00000000", "gst_slab": 5, "cost_price": "50.00", "sell_price": "40.00",
        "mrp": "60.00", "reorder_level": "1",
    }))
    assert result.get("is_error") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_inventory_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tools'`

- [ ] **Step 3: Write minimal implementation**

`app/tools/__init__.py`:
```python
```

`app/tools/inventory_tools.py`:
```python
import asyncio
from decimal import Decimal

from claude_agent_sdk import tool

from app.errors import DomainError
from app.services.inventory import InventoryService


def build_inventory_tools(inventory: InventoryService):
    @tool("get_stock", "Look up current stock quantity for a product by its exact name.",
          {"product_name": str})
    async def get_stock(args):
        product = await asyncio.to_thread(inventory.find_product_by_name, name=args["product_name"])
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
        product = await asyncio.to_thread(inventory.find_product_by_name, name=args["product_name"])
        if product is None:
            return {"content": [{"type": "text", "text": f"No product found named {args['product_name']!r}."}],
                    "is_error": True}
        try:
            await asyncio.to_thread(
                inventory.receive_stock,
                product_id=product.id,
                qty=Decimal(args["qty"]),
                cost_price=Decimal(args["cost_price"]) if args.get("cost_price") else None,
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
        try:
            product_id = await asyncio.to_thread(
                inventory.create_product,
                name=args["name"], category=args["category"], unit=args["unit"],
                is_loose=args["is_loose"], hsn_code=args["hsn_code"], gst_slab=args["gst_slab"],
                cost_price=Decimal(args["cost_price"]), sell_price=Decimal(args["sell_price"]),
                mrp=Decimal(args["mrp"]), reorder_level=Decimal(args["reorder_level"]),
                initial_qty=Decimal(args["initial_qty"]) if args.get("initial_qty") else Decimal("0"),
            )
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        return {"content": [{"type": "text", "text": f"Created {args['name']} (product id {product_id})."}]}

    return [get_stock, list_low_stock, list_products, receive_stock, create_product]
```

- [ ] **Step 4: Run test to verify it passes, then full suite**

Run: `pytest tests/test_inventory_tools.py -v` — expect 8 passed
Run: `pytest -v` — expect 82 passed

- [ ] **Step 5: Commit**

```bash
git add app/tools/__init__.py app/tools/inventory_tools.py tests/test_inventory_tools.py
git commit -m "feat: add inventory tool wrappers"
```

---

### Task 3: Billing tools

**Files:**
- Create: `app/tools/billing_tools.py`
- Test: `tests/test_billing_tools.py`

**Interfaces:**
- Consumes: `BillingService` from `app.services.billing`; `InventoryService` from `app.services.inventory`; `DomainError` from `app.errors`
- Produces: `UpdateContext` (a mutable dataclass with one field, `current_update_id: str | None`), `build_billing_tools(billing, inventory, chat_id: str, update_context: UpdateContext) -> list[SdkMcpTool]` — 7 tools: `start_bill`, `add_bill_item`, `update_bill_item`, `drop_bill_item`, `get_bill_draft`, `cancel_bill`, `finalize_bill`.

- [ ] **Step 1: Write the failing test**

`tests/test_billing_tools.py`:
```python
import asyncio
from decimal import Decimal

from app.db import Base, make_engine, make_session_factory
from app.services.billing import BillingService
from app.services.inventory import InventoryService
from app.tools.billing_tools import UpdateContext, build_billing_tools


def _make_services(tmp_path):
    engine = make_engine(str(tmp_path / "bill_tools.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    return InventoryService(session_factory), BillingService(session_factory)


def _make_product(inventory, qty=Decimal("10")):
    inventory.create_product(
        name="Tata Salt 1kg", category="staples", unit="packet", is_loose=False,
        hsn_code="25010020", gst_slab=5, cost_price=Decimal("18.00"),
        sell_price=Decimal("22.00"), mrp=Decimal("24.00"), reorder_level=Decimal("5"),
        initial_qty=qty,
    )


def _tools_by_name(billing, inventory, chat_id="chat-1", update_context=None):
    return {t.name: t for t in build_billing_tools(billing, inventory, chat_id, update_context or UpdateContext())}


def test_start_bill_then_get_bill_draft_is_empty(tmp_path):
    inventory, billing = _make_services(tmp_path)
    tools = _tools_by_name(billing, inventory)
    asyncio.run(tools["start_bill"].handler({"payment_mode": "upi"}))
    result = asyncio.run(tools["get_bill_draft"].handler({}))
    assert "empty" in result["content"][0]["text"].lower()


def test_add_bill_item_appears_in_draft(tmp_path):
    inventory, billing = _make_services(tmp_path)
    _make_product(inventory)
    tools = _tools_by_name(billing, inventory)
    asyncio.run(tools["start_bill"].handler({}))
    result = asyncio.run(tools["add_bill_item"].handler({"product_name": "Tata Salt 1kg", "qty": "2"}))
    assert not result.get("is_error")
    draft = asyncio.run(tools["get_bill_draft"].handler({}))
    assert "Tata Salt 1kg" in draft["content"][0]["text"]


def test_add_bill_item_is_error_for_unknown_product(tmp_path):
    inventory, billing = _make_services(tmp_path)
    tools = _tools_by_name(billing, inventory)
    asyncio.run(tools["start_bill"].handler({}))
    result = asyncio.run(tools["add_bill_item"].handler({"product_name": "Nonexistent", "qty": "1"}))
    assert result.get("is_error") is True


def test_update_bill_item_changes_qty(tmp_path):
    inventory, billing = _make_services(tmp_path)
    _make_product(inventory)
    tools = _tools_by_name(billing, inventory)
    asyncio.run(tools["start_bill"].handler({}))
    asyncio.run(tools["add_bill_item"].handler({"product_name": "Tata Salt 1kg", "qty": "2"}))
    asyncio.run(tools["update_bill_item"].handler({"product_name": "Tata Salt 1kg", "qty": "6"}))
    draft = asyncio.run(tools["get_bill_draft"].handler({}))
    assert "6" in draft["content"][0]["text"]


def test_drop_bill_item_removes_line(tmp_path):
    inventory, billing = _make_services(tmp_path)
    _make_product(inventory)
    tools = _tools_by_name(billing, inventory)
    asyncio.run(tools["start_bill"].handler({}))
    asyncio.run(tools["add_bill_item"].handler({"product_name": "Tata Salt 1kg", "qty": "2"}))
    asyncio.run(tools["drop_bill_item"].handler({"product_name": "Tata Salt 1kg"}))
    draft = asyncio.run(tools["get_bill_draft"].handler({}))
    assert "empty" in draft["content"][0]["text"].lower()


def test_cancel_bill_discards_draft(tmp_path):
    inventory, billing = _make_services(tmp_path)
    tools = _tools_by_name(billing, inventory)
    asyncio.run(tools["start_bill"].handler({}))
    result = asyncio.run(tools["cancel_bill"].handler({}))
    assert not result.get("is_error")
    draft = asyncio.run(tools["get_bill_draft"].handler({}))
    assert draft.get("is_error") is True  # NoDraftBillError, since it was cancelled


def test_finalize_bill_decrements_stock_and_uses_update_context(tmp_path):
    inventory, billing = _make_services(tmp_path)
    _make_product(inventory, qty=Decimal("10"))
    update_context = UpdateContext()
    tools = _tools_by_name(billing, inventory, update_context=update_context)
    asyncio.run(tools["start_bill"].handler({"payment_mode": "cash"}))
    asyncio.run(tools["add_bill_item"].handler({"product_name": "Tata Salt 1kg", "qty": "2"}))

    update_context.current_update_id = "update-1"
    result = asyncio.run(tools["finalize_bill"].handler({}))
    assert not result.get("is_error")
    assert inventory.get_stock(product_id=inventory.find_product_by_name(name="Tata Salt 1kg").id) == Decimal("8")


def test_finalize_bill_is_error_on_oversell(tmp_path):
    inventory, billing = _make_services(tmp_path)
    _make_product(inventory, qty=Decimal("1"))
    update_context = UpdateContext()
    tools = _tools_by_name(billing, inventory, update_context=update_context)
    asyncio.run(tools["start_bill"].handler({"payment_mode": "cash"}))
    asyncio.run(tools["add_bill_item"].handler({"product_name": "Tata Salt 1kg", "qty": "10"}))

    update_context.current_update_id = "update-2"
    result = asyncio.run(tools["finalize_bill"].handler({}))
    assert result.get("is_error") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_billing_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tools.billing_tools'`

- [ ] **Step 3: Write minimal implementation**

`app/tools/billing_tools.py`:
```python
import asyncio
from dataclasses import dataclass
from decimal import Decimal

from claude_agent_sdk import tool

from app.errors import DomainError


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
        product = await _resolve_product(args["product_name"])
        if product is None:
            return {"content": [{"type": "text", "text": f"No product found named {args['product_name']!r}."}],
                    "is_error": True}
        try:
            await asyncio.to_thread(
                billing.add_item, chat_id=chat_id, product_id=product.id, qty=Decimal(args["qty"]),
            )
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        return {"content": [{"type": "text", "text": f"Added {args['qty']} x {product.name}."}]}

    @tool("update_bill_item", "Change the quantity of a product already on the current bill.",
          {"product_name": str, "qty": str})
    async def update_bill_item(args):
        product = await _resolve_product(args["product_name"])
        if product is None:
            return {"content": [{"type": "text", "text": f"No product found named {args['product_name']!r}."}],
                    "is_error": True}
        try:
            await asyncio.to_thread(
                billing.update_item, chat_id=chat_id, product_id=product.id, qty=Decimal(args["qty"]),
            )
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        return {"content": [{"type": "text", "text": f"Updated {product.name} to {args['qty']}."}]}

    @tool("drop_bill_item", "Remove a product line from the current bill.", {"product_name": str})
    async def drop_bill_item(args):
        product = await _resolve_product(args["product_name"])
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
```

- [ ] **Step 4: Run test to verify it passes, then full suite**

Run: `pytest tests/test_billing_tools.py -v` — expect 8 passed
Run: `pytest -v` — expect 90 passed

- [ ] **Step 5: Commit**

```bash
git add app/tools/billing_tools.py tests/test_billing_tools.py
git commit -m "feat: add billing tool wrappers with per-turn update-id context"
```

---

### Task 4: Khata + Preferences tools

**Files:**
- Create: `app/tools/khata_tools.py`
- Create: `app/tools/preferences_tools.py`
- Test: `tests/test_khata_tools.py`
- Test: `tests/test_preferences_tools.py`

**Interfaces:**
- Consumes: `KhataService` from `app.services.khata`; `PreferencesService` from `app.services.preferences`; `DomainError` from `app.errors`
- Produces: `build_khata_tools(khata) -> list[SdkMcpTool]` (3 tools: `credit_customer`, `settle_khata`, `get_khata_balance`); `build_preferences_tools(preferences) -> list[SdkMcpTool]` (2 tools: `set_preference`, `get_preference`)

- [ ] **Step 1: Write the failing tests**

`tests/test_khata_tools.py`:
```python
import asyncio
from decimal import Decimal

from app.db import Base, make_engine, make_session_factory
from app.services.khata import KhataService
from app.tools.khata_tools import build_khata_tools


def _tools_by_name(tmp_path):
    engine = make_engine(str(tmp_path / "khata_tools.db"))
    Base.metadata.create_all(engine)
    khata = KhataService(make_session_factory(engine))
    return {t.name: t for t in build_khata_tools(khata)}, khata


def test_credit_customer_creates_and_reports(tmp_path):
    tools, khata = _tools_by_name(tmp_path)
    result = asyncio.run(tools["credit_customer"].handler({"customer_name": "Ramesh", "amount": "500"}))
    assert not result.get("is_error")
    assert khata.get_balance(customer_name="Ramesh") == Decimal("500")


def test_settle_khata_reduces_balance(tmp_path):
    tools, khata = _tools_by_name(tmp_path)
    asyncio.run(tools["credit_customer"].handler({"customer_name": "Ramesh", "amount": "500"}))
    result = asyncio.run(tools["settle_khata"].handler({"customer_name": "Ramesh", "amount": "300"}))
    assert not result.get("is_error")
    assert khata.get_balance(customer_name="Ramesh") == Decimal("200")


def test_settle_khata_is_error_for_unknown_customer(tmp_path):
    tools, khata = _tools_by_name(tmp_path)
    result = asyncio.run(tools["settle_khata"].handler({"customer_name": "Ghost", "amount": "100"}))
    assert result.get("is_error") is True


def test_get_khata_balance_reports_amount(tmp_path):
    tools, khata = _tools_by_name(tmp_path)
    asyncio.run(tools["credit_customer"].handler({"customer_name": "Ramesh", "amount": "500"}))
    result = asyncio.run(tools["get_khata_balance"].handler({"customer_name": "Ramesh"}))
    assert "500" in result["content"][0]["text"]


def test_get_khata_balance_is_error_for_unknown_customer(tmp_path):
    tools, khata = _tools_by_name(tmp_path)
    result = asyncio.run(tools["get_khata_balance"].handler({"customer_name": "Ghost"}))
    assert result.get("is_error") is True
```

`tests/test_preferences_tools.py`:
```python
import asyncio

from app.db import Base, make_engine, make_session_factory
from app.services.preferences import PreferencesService
from app.tools.preferences_tools import build_preferences_tools


def _tools_by_name(tmp_path):
    engine = make_engine(str(tmp_path / "prefs_tools.db"))
    Base.metadata.create_all(engine)
    preferences = PreferencesService(make_session_factory(engine))
    return {t.name: t for t in build_preferences_tools(preferences)}, preferences


def test_set_preference_persists(tmp_path):
    tools, preferences = _tools_by_name(tmp_path)
    result = asyncio.run(tools["set_preference"].handler({"key": "default_payment_mode", "value": "upi"}))
    assert not result.get("is_error")
    assert preferences.get_preference(key="default_payment_mode") == "upi"


def test_get_preference_reports_value(tmp_path):
    tools, preferences = _tools_by_name(tmp_path)
    preferences.set_preference(key="shop_name", value="Sharma Kirana Store")
    result = asyncio.run(tools["get_preference"].handler({"key": "shop_name"}))
    assert "Sharma Kirana Store" in result["content"][0]["text"]


def test_get_preference_reports_unset(tmp_path):
    tools, preferences = _tools_by_name(tmp_path)
    result = asyncio.run(tools["get_preference"].handler({"key": "nonexistent_key"}))
    assert "No preference set" in result["content"][0]["text"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_khata_tools.py tests/test_preferences_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`app/tools/khata_tools.py`:
```python
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
```

`app/tools/preferences_tools.py`:
```python
import asyncio

from claude_agent_sdk import tool


def build_preferences_tools(preferences):
    @tool("set_preference",
          "Remember a standing owner preference (e.g. default payment mode, default brand for "
          "an item, shop name/GSTIN) so it silently applies in future chats too.",
          {"key": str, "value": str})
    async def set_preference(args):
        await asyncio.to_thread(preferences.set_preference, key=args["key"], value=args["value"])
        return {"content": [{"type": "text", "text": f"Got it, remembered {args['key']} = {args['value']}."}]}

    @tool("get_preference", "Look up a previously remembered owner preference by key.", {"key": str})
    async def get_preference(args):
        value = await asyncio.to_thread(preferences.get_preference, key=args["key"])
        if value is None:
            return {"content": [{"type": "text", "text": f"No preference set for {args['key']!r}."}]}
        return {"content": [{"type": "text", "text": f"{args['key']} = {value}"}]}

    return [set_preference, get_preference]
```

- [ ] **Step 4: Run tests to verify they pass, then full suite**

Run: `pytest tests/test_khata_tools.py tests/test_preferences_tools.py -v` — expect 8 passed
Run: `pytest -v` — expect 98 passed

- [ ] **Step 5: Commit**

```bash
git add app/tools/khata_tools.py app/tools/preferences_tools.py tests/test_khata_tools.py tests/test_preferences_tools.py
git commit -m "feat: add khata and preferences tool wrappers"
```

---

### Task 5: Skill content (`.claude/skills/*/SKILL.md`)

**Files:**
- Create: `.claude/skills/inventory/SKILL.md`
- Create: `.claude/skills/billing/SKILL.md`
- Create: `.claude/skills/khata/SKILL.md`
- Create: `.claude/skills/preferences/SKILL.md`
- Test: `tests/test_skills_content.py` (a sanity check, not a behavioral test — SKILL.md content quality is judged by reading it, not by pytest)

**Interfaces:**
- Consumes: nothing (pure content, read by the SDK's own skill-discovery mechanism, verified working in Task 5's own manual smoke test)
- Produces: 4 skill files discoverable by `setting_sources=["project"]` when `cwd` is the repo root

- [ ] **Step 1: Write the failing sanity test**

`tests/test_skills_content.py`:
```python
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / ".claude" / "skills"


def _read(name):
    return (SKILLS_DIR / name / "SKILL.md").read_text()


def test_all_four_skill_files_exist_with_frontmatter():
    for name in ("inventory", "billing", "khata", "preferences"):
        content = _read(name)
        assert content.startswith("---"), f"{name} SKILL.md missing YAML frontmatter"
        assert "description:" in content.splitlines()[2], f"{name} SKILL.md missing a description line"


def test_billing_skill_mentions_gst_and_oversell():
    content = _read("billing").lower()
    assert "gst" in content
    assert "oversell" in content or "stock" in content


def test_khata_skill_mentions_settle_guardrail():
    content = _read("khata").lower()
    assert "khata" in content
    assert "doesn't exist" in content or "does not exist" in content or "unknown" in content


def test_preferences_skill_mentions_silent_application():
    content = _read("preferences").lower()
    assert "silent" in content or "don't re-ask" in content or "without asking" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_skills_content.py -v`
Expected: FAIL with `FileNotFoundError` (skill directories don't exist yet)

- [ ] **Step 3: Write the skill content**

`.claude/skills/inventory/SKILL.md`:
```markdown
---
name: inventory
description: Use whenever the owner asks about stock levels, receiving new stock, registering a new product/SKU, or what's running low. Covers unit handling (loose vs packaged) and HSN/GST lookup for new products.
---

# Inventory

You manage stock for an Indian kirana store. Ground every fact in the tools — never state a
price, GST slab, or stock level from memory.

## Units and loose vs packaged

- Loose items (sugar, rice, dal, atta sold by weight) use `kg`/`g`/`litre`/`ml` and `is_loose=true`.
- Packaged items (Maggi, Parle-G, Amul Butter) use `packet`/`dozen`/`piece` and `is_loose=false`.
- When the owner names a generic item that could be either (e.g. "atta"), ask which one they mean
  — e.g. "Aashirvaad 5kg or loose?" — unless a standing preference already answers it (check
  preferences first).

## GST slabs

Real Indian slabs: 0% (loose staples, fresh produce), 5% (packaged staples like salt, oil, some
biscuits), 12–18% (most FMCG — soaps, snacks, some dairy), 28% (luxury/sin goods, rarely relevant
here). When registering a new product, ask the owner for the GST slab if they don't state it —
never guess a tax rate.

## Registering a new product

Use `create_product`. It will refuse (typed error, relay verbatim) if the sell price is below
cost, or if the unit/GST slab isn't one of the valid values — that's the tool protecting the
owner from a data-entry mistake, not a bug.

## Receiving stock

Use `receive_stock` when the owner says something like "50 packets of Maggi came in, cost ₹12".
If they mention a new cost price, pass it — this is how the shop's ledger cost stays current.

## Running low

Use `list_low_stock` for "what's running out?" — it already applies the reorder-level threshold,
don't try to compute it yourself from `get_stock` calls.
```

`.claude/skills/billing/SKILL.md`:
```markdown
---
name: billing
description: Use whenever the owner is cutting a bill, mentions items to buy, wants to edit an in-progress bill (drop/add/change quantity), asks to see the current bill, or wants to finalize/cancel one. Covers GST tax breakup and the oversell guard.
---

# Billing

A bill is built over several messages before it's final. Follow this lifecycle:

1. **`start_bill`** — begin a new bill for this chat. If the owner just starts listing items
   without saying "start a bill" or "make a bill", call `start_bill` implicitly first, then add
   the items — don't ask them to explicitly say "start" first.
2. **`add_bill_item`** (repeat per item) — resolve the product by its exact name. If the owner's
   phrasing is ambiguous (e.g. "atta" with no size, and no standing preference answers it), ask
   which SKU before adding.
3. Mid-build edits — **`update_bill_item`** to change a quantity, **`drop_bill_item`** to remove a
   line. These work on the SAME draft; don't call `start_bill` again unless the owner clearly
   wants to discard everything and start over (use `cancel_bill` for that instead, then
   `start_bill`).
4. **`get_bill_draft`** — show the running total with its GST tax breakup whenever the owner asks
   "what's the total so far" or similar, or after adding items if it feels natural to confirm.
5. **`finalize_bill`** — ONLY when the owner has clearly confirmed they want to complete the sale
   (e.g. "that's it, UPI" / "finalize" / "done, cash"). This is the point stock actually
   decrements — never call it speculatively or "just to check" the total; use `get_bill_draft` for
   that instead.

## Payment mode

If the owner doesn't state a payment mode, check preferences for a default before asking — many
owners set "always assume UPI unless I say cash" as a standing preference. If there's genuinely no
default and none was stated, ask before finalizing.

## Oversell guard

If `add_bill_item` or `finalize_bill` refuses because there isn't enough stock, relay that refusal
plainly — e.g. "Only 6 in stock, you asked for 10." Never round down silently or substitute a
different quantity without the owner's say-so.

## GST tax breakup

Every draft and every finalized bill shows CGST and SGST separately, plus the subtotal and grand
total — this is what a printed GST invoice needs to show. Don't collapse them into one "tax" line
when relaying to the owner.
```

`.claude/skills/khata/SKILL.md`:
```markdown
---
name: khata
description: Use whenever the owner mentions putting an amount on someone's credit, a customer paying off what they owe, or asks for a customer's balance. This is the store's credit ledger (khata) — a first-class kirana concept, distinct from a regular cash/UPI/card sale.
---

# Khata (credit ledger)

Khata is running credit a regular customer buys against and pays down later — not the same as a
bill's payment mode.

- **`credit_customer`** — "put ₹500 on Ramesh's credit". If this is the customer's first-ever
  khata entry, the tool creates them automatically — you don't need a separate "add customer"
  step.
- **`settle_khata`** — "Ramesh paid ₹300". This REQUIRES the customer to already exist — if the
  tool refuses because the customer is unknown, tell the owner plainly (e.g. "I don't have a
  khata for anyone named X yet") rather than silently creating one. Settling a khata that doesn't
  exist is exactly the mistake this guard prevents.
- **`get_khata_balance`** — "what's Ramesh's balance?" — reports the net credit outstanding
  (credit given minus payments received). Same not-found behavior as settling.

Customer names are matched case-insensitively but must otherwise match exactly — if the owner's
phrasing is ambiguous about which customer they mean, ask rather than guessing.
```

`.claude/skills/preferences/SKILL.md`:
```markdown
---
name: preferences
description: Use whenever the owner states a standing rule for how they want things handled going forward (e.g. a default payment mode, a default brand/size for an ambiguous item, the shop's name or GSTIN for invoices) — and check remembered preferences before asking a question they've already answered.
---

# Preferences

These are facts that should apply silently and persist across conversations (including after
`/new`) — not something to re-confirm every time.

- When the owner says something like "always assume UPI unless I say cash" or "default atta is
  Aashirvaad 5kg", call `set_preference` with a clear key (`default_payment_mode`,
  `default_atta_sku`, `shop_name`, `shop_gstin`, `shop_address`) and the stated value. Acknowledge
  briefly — don't make a big deal of it.
- Before asking a clarifying question about payment mode, product ambiguity, or invoice details,
  check `get_preference` first (or rely on the standing-preferences block already given to you at
  the start of this conversation) — don't re-ask something a preference already answers.
- Preferences apply silently. Don't announce "using your default payment mode of UPI" every single
  time — just use it, the way a regular shop assistant would.
```

- [ ] **Step 4: Run test to verify it passes, then full suite**

Run: `pytest tests/test_skills_content.py -v` — expect 4 passed
Run: `pytest -v` — expect 102 passed

- [ ] **Step 5: Commit**

```bash
git add .claude/skills tests/test_skills_content.py
git commit -m "feat: add inventory/billing/khata/preferences skill content"
```

---

### Task 6: `AgentSession` core

**Files:**
- Create: `app/agent_session.py`
- Test: `tests/test_agent_session.py` (construction/wiring only — no live API call, see Task 6's manual verification note)

**Interfaces:**
- Consumes: all four `build_*_tools` factories; `InventoryService`, `BillingService`, `KhataService`, `PreferencesService`; `ClaudeAgentOptions`, `ClaudeSDKClient`, `create_sdk_mcp_server` from `claude_agent_sdk`
- Produces: `AgentSession(chat_id: str, session_factory, model: str | None = None)` with `async send(text: str, *, update_id: str) -> str` and `async close() -> None`

- [ ] **Step 1: Write the failing test**

`tests/test_agent_session.py` (construction-only — connecting/sending requires a live model call, which costs real money and network access; that is verified manually per this task's Step 6, not in the automated suite):
```python
from app.agent_session import AgentSession
from app.db import Base, make_engine, make_session_factory


def test_agent_session_constructs_with_all_tool_domains_registered(tmp_path):
    engine = make_engine(str(tmp_path / "session.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    session = AgentSession(chat_id="test-chat", session_factory=session_factory)

    tool_names = {t.name for t in session._all_tools}
    assert tool_names == {
        "get_stock", "list_low_stock", "list_products", "receive_stock", "create_product",
        "start_bill", "add_bill_item", "update_bill_item", "drop_bill_item",
        "get_bill_draft", "cancel_bill", "finalize_bill",
        "credit_customer", "settle_khata", "get_khata_balance",
        "set_preference", "get_preference",
    }
    assert session._options.tools == ["Skill"]
    assert session._options.strict_mcp_config is True
    assert session._options.permission_mode == "bypassPermissions"
    assert session.chat_id == "test-chat"


def test_agent_session_injects_existing_preferences_into_system_prompt(tmp_path):
    from app.services.preferences import PreferencesService

    engine = make_engine(str(tmp_path / "session_prefs.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    PreferencesService(session_factory).set_preference(key="default_payment_mode", value="upi")

    session = AgentSession(chat_id="test-chat", session_factory=session_factory)

    assert "default_payment_mode: upi" in session._options.system_prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_session.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.agent_session'`

- [ ] **Step 3: Write minimal implementation**

`app/agent_session.py`:
```python
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, create_sdk_mcp_server

from app.services.billing import BillingService
from app.services.inventory import InventoryService
from app.services.khata import KhataService
from app.services.preferences import PreferencesService
from app.tools.billing_tools import UpdateContext, build_billing_tools
from app.tools.inventory_tools import build_inventory_tools
from app.tools.khata_tools import build_khata_tools
from app.tools.preferences_tools import build_preferences_tools

REPO_ROOT = Path(__file__).resolve().parent.parent

BASE_SYSTEM_PROMPT = (
    "You are Kirana, the conversational assistant running an Indian kirana (supermarket) store "
    "from Telegram, on behalf of the shop owner. The owner talks to you in plain, terse English, "
    "shopkeeper-style. You act on their behalf using your tools -- never invent a price, GST "
    "rate, or stock level; always look it up. Amounts are in Indian Rupees. When a request is "
    "genuinely ambiguous (e.g. which SKU, which unit), ask a clarifying question instead of "
    "guessing. When a tool refuses an action, relay the reason to the owner plainly -- do not "
    "try to work around it."
)


def _format_preferences(prefs: dict) -> str:
    if not prefs:
        return "No standing preferences set yet."
    lines = "\n".join(f"- {k}: {v}" for k, v in prefs.items())
    return f"Standing owner preferences (apply these silently unless the owner says otherwise):\n{lines}"


class AgentSession:
    def __init__(self, *, chat_id: str, session_factory, model: str | None = None):
        self.chat_id = chat_id
        inventory = InventoryService(session_factory)
        billing = BillingService(session_factory)
        khata = KhataService(session_factory)
        preferences = PreferencesService(session_factory)

        self._update_context = UpdateContext()
        self._all_tools = (
            build_inventory_tools(inventory)
            + build_billing_tools(billing, inventory, chat_id, self._update_context)
            + build_khata_tools(khata)
            + build_preferences_tools(preferences)
        )
        server = create_sdk_mcp_server(name="kirana", version="1.0.0", tools=self._all_tools)

        prefs_block = _format_preferences(preferences.get_all_preferences())
        system_prompt = f"{BASE_SYSTEM_PROMPT}\n\n{prefs_block}"

        self._options = ClaudeAgentOptions(
            tools=["Skill"],
            mcp_servers={"kirana": server},
            strict_mcp_config=True,
            permission_mode="bypassPermissions",
            setting_sources=["project"],
            skills="all",
            cwd=str(REPO_ROOT),
            system_prompt=system_prompt,
            max_turns=20,
            model=model,
        )
        self._client = ClaudeSDKClient(options=self._options)
        self._connected = False

    async def send(self, text: str, *, update_id: str) -> str:
        self._update_context.current_update_id = update_id
        if not self._connected:
            await self._client.connect()
            self._connected = True
        await self._client.query(text)
        result_text = ""
        async for message in self._client.receive_response():
            if type(message).__name__ == "ResultMessage":
                result_text = message.result or ""
        return result_text

    async def close(self):
        if self._connected:
            await self._client.disconnect()
            self._connected = False
```

- [ ] **Step 4: Run test to verify it passes, then full suite**

Run: `pytest tests/test_agent_session.py -v` — expect 2 passed
Run: `pytest -v` — expect 104 passed

- [ ] **Step 5: Commit**

```bash
git add app/agent_session.py tests/test_agent_session.py
git commit -m "feat: add AgentSession wrapping ClaudeSDKClient with locked-down tool surface"
```

- [ ] **Step 6: Manual live verification (not part of the automated suite — costs real API usage)**

This step is run once by hand after the commit, not on every test run. From the repo root with the venv active and a working `claude` CLI auth (or `ANTHROPIC_API_KEY` set):
```python
import asyncio
from app.config import load_settings
from app.db import init_db, make_session_factory
from app.agent_session import AgentSession

settings = load_settings()
engine = init_db(settings)
session_factory = make_session_factory(engine)

async def main():
    session = AgentSession(chat_id="smoke-test", session_factory=session_factory)
    print(await session.send("how much sugar is left?", update_id="u1"))
    await session.close()

asyncio.run(main())
```
Expected: a grounded answer referencing whatever `Sugar (loose)` stock actually is in the DB (seed the DB first via `scripts/seed_dev_data.py` if empty) — not a hallucinated number. Record the result in the task report.

---

### Task 7: CLI channel + local entrypoint

**Files:**
- Create: `app/channels/__init__.py`
- Create: `app/channels/cli_channel.py`
- Create: `app/run_cli.py`
- Test: `tests/test_cli_channel.py` (construction only, same live-call caveat as Task 6)

**Interfaces:**
- Consumes: `AgentSession` from `app.agent_session`
- Produces: `CLIChannel(chat_id: str, session_factory)` with `async run() -> None`; `app/run_cli.py`'s `main()` as the `python -m app.run_cli` entrypoint

- [ ] **Step 1: Write the failing test**

`tests/test_cli_channel.py`:
```python
from app.channels.cli_channel import CLIChannel
from app.db import Base, make_engine, make_session_factory


def test_cli_channel_constructs_an_agent_session(tmp_path):
    engine = make_engine(str(tmp_path / "cli.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    channel = CLIChannel(chat_id="local", session_factory=session_factory)

    assert channel._session.chat_id == "local"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_channel.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.channels'`

- [ ] **Step 3: Write minimal implementation**

`app/channels/__init__.py`:
```python
```

`app/channels/cli_channel.py`:
```python
import asyncio
import uuid

from app.agent_session import AgentSession


class CLIChannel:
    def __init__(self, *, chat_id: str, session_factory):
        self._session = AgentSession(chat_id=chat_id, session_factory=session_factory)

    async def run(self):
        print("Kirana Ops Agent (CLI) -- type your message, or 'exit' to quit.")
        loop = asyncio.get_event_loop()
        try:
            while True:
                text = await loop.run_in_executor(None, input, "you> ")
                if text.strip().lower() in ("exit", "quit"):
                    break
                if not text.strip():
                    continue
                update_id = str(uuid.uuid4())
                reply = await self._session.send(text, update_id=update_id)
                print(f"kirana> {reply}")
        finally:
            await self._session.close()
```

`app/run_cli.py`:
```python
import asyncio

from app.channels.cli_channel import CLIChannel
from app.config import load_settings
from app.db import init_db, make_session_factory


def main():
    settings = load_settings()
    engine = init_db(settings)
    session_factory = make_session_factory(engine)
    channel = CLIChannel(chat_id="local", session_factory=session_factory)
    asyncio.run(channel.run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes, then full suite**

Run: `pytest tests/test_cli_channel.py -v` — expect 1 passed
Run: `pytest -v` — expect 105 passed

- [ ] **Step 5: Commit**

```bash
git add app/channels/__init__.py app/channels/cli_channel.py app/run_cli.py tests/test_cli_channel.py
git commit -m "feat: add CLIChannel and python -m app.run_cli local entrypoint"
```

- [ ] **Step 6: Manual live verification (not part of the automated suite)**

Run: `python -m app.run_cli` (with the DB seeded via `scripts/seed_dev_data.py` first) and drive at least these from the brief's §3 table by hand: a stock query, a multi-item bill with an edit (drop one item, change a quantity), an oversell attempt, a khata credit + balance check, and a preference ("always assume UPI unless I say cash"). Record what happened in the task report — this is the first real, interactive proof the whole agent-first control loop works end to end locally, with no Telegram dependency, matching the roadmap's local-first priority.
