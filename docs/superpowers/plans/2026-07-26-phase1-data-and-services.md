# Phase 1 — Data Model & Service Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the durable data model and the three domain services (Inventory, Billing, Khata) that own every business rule — oversell guard, GST math, idempotent finalize, khata integrity — with no agent involved yet. This is the layer Phase 2's tools will call.

**Architecture:** SQLAlchemy 2.0 typed models (`app/models.py`) attach to Phase 0's `Base`. A shared pure-function GST calculator (`app/billing_math.py`) is used by both the live draft preview and the authoritative finalize path, so there is exactly one place GST gets computed. Each service (`app/services/inventory.py`, `billing.py`, `khata.py`) takes a `session_factory` and opens its own transaction per method — no service method spans multiple transactions, and no transaction is left open across a return to the caller.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.0 (typed `Mapped`/`mapped_column`), `decimal.Decimal` for all money and quantity math, pytest, `threading` for concurrency tests.

## Global Constraints

- Python >= 3.11
- All money and quantity fields are `decimal.Decimal`, stored as SQL `Numeric` — never `float`
- GST slab must be one of `{0, 5, 12, 18, 28}`; unit must be one of `{kg, g, litre, ml, packet, dozen, piece}` — validated in `InventoryService.create_product`, not left to the caller
- Rounding: quantize to the nearest paisa (`ROUND_HALF_UP`, 2 decimal places) only from the **unrounded** running sum, at the bill level — never derive a bill total by summing already-rounded per-line amounts (that reintroduces the drift the spec calls out)
- Oversell guard: the authoritative check runs inside `finalize_bill`'s single transaction, validates every line before writing any of them, and that transaction runs under `BEGIN IMMEDIATE` (Task 1) so two concurrent finalizes serialize instead of corrupting stock
- Idempotency: `finalize_bill` is keyed on `telegram_update_id`. This phase extends the design spec's `processed_updates` table with one additional nullable column, `bill_id`, so a duplicate finalize call can return the prior bill's id (the design spec's bill-lifecycle sequence diagram requires this; the two-column version in the spec text can't support it) — this is documented here as a deliberate, additive refinement, not a silent deviation
- No placeholder/TODO code — every function fully implemented per its task

---

### Task 1: `BEGIN IMMEDIATE` transaction wiring

**Files:**
- Modify: `app/db.py:14-30` (the `make_engine` function)
- Test: `tests/test_concurrency_db.py`

**Interfaces:**
- Consumes: nothing new — same `make_engine(db_path: str) -> Engine` signature
- Produces: an engine where every ORM-level transaction begins with `BEGIN IMMEDIATE` instead of SQLite's default deferred begin, so a second writer's `session.begin()` call blocks (up to the existing `busy_timeout`) until the first writer commits, rather than both writers proceeding on a stale read snapshot

Why this is needed now: Phase 0 shipped `PRAGMA busy_timeout`, which prevents "database is locked" on a **write-time** lock collision. But pysqlite's default is deferred-begin, so two transactions that each do a SELECT-then-UPDATE (exactly the oversell-guard pattern in Task 6) can both open fine, both read the same pre-update value, and the second one's UPDATE fails with `SQLITE_BUSY_SNAPSHOT` — which `busy_timeout` does not retry, because its read snapshot is already stale. `BEGIN IMMEDIATE` grabs the write lock at the start of the transaction, before any read happens, closing that gap.

- [ ] **Step 1: Write the failing test**

`tests/test_concurrency_db.py`:
```python
import threading
import time

from sqlalchemy import Column, Integer
from sqlalchemy.orm import DeclarativeBase

from app.db import make_engine, make_session_factory


class _CounterBase(DeclarativeBase):
    pass


class _Counter(_CounterBase):
    __tablename__ = "concurrency_test_counter"
    id = Column(Integer, primary_key=True)
    value = Column(Integer, nullable=False)


def test_begin_immediate_prevents_lost_update_on_concurrent_read_then_write(tmp_path):
    engine = make_engine(str(tmp_path / "concurrency.db"))
    _CounterBase.metadata.create_all(engine)
    Session = make_session_factory(engine)

    with Session() as session:
        with session.begin():
            session.add(_Counter(id=1, value=0))

    both_read = threading.Barrier(2)
    errors = []

    def increment():
        try:
            with Session() as session:
                with session.begin():
                    counter = session.get(_Counter, 1)
                    both_read.wait()
                    time.sleep(0.05)
                    counter.value += 1
        except Exception as exc:  # noqa: BLE001 - capturing the failure mode under test
            errors.append(exc)

    t1 = threading.Thread(target=increment)
    t2 = threading.Thread(target=increment)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"concurrent writers raised: {errors}"
    with Session() as session:
        assert session.get(_Counter, 1).value == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_concurrency_db.py -v`
Expected: FAIL. Either an exception is captured in `errors` (a `sqlite3.OperationalError` / `sqlalchemy.exc.OperationalError` mentioning the database being locked or busy), or the final assertion fails because `value == 1` instead of `2` (a lost update — both threads read `0`, both wrote `1`). Either failure mode demonstrates the gap this task closes.

- [ ] **Step 3: Write minimal implementation**

Modify `app/db.py`'s `make_engine` function (replace lines 20-28 — the body from `engine = create_engine(...)` through the closing of `_set_pragmas`):

```python
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _connection_record):
        dbapi_connection.isolation_level = None  # hand transaction control to SQLAlchemy's "begin" event below
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _begin_immediate(conn):
        conn.exec_driver_sql("BEGIN IMMEDIATE")
```

