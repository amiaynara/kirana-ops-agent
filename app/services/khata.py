from decimal import Decimal

from app.errors import CustomerNotFoundError
from app.models import Customer, KhataLedger


class KhataService:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def credit_customer(self, *, customer_name, amount, note=None):
        if amount <= 0:
            raise ValueError("amount must be positive")
        with self._session_factory() as session:
            with session.begin():
                customer = session.query(Customer).filter(
                    Customer.name.ilike(customer_name)
                ).one_or_none()
                if customer is None:
                    customer = Customer(name=customer_name)
                    session.add(customer)
                    session.flush()
                session.add(KhataLedger(
                    customer_id=customer.id, amount=amount, direction="credit", note=note,
                ))

    def settle_khata(self, *, customer_name, amount, note=None):
        if amount <= 0:
            raise ValueError("amount must be positive")
        with self._session_factory() as session:
            with session.begin():
                customer = session.query(Customer).filter(
                    Customer.name.ilike(customer_name)
                ).one_or_none()
                if customer is None:
                    raise CustomerNotFoundError(customer_name)
                session.add(KhataLedger(
                    customer_id=customer.id, amount=amount, direction="payment", note=note,
                ))

    def get_balance(self, *, customer_name):
        with self._session_factory() as session:
            customer = session.query(Customer).filter(
                Customer.name.ilike(customer_name)
            ).one_or_none()
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
