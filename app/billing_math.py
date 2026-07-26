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

        rounded_line_subtotal = _round_paisa(line_subtotal)
        rounded_cgst_amt = _round_paisa(cgst_amt)
        rounded_sgst_amt = _round_paisa(sgst_amt)

        line_results.append(BillLineResult(
            product_id=line.product_id,
            product_name=line.product_name,
            qty=line.qty,
            unit_price=line.unit_price,
            gst_slab=line.gst_slab,
            line_subtotal=rounded_line_subtotal,
            cgst_amt=rounded_cgst_amt,
            sgst_amt=rounded_sgst_amt,
            # Same reconciliation rule as the bill-level grand_total below:
            # sum the already-rounded components rather than independently
            # rounding line_subtotal + line_gst, so a line's own total always
            # equals its displayed subtotal + cgst + sgst.
            line_total=rounded_line_subtotal + rounded_cgst_amt + rounded_sgst_amt,
        ))

    subtotal = _round_paisa(raw_subtotal)
    cgst_total = _round_paisa(raw_cgst)
    sgst_total = _round_paisa(raw_sgst)

    return BillTotals(
        lines=line_results,
        subtotal=subtotal,
        cgst_total=cgst_total,
        sgst_total=sgst_total,
        # grand_total must be the sum of the already-rounded components, not an
        # independent rounding of the raw combined sum. Otherwise the persisted
        # tax breakup (subtotal + cgst_total + sgst_total) can be a paisa off
        # from grand_total on sub-paisa amounts.
        grand_total=subtotal + cgst_total + sgst_total,
    )