The rest of `make_engine` (the directory-creation block above it, and the `return engine` below it) stays unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_concurrency_db.py -v`
Expected: PASS. Thread 2's `session.begin()` now blocks until thread 1 commits (via `BEGIN IMMEDIATE` + the existing `busy_timeout`), so both increments apply in sequence and the final value is `2`.

- [ ] **Step 5: Run the full existing suite to check for regressions**

Run: `pytest -v`
Expected: all previously-passing tests (12 from Phase 0) still pass, plus the 1 new test — 13 passed.

- [ ] **Step 6: Commit**

```bash
git add app/db.py tests/test_concurrency_db.py
git commit -m "feat: serialize writers with BEGIN IMMEDIATE to prevent lost updates"
```

---

### Task 2: SQLAlchemy models

**Files:**
- Create: `app/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `Base` from `app.db`
- Produces: ORM classes `Product`, `Customer`, `KhataLedger`, `DraftBill`, `Bill`, `BillItem`, `StockMovement`, `OwnerPreference`, `ProcessedUpdate` — every later task imports these exact names from `app.models`

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 3: Write minimal implementation**

`app/models.py`:
```python
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    is_loose: Mapped[bool] = mapped_column(default=False, nullable=False)
    hsn_code: Mapped[str] = mapped_column(String, nullable=False)
    gst_slab: Mapped[int] = mapped_column(nullable=False)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    sell_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    mrp: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    qty_on_hand: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("0"))
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class KhataLedger(Base):
    __tablename__ = "khata_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    bill_id: Mapped[int | None] = mapped_column(ForeignKey("bills.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class DraftBill(Base):
    __tablename__ = "draft_bills"

    chat_id: Mapped[str] = mapped_column(String, primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payment_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class Bill(Base):
    __tablename__ = "bills"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_bills_idempotency_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    payment_mode: Mapped[str] = mapped_column(String, nullable=False)
    payment_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    cgst_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    sgst_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class BillItem(Base):
    __tablename__ = "bill_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("bills.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    gst_slab: Mapped[int] = mapped_column(nullable=False)
    cgst_amt: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    sgst_amt: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    delta: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    ref_bill_id: Mapped[int | None] = mapped_column(ForeignKey("bills.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class OwnerPreference(Base):
    __tablename__ = "owner_preferences"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class ProcessedUpdate(Base):
    __tablename__ = "processed_updates"

    telegram_update_id: Mapped[str] = mapped_column(String, primary_key=True)
    bill_id: Mapped[int | None] = mapped_column(ForeignKey("bills.id"), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(default=_now)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: 17 passed (13 from Tasks 0-1 + 4 new)

- [ ] **Step 6: Commit**

```bash
git add app/models.py tests/test_models.py
git commit -m "feat: add SQLAlchemy models for products, billing, and khata"
```

---

### Task 3: GST calculator and typed errors

**Files:**
- Create: `app/billing_math.py`
- Create: `app/errors.py`
- Test: `tests/test_billing_math.py`

**Interfaces:**
- Consumes: nothing (pure functions/dataclasses, no DB access)
- Produces: `BillLineInput(product_id, product_name, qty, unit_price, gst_slab)`, `BillLineResult` (adds `line_subtotal, cgst_amt, sgst_amt, line_total`), `BillTotals(lines, subtotal, cgst_total, sgst_total, grand_total)`, `compute_bill_totals(lines: list[BillLineInput]) -> BillTotals`. Errors: `DomainError` (base), `ProductNotFoundError`, `CustomerNotFoundError`, `BelowCostError`, `InsufficientStockError`, `NoDraftBillError`, `LineNotFoundError` — every later task's service layer raises these exact classes, and the agent (Phase 2+) relays their message verbatim as a refusal.

- [ ] **Step 1: Write the failing test**

`tests/test_billing_math.py`:
```python
from decimal import Decimal

from app.billing_math import BillLineInput, compute_bill_totals


def test_single_line_gst_5_percent_cgst_sgst_split():
    lines = [BillLineInput(product_id=1, product_name="Tata Salt 1kg", qty=Decimal("1"),
                            unit_price=Decimal("22.00"), gst_slab=5)]
    result = compute_bill_totals(lines)
    line = result.lines[0]
    assert line.line_subtotal == Decimal("22.00")
    assert line.cgst_amt == Decimal("0.55")
    assert line.sgst_amt == Decimal("0.55")
    assert line.line_total == Decimal("23.10")
    assert result.subtotal == Decimal("22.00")
    assert result.cgst_total == Decimal("0.55")
    assert result.sgst_total == Decimal("0.55")
    assert result.grand_total == Decimal("23.10")


def test_zero_gst_slab_for_loose_staples():
    lines = [BillLineInput(product_id=2, product_name="Loose Rice", qty=Decimal("2"),
                            unit_price=Decimal("40.00"), gst_slab=0)]
    result = compute_bill_totals(lines)
    assert result.cgst_total == Decimal("0.00")
    assert result.sgst_total == Decimal("0.00")
    assert result.grand_total == Decimal("80.00")


def test_multi_item_bill_sums_correctly():
    lines = [
        BillLineInput(product_id=1, product_name="Tata Salt 1kg", qty=Decimal("1"),
                       unit_price=Decimal("22.00"), gst_slab=5),
        BillLineInput(product_id=3, product_name="Maggi 70g", qty=Decimal("4"),
                       unit_price=Decimal("14.00"), gst_slab=12),
    ]
    result = compute_bill_totals(lines)
    assert result.subtotal == Decimal("78.00")
    assert result.cgst_total == Decimal("3.91")
    assert result.sgst_total == Decimal("3.91")
    assert result.grand_total == Decimal("85.82")


