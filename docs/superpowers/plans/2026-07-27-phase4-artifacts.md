# Phase 4 — Artifacts: PDF Invoice + PPTX Analysis Deck Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Real, agent-generated document artifacts — a GST-correct PDF invoice from `reportlab`, and a sales-analysis PPTX deck with real matplotlib charts from `python-pptx` — deliverable through both the CLI and Telegram channels.

**Architecture:** `InvoiceService` and `AnalyticsService` are pure Python + SQLAlchemy, following the exact same pattern as Phase 1's services (no agent involved). Their tools (`render_invoice_pdf`, `get_daily_summary`, `render_analysis_deck`) generate bytes in memory and hand them off via a new shared mutable `ArtifactContext` — the same pattern `UpdateContext` already established in Phase 2 for `finalize_bill`'s idempotency key, just for binary output instead of input. `AgentSession.send()` now returns a small `SendResult(text, artifact)` instead of a bare string, and both channels (CLI, Telegram) are updated to deliver the artifact: the CLI writes it to `./data/artifacts/` and prints the path, Telegram sends it as a document.

**Tech Stack:** `reportlab` (PDF), `matplotlib` with the `Agg` backend (charts, no display needed), `python-pptx` (deck) — all verified installed and working before this plan was written (confirmed: `SimpleDocTemplate`+`Table`+`Paragraph` produce a valid PDF; `Presentation().slide_layouts` names/indices; `add_picture` from an in-memory `BytesIO` PNG; `text_frame.add_paragraph()`).

## Global Constraints

- No placeholder/TODO code
- `render_invoice_pdf` and `render_analysis_deck` never touch the agent's text conversation with binary data — they hand bytes off via `ArtifactContext`, and the tool's own text response is a short human-readable confirmation only
- `bill_id` for `render_invoice_pdf` is a required tool parameter (not looked up implicitly) — the model already has the bill id in its own conversation from when `finalize_bill` reported it (e.g. "Bill #12 finalized"), so no new lookup method is needed on `BillingService`
- Dates cross the tool boundary as `YYYY-MM-DD` strings, parsed via `datetime.strptime(...).date()`
- `AgentSession.send()`'s return type changes from `str` to `SendResult` — every existing call site (`CLIChannel`, `TelegramChannel`, and their tests) must be updated in the same task that makes the change, not left broken

## Verified Library Behavior (confirmed before this plan was written)

- `reportlab.platypus.SimpleDocTemplate` + `Table`/`TableStyle`/`Paragraph` + `.build([...])` on an `io.BytesIO()` produces real PDF bytes (`b"%PDF"` header confirmed).
- `matplotlib` with `matplotlib.use("Agg")` set before importing `pyplot` renders figures to PNG bytes via `fig.savefig(buf, format="png")` with no display/GUI backend needed (confirmed in this headless environment).
- `python-pptx`'s `Presentation().slide_layouts` are, by index: `0` = "Title Slide" (has a title placeholder and a subtitle at `placeholders[1]`), `1` = "Title and Content" (title + a body placeholder at `placeholders[1]` whose `.text_frame` supports `.text = ...` then `.add_paragraph()` for further lines), `5` = "Title Only" (title, no content placeholder — used for full-bleed chart images via `shapes.add_picture(image_stream, ...)`). Confirmed live: built a 2-slide deck (title + chart) and verified the output is a valid `PK`-zip (pptx file signature).

---

### Task 1: `BillNotFoundError` + `InvoiceService`

**Files:**
- Modify: `app/errors.py` (add one error class)
- Create: `app/services/invoice.py`
- Modify: `pyproject.toml` (add `reportlab` dependency)
- Test: `tests/test_invoice_service.py`

**Interfaces:**
- Consumes: `Bill`, `BillItem`, `Product` from `app.models`; `DomainError` from `app.errors`; `PreferencesService` from `app.services.preferences`
- Produces: `BillNotFoundError(DomainError)`; `InvoiceService(session_factory, preferences)` with `render_invoice_pdf(*, bill_id: int) -> bytes`

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`'s `dependencies` list, add:
```toml
    "reportlab>=5.0,<6.0",
```

- [ ] **Step 2: Write the failing test**

`tests/test_invoice_service.py`:
```python
from decimal import Decimal

import pytest

from app.db import Base, make_engine, make_session_factory
from app.errors import BillNotFoundError
from app.services.billing import BillingService
from app.services.inventory import InventoryService
from app.services.invoice import InvoiceService
from app.services.preferences import PreferencesService


