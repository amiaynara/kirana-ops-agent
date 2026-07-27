from decimal import Decimal

import pytest

from app.db import Base, make_engine, make_session_factory
from app.errors import AmbiguousCustomerError, CustomerNotFoundError, ValidationError
from app.models import Customer, KhataLedger
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
    with pytest.raises(ValidationError):
        khata.credit_customer(customer_name="Ramesh", amount=Decimal("0"))


def test_settle_khata_rejects_non_positive_amount(khata):
    khata.credit_customer(customer_name="Ramesh", amount=Decimal("500"))
    with pytest.raises(ValidationError):
        khata.settle_khata(customer_name="Ramesh", amount=Decimal("0"))


def test_credit_customer_treats_underscore_and_percent_as_literal_characters(khata):
    # Test underscore as literal character, not SQL wildcard
    khata.credit_customer(customer_name="Ram_sh", amount=Decimal("111"))
    khata.credit_customer(customer_name="Ramesh", amount=Decimal("222"))

    # Verify underscore name returns correct balance, not both
    assert khata.get_balance(customer_name="Ram_sh") == Decimal("111")
    assert khata.get_balance(customer_name="Ramesh") == Decimal("222")

    # Test percent as literal character, not SQL wildcard
    khata.credit_customer(customer_name="100%Store", amount=Decimal("333"))
    khata.credit_customer(customer_name="100XStore", amount=Decimal("444"))

    # Verify percent name returns correct balance, not both
    assert khata.get_balance(customer_name="100%Store") == Decimal("333")
    assert khata.get_balance(customer_name="100XStore") == Decimal("444")


def test_credit_customer_note_is_recorded(khata):
    khata.credit_customer(customer_name="Ramesh", amount=Decimal("500"), note="opening balance")
    session = khata._session_factory()
    entry = session.query(KhataLedger).one()
    assert entry.note == "opening balance"
    session.close()


def test_find_customer_raises_when_multiple_customers_share_a_name_case_insensitively(khata):
    # credit_customer auto-creates on first entry -- case-variant names collide
    # on the case-insensitive lookup but are still two distinct rows.
    khata.credit_customer(customer_name="Ramesh", amount=Decimal("1"))
    session = khata._session_factory()
    with session.begin():
        session.add(Customer(name="ramesh"))
    session.close()

    with pytest.raises(AmbiguousCustomerError):
        khata.get_balance(customer_name="RAMESH")


def test_list_customers_returns_names(khata):
    khata.credit_customer(customer_name="Ramesh", amount=Decimal("1"))
    khata.credit_customer(customer_name="Suresh", amount=Decimal("1"))
    names = {name for _, name in khata.list_customers()}
    assert names == {"Ramesh", "Suresh"}


def test_list_customers_empty(khata):
    assert khata.list_customers() == []