def test_bill_level_rounding_avoids_drift_vs_naive_per_line_rounding():
    # 0.5 * 33.33 = 16.665 exactly - a genuine half-paisa case.
    # Rounding each line first then summing gives 16.67 + 16.67 = 33.34.
    # Summing the raw amounts first (33.33 exactly) and rounding once gives 33.33.
    lines = [
        BillLineInput(product_id=4, product_name="Loose Sugar", qty=Decimal("0.5"),
                       unit_price=Decimal("33.33"), gst_slab=0),
        BillLineInput(product_id=4, product_name="Loose Sugar", qty=Decimal("0.5"),
                       unit_price=Decimal("33.33"), gst_slab=0),
    ]
    result = compute_bill_totals(lines)
    naive_sum_of_rounded_lines = sum((line.line_total for line in result.lines), Decimal("0"))
    assert naive_sum_of_rounded_lines == Decimal("33.34")
    assert result.grand_total == Decimal("33.33")
    assert result.grand_total != naive_sum_of_rounded_lines
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_billing_math.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.billing_math'`

- [ ] **Step 3: Write minimal implementation**

`app/billing_math.py`:
```python
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

PAISA = Decimal("0.01")


@dataclass(frozen=True)
class BillLineInput:
    product_id: int
    product_name: str
    qty: Decimal
    unit_price: Decimal
    gst_slab: int


@dataclass(frozen=True)
class BillLineResult:
    product_id: int
    product_name: str
    qty: Decimal
    unit_price: Decimal
    gst_slab: int
    line_subtotal: Decimal
    cgst_amt: Decimal
    sgst_amt: Decimal
    line_total: Decimal


@dataclass(frozen=True)
class BillTotals:
    lines: list[BillLineResult] = field(default_factory=list)
    subtotal: Decimal = Decimal("0")
    cgst_total: Decimal = Decimal("0")
    sgst_total: Decimal = Decimal("0")
    grand_total: Decimal = Decimal("0")


def _round_paisa(value: Decimal) -> Decimal:
    return value.quantize(PAISA, rounding=ROUND_HALF_UP)


def compute_bill_totals(lines: list[BillLineInput]) -> BillTotals:
    raw_subtotal = Decimal("0")
    raw_cgst = Decimal("0")
    raw_sgst = Decimal("0")
    line_results = []

    for line in lines:
        line_subtotal = line.qty * line.unit_price
        line_gst = line_subtotal * Decimal(line.gst_slab) / Decimal(100)
        cgst_amt = line_gst / 2
        sgst_amt = line_gst / 2

        raw_subtotal += line_subtotal
        raw_cgst += cgst_amt
        raw_sgst += sgst_amt

        line_results.append(BillLineResult(
            product_id=line.product_id,
            product_name=line.product_name,
            qty=line.qty,
            unit_price=line.unit_price,
            gst_slab=line.gst_slab,
            line_subtotal=_round_paisa(line_subtotal),
            cgst_amt=_round_paisa(cgst_amt),
            sgst_amt=_round_paisa(sgst_amt),
            line_total=_round_paisa(line_subtotal + line_gst),
        ))

    return BillTotals(
        lines=line_results,
        subtotal=_round_paisa(raw_subtotal),
        cgst_total=_round_paisa(raw_cgst),
        sgst_total=_round_paisa(raw_sgst),
        grand_total=_round_paisa(raw_subtotal + raw_cgst + raw_sgst),
    )
```

`app/errors.py`:
```python
class DomainError(Exception):
    """Base class for typed service-layer refusals the agent must relay verbatim."""


class ProductNotFoundError(DomainError):
    def __init__(self, identifier):
        self.identifier = identifier
        super().__init__(f"No product found for {identifier!r}")


class CustomerNotFoundError(DomainError):
    def __init__(self, identifier):
        self.identifier = identifier
        super().__init__(f"No customer found for {identifier!r}")


class BelowCostError(DomainError):
    def __init__(self, sell_price, cost_price):
        self.sell_price = sell_price
        self.cost_price = cost_price
        super().__init__(f"Sell price {sell_price} is below cost price {cost_price}")


class InsufficientStockError(DomainError):
    def __init__(self, product_name, requested, available):
        self.product_name = product_name
        self.requested = requested
        self.available = available
        super().__init__(f"Only {available} of {product_name} in stock, {requested} requested")


class NoDraftBillError(DomainError):
    def __init__(self, chat_id):
        self.chat_id = chat_id
        super().__init__(f"No draft bill in progress for chat {chat_id}")


class LineNotFoundError(DomainError):
    def __init__(self, product_id):
        self.product_id = product_id
        super().__init__(f"No line for product {product_id} in the draft bill")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_billing_math.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: 21 passed

- [ ] **Step 6: Commit**

```bash
git add app/billing_math.py app/errors.py tests/test_billing_math.py
git commit -m "feat: add GST calculator and typed domain errors"
```

---

### Task 4: InventoryService

**Files:**
- Create: `app/services/__init__.py`
- Create: `app/services/inventory.py`
- Test: `tests/test_inventory_service.py`

**Interfaces:**
- Consumes: `Base`, `make_engine`, `make_session_factory` from `app.db`; `Product`, `StockMovement` from `app.models`; `BelowCostError`, `ProductNotFoundError` from `app.errors`
- Produces: `InventoryService(session_factory)` with methods `create_product(*, name, category, unit, is_loose, hsn_code, gst_slab, cost_price, sell_price, mrp, reorder_level, initial_qty=Decimal("0")) -> int` (returns new product id), `receive_stock(*, product_id, qty, cost_price=None, mrp=None) -> None`, `get_stock(*, product_id) -> Decimal`, `list_low_stock() -> list[tuple[int, str, Decimal, Decimal]]` (id, name, qty_on_hand, reorder_level)

- [ ] **Step 1: Write the failing test**

`tests/test_inventory_service.py`:
```python
from decimal import Decimal