def _make_services(tmp_path):
    engine = make_engine(str(tmp_path / "invoice.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    inventory = InventoryService(session_factory)
    billing = BillingService(session_factory)
    preferences = PreferencesService(session_factory)
    invoice = InvoiceService(session_factory, preferences)
    return inventory, billing, preferences, invoice


def _finalize_a_bill(inventory, billing, chat_id="chat-1", update_id="u-1"):
    product_id = inventory.create_product(
        name="Tata Salt 1kg", category="staples", unit="packet", is_loose=False,
        hsn_code="25010020", gst_slab=5, cost_price=Decimal("18.00"),
        sell_price=Decimal("22.00"), mrp=Decimal("24.00"), reorder_level=Decimal("5"),
        initial_qty=Decimal("10"),
    )
    billing.start_bill(chat_id=chat_id, payment_mode="upi")
    billing.add_item(chat_id=chat_id, product_id=product_id, qty=Decimal("2"))
    bill_id, _ = billing.finalize_bill(chat_id=chat_id, telegram_update_id=update_id)
    return bill_id


def test_render_invoice_pdf_produces_real_pdf_bytes(tmp_path):
    inventory, billing, preferences, invoice = _make_services(tmp_path)
    bill_id = _finalize_a_bill(inventory, billing)

    pdf_bytes = invoice.render_invoice_pdf(bill_id=bill_id)

    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 500


def test_render_invoice_pdf_includes_shop_preferences(tmp_path):
    inventory, billing, preferences, invoice = _make_services(tmp_path)
    preferences.set_preference(key="shop_name", value="Sharma Kirana Store")
    bill_id = _finalize_a_bill(inventory, billing)

    pdf_bytes = invoice.render_invoice_pdf(bill_id=bill_id)

    assert b"Sharma Kirana Store" in pdf_bytes


def test_render_invoice_pdf_raises_for_unknown_bill(tmp_path):
    _, _, _, invoice = _make_services(tmp_path)
    with pytest.raises(BillNotFoundError):
        invoice.render_invoice_pdf(bill_id=99999)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_invoice_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'BillNotFoundError'` (or `ModuleNotFoundError` for `app.services.invoice`)

- [ ] **Step 4: Write minimal implementation**

Add to `app/errors.py` (after the existing error classes):
```python
class BillNotFoundError(DomainError):
    def __init__(self, bill_id):
        self.bill_id = bill_id
        super().__init__(f"No bill found with id {bill_id}")
```

`app/services/invoice.py`:
```python
import io
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.errors import BillNotFoundError
from app.models import Bill, BillItem, Product


class InvoiceService:
    def __init__(self, session_factory, preferences):
        self._session_factory = session_factory
        self._preferences = preferences

    def render_invoice_pdf(self, *, bill_id: int) -> bytes:
        with self._session_factory() as session:
            bill = session.get(Bill, bill_id)
            if bill is None:
                raise BillNotFoundError(bill_id)

            rows = (
                session.query(BillItem, Product)
                .join(Product, BillItem.product_id == Product.id)
                .filter(BillItem.bill_id == bill_id)
                .all()
            )

            shop_name = self._preferences.get_preference(key="shop_name", default="Kirana Store")
            gstin = self._preferences.get_preference(key="gstin", default="—")
            shop_address = self._preferences.get_preference(key="shop_address", default="")

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm)
            styles = getSampleStyleSheet()
            elements = []

            elements.append(Paragraph(shop_name, styles["Title"]))
            if shop_address:
                elements.append(Paragraph(shop_address, styles["Normal"]))
            elements.append(Paragraph(f"GSTIN: {gstin}", styles["Normal"]))
            elements.append(Spacer(1, 8))
            elements.append(Paragraph(f"Tax Invoice #{bill.id}", styles["Heading2"]))
            elements.append(Paragraph(
                f"Date: {bill.created_at.strftime('%d-%b-%Y %H:%M')}", styles["Normal"],
            ))
            elements.append(Paragraph(f"Payment mode: {bill.payment_mode.upper()}", styles["Normal"]))
            if bill.payment_ref:
                elements.append(Paragraph(f"Payment ref: {bill.payment_ref}", styles["Normal"]))
            elements.append(Spacer(1, 12))

            table_data = [["Item", "HSN", "Qty", "Rate", "Taxable Val", "CGST", "SGST", "Total"]]
            for bill_item, product in rows:
                taxable_value = bill_item.qty * bill_item.unit_price
                table_data.append([
                    product.name,
                    product.hsn_code,
                    f"{bill_item.qty} {product.unit}",
                    f"{bill_item.unit_price:.2f}",
                    f"{taxable_value:.2f}",
                    f"{bill_item.cgst_amt:.2f}",
                    f"{bill_item.sgst_amt:.2f}",
                    f"{bill_item.line_total:.2f}",
                ])

            table = Table(table_data, repeatRows=1)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f3b52")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 12))

            # Standard GST-invoice "round off" line: the persisted per-line
            # totals and the persisted bill-level grand_total are each
            # independently reconciled (see app/billing_math.py) rather than
            # cross-summed, so on a multi-line bill with sub-paisa amounts
            # they can differ by a paisa. Showing the delta explicitly is
            # what makes the printed breakup visibly reconcile instead of
            # silently being a paisa off.
            sum_line_totals = sum((bi.line_total for bi, _ in rows), Decimal("0"))
            round_off = bill.grand_total - sum_line_totals

            totals_data = [
                ["Subtotal", f"{bill.subtotal:.2f}"],
                ["CGST", f"{bill.cgst_total:.2f}"],
                ["SGST", f"{bill.sgst_total:.2f}"],
                ["Round off", f"{round_off:.2f}"],
                ["Grand Total", f"{bill.grand_total:.2f}"],
            ]
            totals_table = Table(totals_data, colWidths=[110 * 0.7 * mm, 90 * 0.7 * mm])
            totals_table.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ]))
            elements.append(totals_table)

            doc.build(elements)
            return buffer.getvalue()
```

- [ ] **Step 5: Run test to verify it passes, then full suite**

Run: `pytest tests/test_invoice_service.py -v` — expect 3 passed
Run: `pytest -v` — expect 154 passed (151 from Phase 3 + 3 new)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml app/errors.py app/services/invoice.py tests/test_invoice_service.py
git commit -m "feat: add InvoiceService generating GST-correct PDF invoices"
```

---

### Task 2: `AnalyticsService`

**Files:**
- Modify: `pyproject.toml` (add `matplotlib` and `python-pptx` dependencies)
- Create: `app/services/analytics.py`
- Test: `tests/test_analytics_service.py`

**Interfaces:**
- Consumes: `Bill`, `BillItem`, `Product` from `app.models`
- Produces: `AnalyticsService(session_factory)` with `get_daily_summary(*, target_date: date | None = None) -> dict` (keys: `date`, `bill_count`, `total_sales`, `tax_collected`, `by_payment_mode`, `top_items`) and `render_analysis_deck(*, start_date: date, end_date: date) -> bytes` (a valid `.pptx` file)

- [ ] **Step 1: Add the dependencies**

In `pyproject.toml`'s `dependencies` list, add:
```toml
    "matplotlib>=3.11,<4.0",
    "python-pptx>=1.0,<2.0",
```

- [ ] **Step 2: Write the failing test**

