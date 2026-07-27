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
        # Fetched before opening the bill session below: PreferencesService
        # opens its own session on the same engine, and every session here
        # begins its sqlite transaction with BEGIN IMMEDIATE (see app/db.py),
        # which takes a write lock. Calling it while the bill session's
        # transaction is still open would have two transactions contending
        # for that lock on the same engine and dead-lock into "database is
        # locked" once the busy_timeout elapses.
        shop_name = self._preferences.get_preference(key="shop_name", default="Kirana Store")
        gstin = self._preferences.get_preference(key="gstin", default="—")
        shop_address = self._preferences.get_preference(key="shop_address", default="")

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

            buffer = io.BytesIO()
            # pageCompression=0: keep content streams uncompressed. Nothing in
            # this module reads the PDF back in, but callers (and these
            # tests) grep the raw bytes for text like the shop name, which
            # only works if the stream isn't Flate-compressed.
            doc = SimpleDocTemplate(
                buffer, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
                pageCompression=0,
            )
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
