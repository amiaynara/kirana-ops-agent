from decimal import Decimal

import pytest

from app.db import Base, make_engine, make_session_factory
from app.errors import CustomerNotFoundError
from app.services.khata import KhataService


@pytest.fixture
def khata(tmp_path):
    engine = make_engine(str(tmp_path / "khata.db"))
    Base.metadata.create_all(engine)
    return KhataService(make_session_factory(engine))


def test_credit_customer_creates_customer_on_first_entry(khata):
    khata.credit_customer(customer_name="Ramesh", amount=Decimal("500"))
    assert khata.get_balance(customer_name="Ramesh") == Decimal("500")


def test_credit_then_payment_reduces_balance(khata):
    khata.credit_customer(customer_name="Ramesh", amount=Decimal("500"))
    khata.settle_khata(customer_name="Ramesh", amount=Decimal("300"))
    assert khata.get_balance(customer_name="Ramesh") == Decimal("200")


def test_multiple_credits_accumulate(khata):
    khata.credit_customer(customer_name="Ramesh", amount=Decimal("500"))
    khata.credit_customer(customer_name="Ramesh", amount=Decimal("150"))
    assert khata.get_balance(customer_name="Ramesh") == Decimal("650")


def test_credit_customer_name_lookup_is_case_insensitive(khata):
    khata.credit_customer(customer_name="Ramesh", amount=Decimal("500"))
    khata.credit_customer(customer_name="ramesh", amount=Decimal("100"))
    assert khata.get_balance(customer_name="RAMESH") == Decimal("600")


def test_settle_khata_raises_for_unknown_customer(khata):
    with pytest.raises(CustomerNotFoundError):
        khata.settle_khata(customer_name="Ghost", amount=Decimal("100"))


def test_get_balance_raises_for_unknown_customer(khata):
    with pytest.raises(CustomerNotFoundError):
        khata.get_balance(customer_name="Ghost")


def test_credit_customer_rejects_non_positive_amount(khata):
    with pytest.raises(ValueError):
        khata.credit_customer(customer_name="Ramesh", amount=Decimal("0"))
