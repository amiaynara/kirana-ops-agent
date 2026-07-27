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