import pytest

from app.db import Base, make_engine, make_session_factory
from app.errors import BelowCostError, ProductNotFoundError
from app.services.inventory import InventoryService


@pytest.fixture
def inventory(tmp_path):
    engine = make_engine(str(tmp_path / "inventory.db"))
    Base.metadata.create_all(engine)
    return InventoryService(make_session_factory(engine))


def test_create_product_returns_id_with_zero_default_stock(inventory):
    product_id = inventory.create_product(
        name="Parle-G", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19053100", gst_slab=5, cost_price=Decimal("8.00"),
        sell_price=Decimal("10.00"), mrp=Decimal("10.00"), reorder_level=Decimal("20"),
    )
    assert isinstance(product_id, int)
    assert inventory.get_stock(product_id=product_id) == Decimal("0")


def test_create_product_with_initial_qty(inventory):
    product_id = inventory.create_product(
        name="Maggi 70g", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19023090", gst_slab=12, cost_price=Decimal("10.00"),
        sell_price=Decimal("14.00"), mrp=Decimal("14.00"), reorder_level=Decimal("20"),
        initial_qty=Decimal("50"),
    )
    assert inventory.get_stock(product_id=product_id) == Decimal("50")


def test_create_product_rejects_unknown_unit(inventory):
    with pytest.raises(ValueError):
        inventory.create_product(
            name="Bad Unit", category="fmcg", unit="crate", is_loose=False,
            hsn_code="00000000", gst_slab=0, cost_price=Decimal("1"),
            sell_price=Decimal("2"), mrp=Decimal("2"), reorder_level=Decimal("1"),
        )


def test_create_product_rejects_unknown_gst_slab(inventory):
    with pytest.raises(ValueError):
        inventory.create_product(
            name="Bad Slab", category="fmcg", unit="packet", is_loose=False,
            hsn_code="00000000", gst_slab=7, cost_price=Decimal("1"),
            sell_price=Decimal("2"), mrp=Decimal("2"), reorder_level=Decimal("1"),
        )


def test_create_product_refuses_selling_below_cost(inventory):
    with pytest.raises(BelowCostError):
        inventory.create_product(
            name="Underpriced", category="fmcg", unit="packet", is_loose=False,
            hsn_code="00000000", gst_slab=5, cost_price=Decimal("50.00"),
            sell_price=Decimal("40.00"), mrp=Decimal("60.00"), reorder_level=Decimal("1"),
        )


def test_receive_stock_increments_qty(inventory):
    product_id = inventory.create_product(
        name="Fortune Oil 1L", category="staples", unit="packet", is_loose=False,
        hsn_code="15121900", gst_slab=5, cost_price=Decimal("140.00"),
        sell_price=Decimal("165.00"), mrp=Decimal("175.00"), reorder_level=Decimal("5"),
        initial_qty=Decimal("10"),
    )
    inventory.receive_stock(product_id=product_id, qty=Decimal("50"))
    assert inventory.get_stock(product_id=product_id) == Decimal("60")


def test_get_stock_raises_for_unknown_product(inventory):
    with pytest.raises(ProductNotFoundError):
        inventory.get_stock(product_id=99999)


def test_list_low_stock_returns_only_products_at_or_below_reorder_level(inventory):
    low_id = inventory.create_product(
        name="Almost Out", category="fmcg", unit="packet", is_loose=False,
        hsn_code="00000000", gst_slab=0, cost_price=Decimal("1"),
        sell_price=Decimal("2"), mrp=Decimal("2"), reorder_level=Decimal("10"),
        initial_qty=Decimal("3"),
    )
    inventory.create_product(
        name="Well Stocked", category="fmcg", unit="packet", is_loose=False,
        hsn_code="00000000", gst_slab=0, cost_price=Decimal("1"),
        sell_price=Decimal("2"), mrp=Decimal("2"), reorder_level=Decimal("10"),
        initial_qty=Decimal("100"),
    )
    low_stock = inventory.list_low_stock()
    low_ids = [row[0] for row in low_stock]
    assert low_id in low_ids
    assert len(low_stock) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_inventory_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services'`

- [ ] **Step 3: Write minimal implementation**

`app/services/__init__.py`:
```python
```

