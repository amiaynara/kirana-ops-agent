from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SHOP_TIMEZONE = ZoneInfo("Asia/Kolkata")


def to_shop_datetime(created_at_utc_naive: datetime) -> datetime:
    """Convert a naive-but-UTC-valued datetime (as stored in this app's DB) to
    an aware datetime in the shop's local timezone (IST)."""
    return created_at_utc_naive.replace(tzinfo=timezone.utc).astimezone(SHOP_TIMEZONE)


def to_shop_date(created_at_utc_naive: datetime):
    return to_shop_datetime(created_at_utc_naive).date()