`tests/test_analytics_service.py`:
```python
from datetime import date
from decimal import Decimal

from app.db import Base, make_engine, make_session_factory
from app.services.analytics import AnalyticsService
from app.services.billing import BillingService
from app.services.inventory import InventoryService


def _make_services(tmp_path):
    engine = make_engine(str(tmp_path / "analytics.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    return (
        InventoryService(session_factory),
        BillingService(session_factory),
        AnalyticsService(session_factory),
    )


def _finalize_a_bill(inventory, billing, product_id, qty, chat_id, update_id, mode="upi"):
    billing.start_bill(chat_id=chat_id, payment_mode=mode)
    billing.add_item(chat_id=chat_id, product_id=product_id, qty=qty)
    return billing.finalize_bill(chat_id=chat_id, telegram_update_id=update_id)


def test_get_daily_summary_reflects_todays_finalized_bills(tmp_path):
    inventory, billing, analytics = _make_services(tmp_path)
    product_id = inventory.create_product(
        name="Maggi 70g", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19023090", gst_slab=12, cost_price=Decimal("10.00"),
        sell_price=Decimal("14.00"), mrp=Decimal("14.00"), reorder_level=Decimal("20"),
        initial_qty=Decimal("100"),
    )
    _finalize_a_bill(inventory, billing, product_id, Decimal("4"), "chat-1", "u-1", mode="cash")
    _finalize_a_bill(inventory, billing, product_id, Decimal("2"), "chat-2", "u-2", mode="upi")

    summary = analytics.get_daily_summary()

    assert summary["date"] == date.today()
    assert summary["bill_count"] == 2
    assert summary["total_sales"] > Decimal("0")
    assert summary["tax_collected"] > Decimal("0")
    assert set(summary["by_payment_mode"].keys()) == {"cash", "upi"}
    assert summary["top_items"][0][0] == "Maggi 70g"


def test_get_daily_summary_for_empty_day_returns_zeroes(tmp_path):
    _, _, analytics = _make_services(tmp_path)

    summary = analytics.get_daily_summary(target_date=date(2020, 1, 1))

    assert summary["bill_count"] == 0
    assert summary["total_sales"] == Decimal("0")
    assert summary["top_items"] == []


def test_render_analysis_deck_produces_a_valid_pptx(tmp_path):
    inventory, billing, analytics = _make_services(tmp_path)
    product_id = inventory.create_product(
        name="Parle-G", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19053100", gst_slab=5, cost_price=Decimal("8.00"),
        sell_price=Decimal("10.00"), mrp=Decimal("10.00"), reorder_level=Decimal("20"),
        initial_qty=Decimal("50"),
    )
    _finalize_a_bill(inventory, billing, product_id, Decimal("3"), "chat-1", "u-1")

    today = date.today()
    pptx_bytes = analytics.render_analysis_deck(start_date=today, end_date=today)

    assert pptx_bytes[:2] == b"PK"  # pptx is a zip archive
    assert len(pptx_bytes) > 1000
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_analytics_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.analytics'`

- [ ] **Step 4: Write minimal implementation**

`app/services/analytics.py`:
```python
import io
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.util import Inches  # noqa: E402

from app.models import Bill, BillItem, Product  # noqa: E402


def _line_chart_png(x_labels: list[date], y_values: list[float], *, title: str, ylabel: str) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(range(len(x_labels)), y_values, marker="o")
    ax.set_xticks(range(len(x_labels)))
    ax.set_xticklabels([d.strftime("%d-%b") for d in x_labels], rotation=45, ha="right")
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def _bar_chart_png(labels: list[str], values: list[float], *, title: str) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.barh(labels, values)
    ax.set_title(title)
    ax.invert_yaxis()
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


class AnalyticsService:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def get_daily_summary(self, *, target_date: date | None = None) -> dict:
        target_date = target_date or datetime.now(timezone.utc).date()
        with self._session_factory() as session:
            bills = session.query(Bill).filter(Bill.status == "finalized").all()
            day_bills = [b for b in bills if b.created_at.date() == target_date]

            total_sales = sum((b.grand_total for b in day_bills), Decimal("0"))
            tax_collected = sum((b.cgst_total + b.sgst_total for b in day_bills), Decimal("0"))

            by_mode: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
            for b in day_bills:
                by_mode[b.payment_mode] += b.grand_total

            item_qty: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
            bill_ids = [b.id for b in day_bills]
            if bill_ids:
                rows = (
                    session.query(BillItem, Product)
                    .join(Product, BillItem.product_id == Product.id)
                    .filter(BillItem.bill_id.in_(bill_ids))
                    .all()
                )
                for bill_item, product in rows:
                    item_qty[product.name] += bill_item.qty
            top_items = sorted(item_qty.items(), key=lambda kv: kv[1], reverse=True)[:5]

            return {
                "date": target_date,
                "bill_count": len(day_bills),
                "total_sales": total_sales,
                "tax_collected": tax_collected,
                "by_payment_mode": dict(by_mode),
                "top_items": top_items,
            }

    def render_analysis_deck(self, *, start_date: date, end_date: date) -> bytes:
        with self._session_factory() as session:
            bills = session.query(Bill).filter(Bill.status == "finalized").all()
            in_range = [b for b in bills if start_date <= b.created_at.date() <= end_date]

            daily_totals: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
            daily_gst: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
            for b in in_range:
                d = b.created_at.date()
                daily_totals[d] += b.grand_total
                daily_gst[d] += b.cgst_total + b.sgst_total

            date_range = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]
            sales_series = [float(daily_totals.get(d, Decimal("0"))) for d in date_range]

            item_qty: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
            bill_ids = [b.id for b in in_range]
            if bill_ids:
                rows = (
                    session.query(BillItem, Product)
                    .join(Product, BillItem.product_id == Product.id)
                    .filter(BillItem.bill_id.in_(bill_ids))
                    .all()
                )
                for bill_item, product in rows:
                    item_qty[product.name] += bill_item.qty
            top_items = sorted(item_qty.items(), key=lambda kv: kv[1], reverse=True)[:8]

            low_stock = (
                session.query(Product)
                .filter(Product.qty_on_hand <= Product.reorder_level)
                .order_by(Product.name)
                .all()
            )

            total_sales = sum(daily_totals.values(), Decimal("0"))
            total_gst = sum(daily_gst.values(), Decimal("0"))
            bill_count = len(in_range)
            low_stock_names = [p.name for p in low_stock]

        sales_chart = _line_chart_png(date_range, sales_series, title="Daily Sales (Rs)", ylabel="Rs")
        top_items_chart = None
        if top_items:
            top_items_chart = _bar_chart_png(
                [name for name, _ in top_items], [float(qty) for _, qty in top_items],
                title="Top Items by Quantity Sold",
            )

        prs = Presentation()

        title_slide = prs.slides.add_slide(prs.slide_layouts[0])
        title_slide.shapes.title.text = "Sales Analysis"
        title_slide.placeholders[1].text = f"{start_date} to {end_date}"

        sales_slide = prs.slides.add_slide(prs.slide_layouts[5])
        sales_slide.shapes.title.text = "Daily Sales Trend"
        sales_slide.shapes.add_picture(sales_chart, Inches(0.5), Inches(1.3), width=Inches(9))

        if top_items_chart is not None:
            items_slide = prs.slides.add_slide(prs.slide_layouts[5])
            items_slide.shapes.title.text = "Top Items"
            items_slide.shapes.add_picture(top_items_chart, Inches(0.5), Inches(1.3), width=Inches(9))

        summary_slide = prs.slides.add_slide(prs.slide_layouts[1])
        summary_slide.shapes.title.text = "Summary"
        body = summary_slide.placeholders[1].text_frame
        lines = [
            f"Bills: {bill_count}",
            f"Total sales: Rs {total_sales:.2f}",
            f"GST collected: Rs {total_gst:.2f}",
        ]
        if low_stock_names:
            lines.append(f"Running low: {', '.join(low_stock_names)}")
        else:
            lines.append("Nothing running low on stock.")
        body.text = lines[0]
        for line in lines[1:]:
            body.add_paragraph().text = line

        buffer = io.BytesIO()
        prs.save(buffer)
        return buffer.getvalue()
```

