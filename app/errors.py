class DomainError(Exception):
    """Base class for typed service-layer refusals the agent must relay verbatim."""


class ProductNotFoundError(DomainError):
    def __init__(self, identifier):
        self.identifier = identifier
        super().__init__(f"No product found for {identifier!r}")


class CustomerNotFoundError(DomainError):
    def __init__(self, identifier):
        self.identifier = identifier
        super().__init__(f"No customer found for {identifier!r}")


class BelowCostError(DomainError):
    def __init__(self, sell_price, cost_price):
        self.sell_price = sell_price
        self.cost_price = cost_price
        super().__init__(f"Sell price {sell_price} is below cost price {cost_price}")


class InsufficientStockError(DomainError):
    def __init__(self, product_name, requested, available):
        self.product_name = product_name
        self.requested = requested
        self.available = available
        super().__init__(f"Only {available} of {product_name} in stock, {requested} requested")


class NoDraftBillError(DomainError):
    def __init__(self, chat_id):
        self.chat_id = chat_id
        super().__init__(f"No draft bill in progress for chat {chat_id}")


class LineNotFoundError(DomainError):
    def __init__(self, product_id):
        self.product_id = product_id
        super().__init__(f"No line for product {product_id} in the draft bill")


class MissingPaymentModeError(DomainError):
    def __init__(self, chat_id):
        self.chat_id = chat_id
        super().__init__(f"No payment mode set for chat {chat_id} — say cash, UPI, or card")