`app/services/inventory.py`:
```python
from decimal import Decimal

from app.errors import BelowCostError, ProductNotFoundError
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
            raise ValueError(f"unit must be one of {sorted(ALLOWED_UNITS)}, got {unit!r}")
        if gst_slab not in ALLOWED_GST_SLABS:
            raise ValueError(f"gst_slab must be one of {sorted(ALLOWED_GST_SLABS)}, got {gst_slab!r}")
        if sell_price < cost_price:
            raise BelowCostError(sell_price, cost_price)

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
            raise ValueError("qty must be positive")
        with self._session_factory() as session:
            with session.begin():
                product = session.get(Product, product_id)
                if product is None:
                    raise ProductNotFoundError(product_id)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_inventory_service.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: 29 passed

- [ ] **Step 6: Commit**

```bash
git add app/services/__init__.py app/services/inventory.py tests/test_inventory_service.py
git commit -m "feat: add InventoryService with below-cost and unit/slab guards"
```

---

### Task 5: BillingService — draft operations

**Files:**
- Create: `app/services/billing.py`
- Test: `tests/test_billing_service_draft.py`

**Interfaces:**
- Consumes: `BillLineInput`, `compute_bill_totals` from `app.billing_math`; `LineNotFoundError`, `NoDraftBillError`, `ProductNotFoundError` from `app.errors`; `DraftBill`, `Product` from `app.models`
- Produces: `BillingService(session_factory)` with `start_bill(*, chat_id, payment_mode=None) -> None`, `add_item(*, chat_id, product_id, qty) -> None`, `update_item(*, chat_id, product_id, qty) -> None`, `drop_item(*, chat_id, product_id) -> None`, `cancel_bill(*, chat_id) -> None`, `get_draft(*, chat_id) -> tuple[str | None, BillTotals]`. Task 6 adds `finalize_bill` to this same class.

- [ ] **Step 1: Write the failing test**

`tests/test_billing_service_draft.py`:
```python
from decimal import Decimal

import pytest

from app.db import Base, make_engine, make_session_factory
from app.errors import LineNotFoundError, NoDraftBillError, ProductNotFoundError
from app.services.billing import BillingService
from app.services.inventory import InventoryService


@pytest.fixture
def services(tmp_path):
    engine = make_engine(str(tmp_path / "billing.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    return InventoryService(session_factory), BillingService(session_factory)


def _make_product(inventory, name="Tata Salt 1kg", gst_slab=5, sell_price=Decimal("22.00")):
    return inventory.create_product(
        name=name, category="staples", unit="packet", is_loose=False,
        hsn_code="25010020", gst_slab=gst_slab, cost_price=Decimal("18.00"),
        sell_price=sell_price, mrp=Decimal("24.00"), reorder_level=Decimal("5"),
        initial_qty=Decimal("100"),
    )


def test_start_bill_then_get_draft_is_empty(services):
    inventory, billing = services
    billing.start_bill(chat_id="chat-1", payment_mode="upi")
    payment_mode, totals = billing.get_draft(chat_id="chat-1")
    assert payment_mode == "upi"
    assert totals.lines == []
    assert totals.grand_total == Decimal("0")


def test_add_item_appears_in_draft_totals(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))
    _, totals = billing.get_draft(chat_id="chat-1")
    assert len(totals.lines) == 1
    assert totals.lines[0].qty == Decimal("2")
    assert totals.subtotal == Decimal("44.00")


def test_add_item_twice_for_same_product_replaces_not_duplicates(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("5"))
    _, totals = billing.get_draft(chat_id="chat-1")
    assert len(totals.lines) == 1
    assert totals.lines[0].qty == Decimal("5")


def test_update_item_changes_qty(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))
    billing.update_item(chat_id="chat-1", product_id=product_id, qty=Decimal("6"))
    _, totals = billing.get_draft(chat_id="chat-1")
    assert totals.lines[0].qty == Decimal("6")


def test_update_item_raises_for_line_not_in_draft(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    with pytest.raises(LineNotFoundError):
        billing.update_item(chat_id="chat-1", product_id=product_id, qty=Decimal("1"))


def test_drop_item_removes_line(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))
    billing.drop_item(chat_id="chat-1", product_id=product_id)
    _, totals = billing.get_draft(chat_id="chat-1")
    assert totals.lines == []


def test_drop_item_raises_for_line_not_in_draft(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    with pytest.raises(LineNotFoundError):
        billing.drop_item(chat_id="chat-1", product_id=product_id)


def test_add_item_raises_for_unknown_product(services):
    inventory, billing = services
    billing.start_bill(chat_id="chat-1")
    with pytest.raises(ProductNotFoundError):
        billing.add_item(chat_id="chat-1", product_id=99999, qty=Decimal("1"))


def test_add_item_without_start_bill_raises(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    with pytest.raises(NoDraftBillError):
        billing.add_item(chat_id="never-started", product_id=product_id, qty=Decimal("1"))


def test_cancel_bill_removes_draft(services):
    inventory, billing = services
    billing.start_bill(chat_id="chat-1")
    billing.cancel_bill(chat_id="chat-1")
    with pytest.raises(NoDraftBillError):
        billing.get_draft(chat_id="chat-1")


def test_start_bill_overwrites_prior_incomplete_draft(services):
    inventory, billing = services
    product_id = _make_product(inventory)
    billing.start_bill(chat_id="chat-1")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("3"))
    billing.start_bill(chat_id="chat-1", payment_mode="cash")
    payment_mode, totals = billing.get_draft(chat_id="chat-1")
    assert payment_mode == "cash"
    assert totals.lines == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_billing_service_draft.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.billing'`

- [ ] **Step 3: Write minimal implementation**

`app/services/billing.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_billing_service_draft.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: 40 passed

- [ ] **Step 6: Commit**

```bash
git add app/services/billing.py tests/test_billing_service_draft.py
git commit -m "feat: add BillingService draft operations (start/add/update/drop/cancel)"
```

---

### Task 6: BillingService — `finalize_bill`

**Files:**
- Modify: `app/services/billing.py` (add one method to the existing `BillingService` class; add the two extra imports it needs)
- Test: `tests/test_billing_service_finalize.py`

**Interfaces:**
- Consumes: everything from Task 5, plus `Bill`, `BillItem`, `StockMovement`, `ProcessedUpdate` from `app.models` and `InsufficientStockError` from `app.errors`
- Produces: `BillingService.finalize_bill(*, chat_id, telegram_update_id, payment_mode=None, payment_ref=None) -> tuple[int, bool]` — returns `(bill_id, is_duplicate)`. `is_duplicate=True` means this `telegram_update_id` was already processed and no new writes happened.

- [ ] **Step 1: Write the failing test**

`tests/test_billing_service_finalize.py`:
```python
from decimal import Decimal

import pytest

from app.db import Base, make_engine, make_session_factory
from app.errors import InsufficientStockError, NoDraftBillError
from app.services.billing import BillingService
from app.services.inventory import InventoryService


@pytest.fixture
def services(tmp_path):
    engine = make_engine(str(tmp_path / "finalize.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    return InventoryService(session_factory), BillingService(session_factory)


def _make_product(inventory, qty=Decimal("10")):
    return inventory.create_product(
        name="Tata Salt 1kg", category="staples", unit="packet", is_loose=False,
        hsn_code="25010020", gst_slab=5, cost_price=Decimal("18.00"),
        sell_price=Decimal("22.00"), mrp=Decimal("24.00"), reorder_level=Decimal("5"),
        initial_qty=qty,
    )


def test_finalize_bill_decrements_stock_and_returns_new_bill(services):
    inventory, billing = services
    product_id = _make_product(inventory, qty=Decimal("10"))
    billing.start_bill(chat_id="chat-1", payment_mode="upi")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))

    bill_id, is_duplicate = billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-1")

    assert is_duplicate is False
    assert isinstance(bill_id, int)
    assert inventory.get_stock(product_id=product_id) == Decimal("8")


def test_finalize_bill_is_idempotent_on_same_update_id(services):
    inventory, billing = services
    product_id = _make_product(inventory, qty=Decimal("10"))
    billing.start_bill(chat_id="chat-1", payment_mode="upi")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))

    bill_id_1, dup1 = billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-1")
    bill_id_2, dup2 = billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-1")

    assert dup1 is False
    assert dup2 is True
    assert bill_id_2 == bill_id_1
    assert inventory.get_stock(product_id=product_id) == Decimal("8")  # decremented only once