- [ ] **Step 5: Run test to verify it passes, then full suite**

Run: `pytest tests/test_analytics_service.py -v` — expect 3 passed
Run: `pytest -v` — expect 157 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml app/services/analytics.py tests/test_analytics_service.py
git commit -m "feat: add AnalyticsService with real matplotlib charts and PPTX deck"
```

---

### Task 3: `ArtifactContext` + invoicing/analytics tools

**Files:**
- Create: `app/tools/artifact_context.py`
- Create: `app/tools/invoicing_tools.py`
- Create: `app/tools/analytics_tools.py`
- Test: `tests/test_artifact_context.py`
- Test: `tests/test_invoicing_tools.py`
- Test: `tests/test_analytics_tools.py`

**Interfaces:**
- Consumes: `InvoiceService`, `AnalyticsService`, `DomainError`
- Produces: `ArtifactPayload` (frozen dataclass: `data: bytes`, `filename: str`, `mime_type: str`), `ArtifactContext` with `set(*, data, filename, mime_type) -> None` and `pop() -> ArtifactPayload | None` (clears after popping); `build_invoicing_tools(invoice_service, artifact_context) -> list[SdkMcpTool]` (1 tool: `render_invoice_pdf`); `build_analytics_tools(analytics_service, artifact_context) -> list[SdkMcpTool]` (2 tools: `get_daily_summary`, `render_analysis_deck`)

- [ ] **Step 1: Write the failing tests**

`tests/test_artifact_context.py`:
```python
from app.tools.artifact_context import ArtifactContext


def test_pop_returns_none_when_nothing_set():
    ctx = ArtifactContext()
    assert ctx.pop() is None


def test_set_then_pop_returns_payload_and_clears():
    ctx = ArtifactContext()
    ctx.set(data=b"hello", filename="a.pdf", mime_type="application/pdf")

    payload = ctx.pop()

    assert payload.data == b"hello"
    assert payload.filename == "a.pdf"
    assert payload.mime_type == "application/pdf"
    assert ctx.pop() is None
```

`tests/test_invoicing_tools.py`:
```python
import asyncio
from decimal import Decimal

from app.db import Base, make_engine, make_session_factory
from app.services.billing import BillingService
from app.services.inventory import InventoryService
from app.services.invoice import InvoiceService
from app.services.preferences import PreferencesService
from app.tools.artifact_context import ArtifactContext
from app.tools.invoicing_tools import build_invoicing_tools


