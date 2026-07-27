import io
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.util import Inches  # noqa: E402

from app.models import Bill, BillItem, Product  # noqa: E402

SHOP_TIMEZONE = ZoneInfo("Asia/Kolkata")


def _to_shop_date(created_at_utc_naive: datetime) -> date:
    """Convert a naive-but-UTC-valued timestamp (as stored on Bill.created_at) to the shop's local (IST) calendar date."""
    return created_at_utc_naive.replace(tzinfo=timezone.utc).astimezone(SHOP_TIMEZONE).date()


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
        target_date = target_date or datetime.now(SHOP_TIMEZONE).date()
        with self._session_factory() as session:
            bills = session.query(Bill).filter(Bill.status == "finalized").all()
            day_bills = [b for b in bills if _to_shop_date(b.created_at) == target_date]

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
        if start_date > end_date:
            raise ValueError(f"start_date ({start_date}) must not be after end_date ({end_date})")
        with self._session_factory() as session:
            bills = session.query(Bill).filter(Bill.status == "finalized").all()
            in_range = [b for b in bills if start_date <= _to_shop_date(b.created_at) <= end_date]

            daily_totals: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
            daily_gst: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
            for b in in_range:
                d = _to_shop_date(b.created_at)
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