def test_finalize_bill_refuses_oversell_with_no_partial_writes(services):
    inventory, billing = services
    product_id = _make_product(inventory, qty=Decimal("6"))
    billing.start_bill(chat_id="chat-1", payment_mode="cash")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("10"))

    with pytest.raises(InsufficientStockError):
        billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-x")

    assert inventory.get_stock(product_id=product_id) == Decimal("6")
    payment_mode, totals = billing.get_draft(chat_id="chat-1")
    assert payment_mode == "cash"
    assert len(totals.lines) == 1


def test_finalize_bill_raises_without_a_draft(services):
    inventory, billing = services
    with pytest.raises(NoDraftBillError):
        billing.finalize_bill(chat_id="never-started", telegram_update_id="u-y")


def test_finalize_bill_raises_without_items(services):
    inventory, billing = services
    billing.start_bill(chat_id="chat-1", payment_mode="cash")
    with pytest.raises(NoDraftBillError):
        billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-z")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_billing_service_finalize.py -v`
Expected: FAIL with `AttributeError: 'BillingService' object has no attribute 'finalize_bill'`

- [ ] **Step 3: Write minimal implementation**

At the top of `app/services/billing.py`, change the models import line to:
```python
from app.models import Bill, BillItem, DraftBill, Product, ProcessedUpdate, StockMovement
```
and add to the errors import line:
```python
from app.errors import InsufficientStockError, LineNotFoundError, NoDraftBillError, ProductNotFoundError
```

Then add this method to the `BillingService` class (after `get_draft`):
```python
    def finalize_bill(self, *, chat_id, telegram_update_id, payment_mode=None, payment_ref=None):
        with self._session_factory() as session:
            with session.begin():
                existing = session.get(ProcessedUpdate, telegram_update_id)
                if existing is not None:
                    return existing.bill_id, True

                draft = session.get(DraftBill, chat_id)
                if draft is None:
                    raise NoDraftBillError(chat_id)
                items = json.loads(draft.payload_json)["items"]
                if not items:
                    raise NoDraftBillError(chat_id)

                resolved_mode = payment_mode or draft.payment_mode
                if not resolved_mode:
                    raise ValueError("payment_mode is required to finalize a bill")

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

                # Validate every line before writing any of them.
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

                session.add(ProcessedUpdate(telegram_update_id=telegram_update_id, bill_id=bill.id))
                session.delete(draft)

                return bill.id, False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_billing_service_finalize.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: 45 passed

- [ ] **Step 6: Commit**

```bash
git add app/services/billing.py tests/test_billing_service_finalize.py
git commit -m "feat: add idempotent finalize_bill with all-or-nothing oversell guard"
```

---

### Task 7: KhataService

**Files:**
- Create: `app/services/khata.py`
- Test: `tests/test_khata_service.py`

**Interfaces:**
- Consumes: `Customer`, `KhataLedger` from `app.models`; `CustomerNotFoundError` from `app.errors`
- Produces: `KhataService(session_factory)` with `credit_customer(*, customer_name, amount, note=None) -> None` (creates the customer if this is their first khata entry), `settle_khata(*, customer_name, amount, note=None) -> None` (raises if the customer doesn't exist yet), `get_balance(*, customer_name) -> Decimal` (raises if the customer doesn't exist)

- [ ] **Step 1: Write the failing test**

`tests/test_khata_service.py`:
```python
from decimal import Decimal

import pytest

from app.db import Base, make_engine, make_session_factory
from app.errors import CustomerNotFoundError
from app.services.khata import KhataService