def _make_services(tmp_path):
    engine = make_engine(str(tmp_path / "invoicing_tools.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    inventory = InventoryService(session_factory)
    billing = BillingService(session_factory)
    preferences = PreferencesService(session_factory)
    invoice = InvoiceService(session_factory, preferences)
    return inventory, billing, invoice


def test_render_invoice_pdf_sets_artifact_and_confirms(tmp_path):
    inventory, billing, invoice = _make_services(tmp_path)
    product_id = inventory.create_product(
        name="Tata Salt 1kg", category="staples", unit="packet", is_loose=False,
        hsn_code="25010020", gst_slab=5, cost_price=Decimal("18.00"),
        sell_price=Decimal("22.00"), mrp=Decimal("24.00"), reorder_level=Decimal("5"),
        initial_qty=Decimal("10"),
    )
    billing.start_bill(chat_id="chat-1", payment_mode="upi")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("2"))
    bill_id, _ = billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-1")

    ctx = ArtifactContext()
    tools = {t.name: t for t in build_invoicing_tools(invoice, ctx)}
    result = asyncio.run(tools["render_invoice_pdf"].handler({"bill_id": bill_id}))

    assert not result.get("is_error")
    payload = ctx.pop()
    assert payload is not None
    assert payload.data[:4] == b"%PDF"
    assert payload.filename == f"invoice-{bill_id}.pdf"
    assert payload.mime_type == "application/pdf"


def test_render_invoice_pdf_is_error_for_unknown_bill(tmp_path):
    inventory, billing, invoice = _make_services(tmp_path)
    ctx = ArtifactContext()
    tools = {t.name: t for t in build_invoicing_tools(invoice, ctx)}

    result = asyncio.run(tools["render_invoice_pdf"].handler({"bill_id": 99999}))

    assert result.get("is_error") is True
    assert ctx.pop() is None
```

`tests/test_analytics_tools.py`:
```python
import asyncio
from datetime import date
from decimal import Decimal

from app.db import Base, make_engine, make_session_factory
from app.services.analytics import AnalyticsService
from app.services.billing import BillingService
from app.services.inventory import InventoryService
from app.tools.analytics_tools import build_analytics_tools
from app.tools.artifact_context import ArtifactContext


def _make_services(tmp_path):
    engine = make_engine(str(tmp_path / "analytics_tools.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    return (
        InventoryService(session_factory),
        BillingService(session_factory),
        AnalyticsService(session_factory),
    )


def test_get_daily_summary_reports_totals(tmp_path):
    inventory, billing, analytics = _make_services(tmp_path)
    product_id = inventory.create_product(
        name="Maggi 70g", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19023090", gst_slab=12, cost_price=Decimal("10.00"),
        sell_price=Decimal("14.00"), mrp=Decimal("14.00"), reorder_level=Decimal("20"),
        initial_qty=Decimal("100"),
    )
    billing.start_bill(chat_id="chat-1", payment_mode="cash")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("4"))
    billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-1")

    ctx = ArtifactContext()
    tools = {t.name: t for t in build_analytics_tools(analytics, ctx)}
    result = asyncio.run(tools["get_daily_summary"].handler({}))

    assert not result.get("is_error")
    assert "Maggi" in result["content"][0]["text"]
    assert ctx.pop() is None  # get_daily_summary never produces a file artifact


def test_render_analysis_deck_sets_artifact(tmp_path):
    inventory, billing, analytics = _make_services(tmp_path)
    product_id = inventory.create_product(
        name="Parle-G", category="fmcg", unit="packet", is_loose=False,
        hsn_code="19053100", gst_slab=5, cost_price=Decimal("8.00"),
        sell_price=Decimal("10.00"), mrp=Decimal("10.00"), reorder_level=Decimal("20"),
        initial_qty=Decimal("50"),
    )
    billing.start_bill(chat_id="chat-1", payment_mode="upi")
    billing.add_item(chat_id="chat-1", product_id=product_id, qty=Decimal("3"))
    billing.finalize_bill(chat_id="chat-1", telegram_update_id="u-1")

    ctx = ArtifactContext()
    tools = {t.name: t for t in build_analytics_tools(analytics, ctx)}
    today = date.today().isoformat()
    result = asyncio.run(tools["render_analysis_deck"].handler(
        {"start_date": today, "end_date": today}
    ))

    assert not result.get("is_error")
    payload = ctx.pop()
    assert payload is not None
    assert payload.data[:2] == b"PK"
    assert payload.mime_type == (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_artifact_context.py tests/test_invoicing_tools.py tests/test_analytics_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

`app/tools/artifact_context.py`:
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactPayload:
    data: bytes
    filename: str
    mime_type: str


class ArtifactContext:
    def __init__(self):
        self._pending: ArtifactPayload | None = None

    def set(self, *, data: bytes, filename: str, mime_type: str) -> None:
        self._pending = ArtifactPayload(data=data, filename=filename, mime_type=mime_type)

    def pop(self) -> ArtifactPayload | None:
        payload = self._pending
        self._pending = None
        return payload
```

`app/tools/invoicing_tools.py`:
```python
import asyncio

from claude_agent_sdk import tool

from app.errors import DomainError


def build_invoicing_tools(invoice_service, artifact_context):
    @tool(
        "render_invoice_pdf",
        "Generate a GST-correct PDF invoice for a finalized bill, given its bill id "
        "(the number shown when the bill was finalized, e.g. 'Bill #12').",
        {"bill_id": int},
    )
    async def render_invoice_pdf(args):
        try:
            pdf_bytes = await asyncio.to_thread(
                invoice_service.render_invoice_pdf, bill_id=args["bill_id"],
            )
        except DomainError as exc:
            return {"content": [{"type": "text", "text": f"Refused: {exc}"}], "is_error": True}
        artifact_context.set(
            data=pdf_bytes, filename=f"invoice-{args['bill_id']}.pdf", mime_type="application/pdf",
        )
        return {"content": [{"type": "text",
                              "text": f"Generated the GST invoice PDF for Bill #{args['bill_id']}."}]}

    return [render_invoice_pdf]
```

`app/tools/analytics_tools.py`:
```python
import asyncio
from datetime import datetime

from claude_agent_sdk import tool

PPTX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _parse_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()


def build_analytics_tools(analytics_service, artifact_context):
    @tool(
        "get_daily_summary",
        "Get today's (or a given date's) sales summary: total sales, tax collected, "
        "cash vs UPI vs card split, and top-selling items.",
        {
            "type": "object",
            "properties": {
                "target_date": {"type": "string", "description": "YYYY-MM-DD, defaults to today"},
            },
            "required": [],
        },
    )
    async def get_daily_summary(args):
        target_date = _parse_date(args["target_date"]) if args.get("target_date") else None
        summary = await asyncio.to_thread(analytics_service.get_daily_summary, target_date=target_date)
        lines = [
            f"Date: {summary['date']}",
            f"Bills: {summary['bill_count']}",
            f"Total sales: Rs {summary['total_sales']}",
            f"Tax collected: Rs {summary['tax_collected']}",
        ]
        if summary["by_payment_mode"]:
            lines.append("By payment mode: " + ", ".join(
                f"{mode}=Rs {amt}" for mode, amt in summary["by_payment_mode"].items()
            ))
        if summary["top_items"]:
            lines.append("Top items: " + ", ".join(
                f"{name} ({qty})" for name, qty in summary["top_items"]
            ))
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    @tool(
        "render_analysis_deck",
        "Generate a PPTX sales-analysis deck (with real charts) for a date range: sales trend, "
        "top items, GST collected, and stock health.",
        {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            },
            "required": ["start_date", "end_date"],
        },
    )
    async def render_analysis_deck(args):
        start = _parse_date(args["start_date"])
        end = _parse_date(args["end_date"])
        pptx_bytes = await asyncio.to_thread(
            analytics_service.render_analysis_deck, start_date=start, end_date=end,
        )
        artifact_context.set(
            data=pptx_bytes, filename=f"analysis-{start}-to-{end}.pptx", mime_type=PPTX_MIME_TYPE,
        )
        return {"content": [{"type": "text",
                              "text": f"Generated the sales analysis deck for {start} to {end}."}]}

    return [get_daily_summary, render_analysis_deck]
```

- [ ] **Step 4: Run tests to verify they pass, then full suite**

Run: `pytest tests/test_artifact_context.py tests/test_invoicing_tools.py tests/test_analytics_tools.py -v` — expect 6 passed
Run: `pytest -v` — expect 163 passed

- [ ] **Step 5: Commit**

```bash
git add app/tools/artifact_context.py app/tools/invoicing_tools.py app/tools/analytics_tools.py \
        tests/test_artifact_context.py tests/test_invoicing_tools.py tests/test_analytics_tools.py
git commit -m "feat: add ArtifactContext and invoicing/analytics tool wrappers"
```

---

### Task 4: Wire artifacts into `AgentSession`

**Files:**
- Modify: `app/agent_session.py`
- Test: `tests/test_agent_session.py`

**Interfaces:**
- Consumes: `InvoiceService`, `AnalyticsService`, `PreferencesService`; `build_invoicing_tools`, `build_analytics_tools`; `ArtifactContext`, `ArtifactPayload`
- Produces: `SendResult(text: str, artifact: ArtifactPayload | None)` (a new frozen dataclass in `app.agent_session`); `AgentSession.send()` now returns `SendResult` instead of `str`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent_session.py` (near the top, alongside existing imports and the tool-name set):
```python
def test_agent_session_registers_invoicing_and_analytics_tools(tmp_path):
    engine = make_engine(str(tmp_path / "session_artifacts.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    session = AgentSession(chat_id="test-chat", session_factory=session_factory)

    tool_names = {t.name for t in session._all_tools}
    assert {"render_invoice_pdf", "get_daily_summary", "render_analysis_deck"} <= tool_names
```

Also add a stub-based test for the new `SendResult` return type (place near the other `_make_session`/`_install_fake_client`-based tests already in this file, reusing those same helpers):
```python
def test_send_returns_send_result_with_no_artifact_by_default(tmp_path):
    session = _make_session(tmp_path)
    _install_fake_client(session)

    result = asyncio.run(session.send("how much sugar is left?", update_id="u1"))

    assert isinstance(result, SendResult)
    assert result.text == "ok"
    assert result.artifact is None


def test_send_returns_artifact_when_a_tool_populated_it(tmp_path):
    session = _make_session(tmp_path)
    _install_fake_client(session)
    session._artifact_context.set(data=b"%PDF-fake", filename="invoice-1.pdf", mime_type="application/pdf")

    result = asyncio.run(session.send("send me that as a pdf", update_id="u1"))

    assert result.artifact is not None
    assert result.artifact.filename == "invoice-1.pdf"
    # Popped, not left behind for the next turn:
    assert session._artifact_context.pop() is None
```
(These reuse `_make_session`/`_install_fake_client` helpers already present in this test file from Phase 2/3 — if the fake client's stubbed `ResultMessage.result` is `"ok"`, that's what the first test's `result.text == "ok"` assertion checks against; adjust only if the actual helper returns a different stub value, don't change the helper itself.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent_session.py -v`
Expected: FAIL — `AttributeError` (no `_artifact_context`) or `ImportError` (`SendResult` doesn't exist yet)

- [ ] **Step 3: Write minimal implementation**

Modify `app/agent_session.py`:

1. Add imports (alongside the existing ones):
```python
from dataclasses import dataclass

from app.services.analytics import AnalyticsService
from app.services.invoice import InvoiceService
from app.tools.analytics_tools import build_analytics_tools
from app.tools.artifact_context import ArtifactContext, ArtifactPayload
from app.tools.invoicing_tools import build_invoicing_tools
```

2. Add the new dataclass (near `BASE_SYSTEM_PROMPT`):
```python
@dataclass(frozen=True)
class SendResult:
    text: str
    artifact: ArtifactPayload | None = None
```

3. In `AgentSession.__init__`, after constructing `preferences = PreferencesService(session_factory)`, add:
```python
        invoice_service = InvoiceService(session_factory, preferences)
        analytics_service = AnalyticsService(session_factory)
        self._artifact_context = ArtifactContext()
```

4. In the `self._all_tools = (...)` expression, add the two new tool lists:
```python
        self._all_tools = (
            build_inventory_tools(inventory)
            + build_billing_tools(billing, inventory, chat_id, self._update_context)
            + build_khata_tools(khata)
            + build_preferences_tools(preferences)
            + build_invoicing_tools(invoice_service, self._artifact_context)
            + build_analytics_tools(analytics_service, self._artifact_context)
        )
```

5. Change every `return "..."` / `return result_text` in `send()` to return a `SendResult`, and pop the artifact context right before each return. Specifically:
   - The `/new` branch's `return "Started a fresh conversation."` becomes `return SendResult(text="Started a fresh conversation.")` (no artifact possible on this path — nothing ran).
   - The main success path currently does `return result_text` inside the `try` — change to:
     ```python
                     artifact = self._artifact_context.pop()
                     return SendResult(text=result_text, artifact=artifact)
     ```
     (placed as the last two lines inside the `try`, right before the `except BaseException:` clause, replacing the old bare `return result_text`).

- [ ] **Step 4: Run test to verify it passes, then full suite**

Run: `pytest tests/test_agent_session.py -v` — expect 6 passed (4 existing + 2 new; the tool-registration test is a 5th new assertion added to an existing test structure, not a new test function, so the count only grows by the 2 fully-new `SendResult` tests plus whatever the tool-registration addition contributes — run it and confirm no failures rather than pattern-matching an exact number here, since this step touches an existing file with pre-existing tests)
Run: `pytest -v` — expect at least 165 passed (163 from Task 3 + 2 new `SendResult` tests; exact count depends on how the tool-registration check was added)

- [ ] **Step 5: Commit**

```bash
git add app/agent_session.py tests/test_agent_session.py
git commit -m "feat: wire invoicing/analytics tools into AgentSession, return SendResult from send()"
```

---

### Task 5: Deliver artifacts through both channels

**Files:**
- Modify: `app/channels/cli_channel.py`
- Modify: `app/channels/telegram_channel.py`
- Test: `tests/test_cli_channel.py`
- Test: `tests/test_telegram_channel.py`

**Interfaces:**
- Consumes: `SendResult` from `app.agent_session`
- Produces: `CLIChannel.run()` now writes any artifact to `./data/artifacts/<filename>` and prints the saved path; `TelegramChannel._on_message` now sends any artifact as a Telegram document (in addition to the text reply)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli_channel.py` (extending the existing construction test — this task needs a new behavioral test, so add a test double for the session):
```python
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from app.agent_session import SendResult
from app.tools.artifact_context import ArtifactPayload


def test_cli_channel_writes_artifact_to_disk_and_reports_path(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    engine = make_engine(str(tmp_path / "cli_artifact.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    channel = CLIChannel(chat_id="local", session_factory=session_factory)
    channel._session.send = AsyncMock(return_value=SendResult(
        text="Here's your invoice.",
        artifact=ArtifactPayload(data=b"%PDF-fake", filename="invoice-1.pdf", mime_type="application/pdf"),
    ))
    channel._session.close = AsyncMock()

    inputs = iter(["send me the invoice", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    asyncio.run(channel.run())

    saved_path = Path("data/artifacts/invoice-1.pdf")
    assert saved_path.exists()
    assert saved_path.read_bytes() == b"%PDF-fake"
    captured = capsys.readouterr()
    assert "invoice-1.pdf" in captured.out
```
(Add the necessary imports — `make_engine`, `make_session_factory`, `Base` from `app.db`, `CLIChannel` from `app.channels.cli_channel` — alongside whatever this test file already imports; don't duplicate existing imports.)

Add to `tests/test_telegram_channel.py`:
```python
def test_on_message_sends_artifact_as_telegram_document(tmp_path):
    from app.agent_session import SendResult
    from app.tools.artifact_context import ArtifactPayload

    registry = MagicMock()
    session = MagicMock()
    session.send = AsyncMock(return_value=SendResult(
        text="Here's your invoice.",
        artifact=ArtifactPayload(data=b"%PDF-fake", filename="invoice-1.pdf", mime_type="application/pdf"),
    ))
    registry.get_or_create.return_value = session

    channel = _make_channel(registry)
    update, message = _make_update(update_id=5, text="send me the invoice")
    message.reply_document = AsyncMock()

    asyncio.run(channel._on_message(update, MagicMock()))

    message.reply_text.assert_awaited_once_with("Here's your invoice.")
    message.reply_document.assert_awaited_once()
    _, kwargs = message.reply_document.await_args
    assert kwargs["filename"] == "invoice-1.pdf"
```
(This test needs `message.reply_document` to be settable the same way `reply_text` is in the existing tests in this file — reuse whatever mocking mechanism `_make_update`/the existing monkeypatch approach already established for `reply_text`, applying it to `reply_document` too, since `Message` is frozen/slots the same way for both attributes.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_channel.py tests/test_telegram_channel.py -v`
Expected: FAIL — `SendResult`/`ArtifactPayload` not yet returned by the real (unmodified) channels, so the artifact-handling assertions fail (the mocked-`session.send` tests will still call the channel's real code, which doesn't yet know how to handle `SendResult.artifact`)

- [ ] **Step 3: Write minimal implementation**

Modify `app/channels/cli_channel.py`:
```python
import asyncio
import uuid
from pathlib import Path

from app.agent_session import AgentSession

ARTIFACTS_DIR = Path("data/artifacts")


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
                result = await self._session.send(text, update_id=update_id)
                print(f"kirana> {result.text}")
                if result.artifact is not None:
                    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
                    saved_path = ARTIFACTS_DIR / result.artifact.filename
                    saved_path.write_bytes(result.artifact.data)
                    print(f"kirana> (saved to {saved_path})")
        finally:
            await self._session.close()
```

Modify `app/channels/telegram_channel.py`: change the body of `_on_message` from calling `session.send(...)` and using the bare string, to handling a `SendResult`:
```python
    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None or message.text is None:
            return
        chat_id = str(update.effective_chat.id)
        if self._allowed_chat_ids is not None and chat_id not in self._allowed_chat_ids:
            logger.warning("Ignoring message from unrecognized chat_id=%s", chat_id)
            return
        session = self._registry.get_or_create(chat_id)
        try:
            if chat_id and str(update.update_id) and message.text.strip().lower() == "/new":
                popped = self._registry.reset(chat_id)
                if popped is not None:
                    try:
                        await popped.close()
                    except Exception:
                        pass
                session = self._registry.get_or_create(chat_id)
                await self._send_reply(message, "Started a fresh conversation.")
                return
            result = await session.send(message.text, update_id=str(update.update_id))
        except Exception:
            logger.exception(
                "AgentSession.send failed for chat_id=%s update_id=%s", chat_id, update.update_id,
            )
            await self._send_reply(message, "Something went wrong on my end -- please try again in a moment.")
            return
        await self._send_reply(message, result.text or FALLBACK_REPLY)
        if result.artifact is not None:
            await message.reply_document(
                document=io.BytesIO(result.artifact.data),
                filename=result.artifact.filename,
            )
```
Note: the `/new`-interception block above already existed in this file before this task (from Phase 3's Finding 4 fix) — only the final `await session.send(...)` line and everything after it (the artifact-sending block) is new in this task; do not duplicate the `/new` handling if it's already present, just extend the success path to handle `result.artifact`. Add `import io` at the top of the file alongside the existing imports.

- [ ] **Step 4: Run tests to verify they pass, then full suite**

Run: `pytest tests/test_cli_channel.py tests/test_telegram_channel.py -v` — expect all passing (existing + 2 new)
Run: `pytest -v` — expect at least 167 passed

- [ ] **Step 5: Commit**

```bash
git add app/channels/cli_channel.py app/channels/telegram_channel.py \
        tests/test_cli_channel.py tests/test_telegram_channel.py
git commit -m "feat: deliver generated artifacts through CLI (saved to disk) and Telegram (as a document)"
```

---

### Task 6: Invoicing + analytics skill content

**Files:**
- Create: `.claude/skills/invoicing/SKILL.md`
- Create: `.claude/skills/analytics/SKILL.md`
- Modify: `app/agent_session.py` (add the two new skill names to the `skills=[...]` allowlist)
- Test: `tests/test_skills_content.py` (extend)

**Interfaces:**
- Consumes: nothing new
- Produces: 2 more skill files; `AgentSession`'s `skills=[...]` list grows to include them

- [ ] **Step 1: Write the failing test**

Add to `tests/test_skills_content.py`:
```python
def test_invoicing_and_analytics_skill_files_exist_with_frontmatter():
    for name in ("invoicing", "analytics"):
        content = _read(name)
        assert content.startswith("---"), f"{name} SKILL.md missing YAML frontmatter"
        assert "description:" in content.splitlines()[2]


def test_invoicing_skill_mentions_pdf_and_bill_id():
    content = _read("invoicing").lower()
    assert "pdf" in content
    assert "bill" in content


def test_analytics_skill_mentions_deck_and_charts():
    content = _read("analytics").lower()
    assert "pptx" in content or "deck" in content
    assert "chart" in content
```

Also add to `tests/test_agent_session.py` (extending the existing tool-registration assertion or as a new small test):
```python
def test_agent_session_skills_allowlist_includes_invoicing_and_analytics(tmp_path):
    engine = make_engine(str(tmp_path / "session_skills.db"))
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    session = AgentSession(chat_id="test-chat", session_factory=session_factory)

    assert set(session._options.skills) == {
        "inventory", "billing", "khata", "preferences", "invoicing", "analytics",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_skills_content.py tests/test_agent_session.py -v`
Expected: FAIL — `FileNotFoundError` for the two new skill files, and an assertion failure on the skills-allowlist test (still only 4 entries)

- [ ] **Step 3: Write the skill content and update the allowlist**

`.claude/skills/invoicing/SKILL.md`:
```markdown
---
name: invoicing
description: Use whenever the owner asks for a bill/invoice as a document -- "send me that as a PDF", "print the invoice", "invoice for bill 12". Only applies to a bill that has already been finalized.
---

# Invoicing

Use `render_invoice_pdf` to produce a proper GST invoice document. It needs the `bill_id` --
you already have this from when the bill was finalized (e.g. "Bill #12 finalized"), so use that
number directly. If the owner asks for an invoice and you genuinely don't know which bill they
mean (no bill was finalized yet in this conversation, or they're asking about an old one), ask
which bill number rather than guessing -- never invent a bill id.

The generated PDF includes the shop's name, GSTIN, and address from standing preferences (if set)
-- if the owner hasn't set `shop_name`/`gstin`/`shop_address` yet, the invoice still generates with
sensible defaults, but it's worth mentioning once that setting those preferences would make future
invoices more complete.

Once you call this tool, the document is handled automatically by the channel -- you don't need to
do anything else with it. Just confirm briefly that it's been generated.
```

`.claude/skills/analytics/SKILL.md`:
```markdown
---
name: analytics
description: Use whenever the owner asks about sales performance, wants a summary of today's/this week's business, or wants a proper analysis deck -- "today's sales?", "close the day", "make this week's sales analysis deck", "how are we doing".
---

# Analytics

Two different things, don't conflate them:

- **`get_daily_summary`** -- a quick text answer for "today's sales?" / "close the day": total
  sales, tax collected, cash/UPI/card split, and top items for one day (defaults to today if no
  date is given). Use this for a conversational check-in, not a document.
- **`render_analysis_deck`** -- a real PPTX deck with charts (sales trend, top items, GST
  collected, stock health) for a date range. Use this when the owner explicitly wants a
  presentation/deck, not just a quick number -- e.g. "make this week's sales analysis deck". Needs
  a `start_date` and `end_date` (YYYY-MM-DD); for "this week" work out the actual calendar dates
  from context rather than asking the owner to compute them.

Like the invoice PDF, once `render_analysis_deck` is called the file is delivered automatically by
the channel -- just confirm briefly what date range it covers.
```

In `app/agent_session.py`, update the `skills=[...]` list inside `ClaudeAgentOptions`:
```python
            skills=["inventory", "billing", "khata", "preferences", "invoicing", "analytics"],
```

- [ ] **Step 4: Run tests to verify they pass, then full suite**

Run: `pytest tests/test_skills_content.py tests/test_agent_session.py -v` — expect all passing
Run: `pytest -v` — expect at least 170 passed

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/invoicing .claude/skills/analytics app/agent_session.py \
        tests/test_skills_content.py tests/test_agent_session.py
git commit -m "feat: add invoicing/analytics skill content, extend agent skills allowlist"
```

- [ ] **Step 6: Manual live verification (not part of the automated suite — costs real API usage)**

Once committed, from the repo root with the venv active and DB seeded (`python3 -m scripts.seed_dev_data`):
1. Run `python -m app.run_cli`, finalize a bill, then ask "send me that as a PDF" — confirm a real PDF appears in `./data/artifacts/` and open it to check the GST tax breakup renders correctly (subtotal, CGST, SGST, round off, grand total all present and consistent).
2. Ask "make this week's sales analysis deck" (using this week's actual dates) — confirm a `.pptx` appears in `./data/artifacts/` and open it to check the charts are real matplotlib images (not placeholder text) and the numbers match what's in the DB.
Record what happened in the task report.
