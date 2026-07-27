from decimal import Decimal

from sqlalchemy import func

from app.errors import AmbiguousCustomerError, CustomerNotFoundError, ValidationError
from app.models import Customer, KhataLedger


class KhataService:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _find_customer(self, session, customer_name):
        """Find a customer by name using exact case-insensitive match.

        Treats % and _ as literal characters, not SQL wildcards.
        """
        matches = session.query(Customer).filter(
            func.lower(Customer.name) == customer_name.lower()
        ).all()
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        raise AmbiguousCustomerError(customer_name, [c.id for c in matches])

    def credit_customer(self, *, customer_name, amount, note=None):
        if amount <= 0:
            raise ValidationError("amount must be positive")
        with self._session_factory() as session:
            with session.begin():
                customer = self._find_customer(session, customer_name)
                if customer is None:
                    customer = Customer(name=customer_name)
                    session.add(customer)
                    session.flush()
                session.add(KhataLedger(
                    customer_id=customer.id, amount=amount, direction="credit", note=note,
                ))

    def settle_khata(self, *, customer_name, amount, note=None):
        if amount <= 0:
            raise ValidationError("amount must be positive")
        with self._session_factory() as session:
            with session.begin():
                customer = self._find_customer(session, customer_name)
                if customer is None:
                    raise CustomerNotFoundError(customer_name)
                session.add(KhataLedger(
                    customer_id=customer.id, amount=amount, direction="payment", note=note,
                ))

    def get_balance(self, *, customer_name):
        with self._session_factory() as session:
            customer = self._find_customer(session, customer_name)
            if customer is None:
                raise CustomerNotFoundError(customer_name)
            entries = session.query(KhataLedger).filter(
                KhataLedger.customer_id == customer.id
            ).all()
            balance = Decimal("0")
            for entry in entries:
                if entry.direction == "credit":
                    balance += entry.amount
                else:
                    balance -= entry.amount
            return balance

    def list_customers(self):
        with self._session_factory() as session:
            customers = session.query(Customer).order_by(Customer.name).all()
            return [(c.id, c.name) for c in customers]