@pytest.fixture
def khata(tmp_path):
    engine = make_engine(str(tmp_path / "khata.db"))
    Base.metadata.create_all(engine)
    return KhataService(make_session_factory(engine))


def test_credit_customer_creates_customer_on_first_entry(khata):
    khata.credit_customer(customer_name="Ramesh", amount=Decimal("500"))
    assert khata.get_balance(customer_name="Ramesh") == Decimal("500")


def test_credit_then_payment_reduces_balance(khata):
    khata.credit_customer(customer_name="Ramesh", amount=Decimal("500"))
    khata.settle_khata(customer_name="Ramesh", amount=Decimal("300"))
    assert khata.get_balance(customer_name="Ramesh") == Decimal("200")


def test_multiple_credits_accumulate(khata):
    khata.credit_customer(customer_name="Ramesh", amount=Decimal("500"))
    khata.credit_customer(customer_name="Ramesh", amount=Decimal("150"))
    assert khata.get_balance(customer_name="Ramesh") == Decimal("650")


def test_credit_customer_name_lookup_is_case_insensitive(khata):
    khata.credit_customer(customer_name="Ramesh", amount=Decimal("500"))
    khata.credit_customer(customer_name="ramesh", amount=Decimal("100"))
    assert khata.get_balance(customer_name="RAMESH") == Decimal("600")


def test_settle_khata_raises_for_unknown_customer(khata):
    with pytest.raises(CustomerNotFoundError):
        khata.settle_khata(customer_name="Ghost", amount=Decimal("100"))


def test_get_balance_raises_for_unknown_customer(khata):
    with pytest.raises(CustomerNotFoundError):
        khata.get_balance(customer_name="Ghost")


