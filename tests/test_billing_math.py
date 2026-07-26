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


def test_grand_total_reconciles_with_rounded_breakup_on_sub_paisa_amounts():
    # 4.10 * 5% = 0.205 GST, split into cgst=sgst=0.1025 each - a genuine
    # sub-paisa amount. grand_total must equal the sum of the *rounded*
    # subtotal/cgst_total/sgst_total, not an independent rounding of the raw
    # combined sum (4.10 + 0.1025 + 0.1025 = 4.305, which would round up to
    # 4.31 and no longer reconcile with the rounded breakup of 4.30).
    lines = [
        BillLineInput(product_id=5, product_name="Parle-G 100g", qty=Decimal("1"),
                       unit_price=Decimal("4.10"), gst_slab=5),
    ]
    result = compute_bill_totals(lines)
    assert result.subtotal == Decimal("4.10")
    assert result.cgst_total == Decimal("0.10")
    assert result.sgst_total == Decimal("0.10")
    assert result.grand_total == result.subtotal + result.cgst_total + result.sgst_total == Decimal("4.30")
