import asyncio
from decimal import Decimal

from app.db import Base, make_engine, make_session_factory
from app.services.khata import KhataService
from app.tools.khata_tools import build_khata_tools


def _tools_by_name(tmp_path):
    engine = make_engine(str(tmp_path / "khata_tools.db"))
    Base.metadata.create_all(engine)
    khata = KhataService(make_session_factory(engine))
    return {t.name: t for t in build_khata_tools(khata)}, khata


def test_credit_customer_creates_and_reports(tmp_path):
    tools, khata = _tools_by_name(tmp_path)
    result = asyncio.run(tools["credit_customer"].handler({"customer_name": "Ramesh", "amount": "500"}))
    assert not result.get("is_error")
    assert khata.get_balance(customer_name="Ramesh") == Decimal("500")


def test_credit_customer_is_error_for_malformed_amount(tmp_path):
    tools, khata = _tools_by_name(tmp_path)
    result = asyncio.run(tools["credit_customer"].handler({"customer_name": "Ramesh", "amount": "not-a-number"}))
    assert result.get("is_error") is True


def test_settle_khata_reduces_balance(tmp_path):
    tools, khata = _tools_by_name(tmp_path)
    asyncio.run(tools["credit_customer"].handler({"customer_name": "Ramesh", "amount": "500"}))
    result = asyncio.run(tools["settle_khata"].handler({"customer_name": "Ramesh", "amount": "300"}))
    assert not result.get("is_error")
    assert khata.get_balance(customer_name="Ramesh") == Decimal("200")


def test_settle_khata_is_error_for_unknown_customer(tmp_path):
    tools, khata = _tools_by_name(tmp_path)
    result = asyncio.run(tools["settle_khata"].handler({"customer_name": "Ghost", "amount": "100"}))
    assert result.get("is_error") is True


def test_get_khata_balance_reports_amount(tmp_path):
    tools, khata = _tools_by_name(tmp_path)
    asyncio.run(tools["credit_customer"].handler({"customer_name": "Ramesh", "amount": "500"}))
    result = asyncio.run(tools["get_khata_balance"].handler({"customer_name": "Ramesh"}))
    assert "500" in result["content"][0]["text"]


def test_get_khata_balance_is_error_for_unknown_customer(tmp_path):
    tools, khata = _tools_by_name(tmp_path)
    result = asyncio.run(tools["get_khata_balance"].handler({"customer_name": "Ghost"}))
    assert result.get("is_error") is True