def test_credit_customer_rejects_non_positive_amount(khata):
    with pytest.raises(ValueError):
        khata.credit_customer(customer_name="Ramesh", amount=Decimal("0"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_khata_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.khata'`

- [ ] **Step 3: Write minimal implementation**

`app/services/khata.py`:
```python
from decimal import Decimal

from app.errors import CustomerNotFoundError
from app.models import Customer, KhataLedger


class KhataService:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def credit_customer(self, *, customer_name, amount, note=None):
        if amount <= 0:
            raise ValueError("amount must be positive")
        with self._session_factory() as session:
            with session.begin():
                customer = session.query(Customer).filter(
                    Customer.name.ilike(customer_name)
                ).one_or_none()
                if customer is None:
                    customer = Customer(name=customer_name)
                    session.add(customer)
                    session.flush()
                session.add(KhataLedger(
                    customer_id=customer.id, amount=amount, direction="credit", note=note,
                ))

    def settle_khata(self, *, customer_name, amount, note=None):
        if amount <= 0:
            raise ValueError("amount must be positive")
        with self._session_factory() as session:
            with session.begin():
                customer = session.query(Customer).filter(
                    Customer.name.ilike(customer_name)
                ).one_or_none()
                if customer is None:
                    raise CustomerNotFoundError(customer_name)
                session.add(KhataLedger(
                    customer_id=customer.id, amount=amount, direction="payment", note=note,
                ))

    def get_balance(self, *, customer_name):
        with self._session_factory() as session:
            customer = session.query(Customer).filter(
                Customer.name.ilike(customer_name)
            ).one_or_none()
            if customer is None:
                raise CustomerNotFoundError(customer_name)
            entries = session.query(KhataLedger).filter(
                KhataLedger.customer_id == customer.id
            ).all()
            balance = Decimal("0")
            for entry in entries:
                if entry.direction == "credit":
                    balance += entry.amount
                else:
                    balance -= entry.amount
            return balance
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_khata_service.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: 52 passed

- [ ] **Step 6: Commit**

```bash
git add app/services/khata.py tests/test_khata_service.py
git commit -m "feat: add KhataService with append-only credit ledger"
```

---

### Task 8: Concurrency integration test — the actual hard part

**Files:**
- Test: `tests/test_concurrency_billing.py` (no production code changes — this task proves Tasks 1-6 compose correctly under real concurrent load)

**Interfaces:**
- Consumes: `InventoryService`, `BillingService` (Tasks 4-6), `InsufficientStockError` from `app.errors`
- Produces: nothing new — this is a verification-only task

- [ ] **Step 1: Write the test**

`tests/test_concurrency_billing.py`:
```python
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
```

- [ ] **Step 2: Run it**

Run: `pytest tests/test_concurrency_billing.py -v`
Expected: PASS (2 passed). `test_concurrent_finalize_does_not_oversell`: with only 1 unit in stock and two concurrent bills each wanting 1, `BEGIN IMMEDIATE` (Task 1) serializes the two `finalize_bill` transactions — whichever acquires the lock first sees stock=1, succeeds, and decrements to 0; the second then sees stock=0 and raises `InsufficientStockError`. `test_concurrent_receive_stock_and_finalize_do_not_lose_updates`: covers the spec's other named concurrency scenario (a sale in flight alongside a stock receipt) — serialized writes mean the final quantity is always `10 + 50 - 4 = 56` regardless of which one's transaction happens to run first. If either fails, re-check Task 1 and Task 6 rather than editing this test — this test is the proof that they compose correctly, not a place to loosen assertions.

- [ ] **Step 3: Run the full suite**

Run: `pytest -v`
Expected: 54 passed

- [ ] **Step 4: Commit**

```bash
git add tests/test_concurrency_billing.py
git commit -m "test: verify concurrent finalize_bill cannot oversell or lose stock updates"
```

---

### Task 9: Seed script (deferred from Phase 0)

**Files:**
- Create: `scripts/__init__.py`
- Create: `scripts/seed_dev_data.py`
- Test: `tests/test_seed_dev_data.py`

**Interfaces:**
- Consumes: `load_settings` from `app.config`; `Base`, `make_engine`, `make_session_factory` from `app.db`; `InventoryService` from `app.services.inventory`
- Produces: `SEED_PRODUCTS` (list of dicts, one per SKU), `seed(session_factory) -> list[tuple[int, str]]` (product id, name), `main()` (CLI entrypoint reading local settings)

- [ ] **Step 1: Write the failing test**

`tests/test_seed_dev_data.py`:
```python
from decimal import Decimal

from app.db import Base, make_engine, make_session_factory
from app.services.inventory import InventoryService
from scripts.seed_dev_data import SEED_PRODUCTS, seed


def test_seed_creates_all_products_with_positive_stock(tmp_path):
    engine = make_engine(str(tmp_path / "seed.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    created = seed(session_factory)

    assert len(created) == len(SEED_PRODUCTS)
    inventory = InventoryService(session_factory)
    for product_id, name in created:
        qty = inventory.get_stock(product_id=product_id)
        assert qty > Decimal("0"), f"{name} seeded with zero stock"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_seed_dev_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.seed_dev_data'`

- [ ] **Step 3: Write minimal implementation**

`scripts/__init__.py`:
```python
```

`scripts/seed_dev_data.py`:
```python
from decimal import Decimal

from app.config import load_settings
from app.db import Base, make_engine, make_session_factory
from app.services.inventory import InventoryService

SEED_PRODUCTS = [
    dict(name="Aashirvaad Atta 5kg", category="staples", unit="packet", is_loose=False,
         hsn_code="11010000", gst_slab=0, cost_price=Decimal("220.00"),
         sell_price=Decimal("250.00"), mrp=Decimal("260.00"),
         reorder_level=Decimal("5"), initial_qty=Decimal("20")),
    dict(name="Tata Salt 1kg", category="staples", unit="packet", is_loose=False,
         hsn_code="25010020", gst_slab=5, cost_price=Decimal("18.00"),
         sell_price=Decimal("22.00"), mrp=Decimal("24.00"),
         reorder_level=Decimal("10"), initial_qty=Decimal("40")),
    dict(name="Amul Butter 100g", category="dairy", unit="packet", is_loose=False,
         hsn_code="04051000", gst_slab=12, cost_price=Decimal("48.00"),
         sell_price=Decimal("58.00"), mrp=Decimal("62.00"),
         reorder_level=Decimal("10"), initial_qty=Decimal("30")),
    dict(name="Fortune Sunflower Oil 1L", category="staples", unit="packet", is_loose=False,
         hsn_code="15121900", gst_slab=5, cost_price=Decimal("140.00"),
         sell_price=Decimal("165.00"), mrp=Decimal("175.00"),
         reorder_level=Decimal("5"), initial_qty=Decimal("15")),
    dict(name="Maggi 70g", category="fmcg", unit="packet", is_loose=False,
         hsn_code="19023090", gst_slab=12, cost_price=Decimal("10.00"),
         sell_price=Decimal("14.00"), mrp=Decimal("14.00"),
         reorder_level=Decimal("20"), initial_qty=Decimal("100")),
    dict(name="Parle-G", category="fmcg", unit="packet", is_loose=False,
         hsn_code="19053100", gst_slab=5, cost_price=Decimal("8.00"),
         sell_price=Decimal("10.00"), mrp=Decimal("10.00"),
         reorder_level=Decimal("20"), initial_qty=Decimal("100")),
    dict(name="Surf Excel 1kg", category="fmcg", unit="packet", is_loose=False,
         hsn_code="34022090", gst_slab=18, cost_price=Decimal("95.00"),
         sell_price=Decimal("115.00"), mrp=Decimal("125.00"),
         reorder_level=Decimal("5"), initial_qty=Decimal("15")),
    dict(name="Sugar (loose)", category="staples", unit="kg", is_loose=True,
         hsn_code="17019900", gst_slab=0, cost_price=Decimal("38.00"),
         sell_price=Decimal("44.00"), mrp=Decimal("44.00"),
         reorder_level=Decimal("10"), initial_qty=Decimal("50")),
    dict(name="Rice (loose)", category="staples", unit="kg", is_loose=True,
         hsn_code="10063090", gst_slab=0, cost_price=Decimal("42.00"),
         sell_price=Decimal("48.00"), mrp=Decimal("48.00"),
         reorder_level=Decimal("10"), initial_qty=Decimal("50")),
    dict(name="Toor Dal (loose)", category="staples", unit="kg", is_loose=True,
         hsn_code="07136000", gst_slab=0, cost_price=Decimal("95.00"),
         sell_price=Decimal("108.00"), mrp=Decimal("108.00"),
         reorder_level=Decimal("10"), initial_qty=Decimal("30")),
]


def seed(session_factory):
    inventory = InventoryService(session_factory)
    created = []
    for spec in SEED_PRODUCTS:
        product_id = inventory.create_product(**spec)
        created.append((product_id, spec["name"]))
    return created


def main():
    settings = load_settings()
    engine = make_engine(settings.db_path)
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    for product_id, name in seed(session_factory):
        print(f"seeded #{product_id}: {name}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_seed_dev_data.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: 55 passed

- [ ] **Step 6: Commit**

```bash
git add scripts/__init__.py scripts/seed_dev_data.py tests/test_seed_dev_data.py
git commit -m "feat: add seed script for real kirana SKUs (deferred from Phase 0)"
```
