from decimal import Decimal

from app.tools.decimal_parsing import parse_decimal


def test_parse_decimal_accepts_plain_number():
    value, error = parse_decimal("2.5", field_name="qty")
    assert value == Decimal("2.5")
    assert error is None


def test_parse_decimal_rejects_garbage():
    value, error = parse_decimal("not-a-number", field_name="qty")
    assert value is None
    assert error["is_error"] is True


def test_parse_decimal_rejects_nan():
    value, error = parse_decimal("NaN", field_name="qty")
    assert value is None
    assert error is not None
    assert error["is_error"] is True


def test_parse_decimal_rejects_infinity():
    value, error = parse_decimal("Infinity", field_name="qty")
    assert value is None
    assert error is not None
    assert error["is_error"] is True


def test_parse_decimal_rejects_negative_infinity():
    value, error = parse_decimal("-Infinity", field_name="qty")
    assert value is None
    assert error is not None
    assert error["is_error"] is True
