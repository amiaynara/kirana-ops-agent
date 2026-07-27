from decimal import Decimal, InvalidOperation


def parse_decimal(value, *, field_name):
    """Parse a decimal string from tool args. Returns (Decimal, None) on success,
    or (None, error_result_dict) on failure — the caller returns error_result_dict
    directly as the tool's result on failure."""
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        parsed = None
    if parsed is None or not parsed.is_finite():
        return None, {
            "content": [{"type": "text",
                         "text": f"{field_name!r} must be a plain number (e.g. '2.5'), got {value!r}."}],
            "is_error": True,
        }
    return parsed, None
