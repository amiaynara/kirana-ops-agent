import io
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.errors import BillNotFoundError
from app.models import Bill, BillItem, Product
from app.timezone_utils import to_shop_datetime


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
            doc = SimpleDocTemplate(
                buffer, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
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
                f"Date: {to_shop_datetime(bill.created_at).strftime('%d-%b-%Y %H:%M')}", styles["Normal"],
            ))
            elements.append(Paragraph(f"Payment mode: {bill.payment_mode.upper()}", styles["Normal"]))
            if bill.payment_ref:
                elements.append(Paragraph(f"Payment ref: {bill.payment_ref}", styles["Normal"]))
            elements.append(Spacer(1, 12))

            # The line-item totals column and the Subtotal/CGST/SGST/Grand
            # Total column reconcile two ENTIRELY DIFFERENT pairs of numbers
            # (see app/billing_math.py):
            #   - sum(line_total) vs grand_total: each line_total is rounded
            #     independently per line, so on a multi-line bill with
            #     sub-paisa amounts this sum can differ from grand_total by a
            #     paisa. That delta is the "rounding adjustment" below.
            #   - Subtotal + CGST + SGST: these three are computed so they
            #     always sum to grand_total *exactly* -- no rounding gap ever
            #     exists between them, so no round-off row belongs in that
            #     block.
            # Mixing the two into a single totals table made that table's
            # running sum arithmetically wrong (verified live). Keep them in
            # two clearly separate, each internally-correct blocks instead.
            sum_line_totals = sum((bi.line_total for bi, _ in rows), Decimal("0"))
            round_off = bill.grand_total - sum_line_totals

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
            table_data.append(["", "", "", "", "", "", "Line items total", f"{sum_line_totals:.2f}"])

            table = Table(table_data, repeatRows=1)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f3b52")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -2), 0.5, colors.grey),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 4))

            rounding_data = [["Rounding adjustment", f"{round_off:.2f}"]]
            rounding_table = Table(rounding_data, colWidths=[110 * 0.7 * mm, 90 * 0.7 * mm])
            rounding_table.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ]))
            elements.append(rounding_table)
            elements.append(Spacer(1, 12))

            # Subtotal + CGST + SGST already equals Grand Total exactly (see
            # note above) -- no round-off row belongs in this block.
            totals_data = [
                ["Subtotal", f"{bill.subtotal:.2f}"],
                ["CGST", f"{bill.cgst_total:.2f}"],
                ["SGST", f"{bill.sgst_total:.2f}"],
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
