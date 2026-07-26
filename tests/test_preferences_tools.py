import asyncio

from app.db import Base, make_engine, make_session_factory
from app.services.preferences import PreferencesService
from app.tools.preferences_tools import build_preferences_tools


def _tools_by_name(tmp_path):
    engine = make_engine(str(tmp_path / "prefs_tools.db"))
    Base.metadata.create_all(engine)
    preferences = PreferencesService(make_session_factory(engine))
    return {t.name: t for t in build_preferences_tools(preferences)}, preferences


def test_set_preference_persists(tmp_path):
    tools, preferences = _tools_by_name(tmp_path)
    result = asyncio.run(tools["set_preference"].handler({"key": "default_payment_mode", "value": "upi"}))
    assert not result.get("is_error")
    assert preferences.get_preference(key="default_payment_mode") == "upi"


def test_get_preference_reports_value(tmp_path):
    tools, preferences = _tools_by_name(tmp_path)
    preferences.set_preference(key="shop_name", value="Sharma Kirana Store")
    result = asyncio.run(tools["get_preference"].handler({"key": "shop_name"}))
    assert "Sharma Kirana Store" in result["content"][0]["text"]


def test_get_preference_reports_unset(tmp_path):
    tools, preferences = _tools_by_name(tmp_path)
    result = asyncio.run(tools["get_preference"].handler({"key": "nonexistent_key"}))
    assert "No preference set" in result["content"][0]["text"]
