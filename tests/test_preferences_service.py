from app.db import Base, make_engine, make_session_factory
from app.services.preferences import PreferencesService


def _make_service(tmp_path):
    engine = make_engine(str(tmp_path / "prefs.db"))
    Base.metadata.create_all(engine)
    return PreferencesService(make_session_factory(engine))


def test_get_preference_returns_default_when_unset(tmp_path):
    prefs = _make_service(tmp_path)
    assert prefs.get_preference(key="default_payment_mode") is None
    assert prefs.get_preference(key="default_payment_mode", default="cash") == "cash"


def test_set_then_get_preference(tmp_path):
    prefs = _make_service(tmp_path)
    prefs.set_preference(key="default_payment_mode", value="upi")
    assert prefs.get_preference(key="default_payment_mode") == "upi"


def test_set_preference_updates_existing(tmp_path):
    prefs = _make_service(tmp_path)
    prefs.set_preference(key="shop_name", value="Sharma Kirana Store")
    prefs.set_preference(key="shop_name", value="Sharma General Store")
    assert prefs.get_preference(key="shop_name") == "Sharma General Store"


def test_get_all_preferences_returns_all_as_dict(tmp_path):
    prefs = _make_service(tmp_path)
    prefs.set_preference(key="default_payment_mode", value="upi")
    prefs.set_preference(key="shop_name", value="Sharma Kirana Store")
    assert prefs.get_all_preferences() == {
        "default_payment_mode": "upi",
        "shop_name": "Sharma Kirana Store",
    }
