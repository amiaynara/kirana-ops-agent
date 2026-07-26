from app.models import OwnerPreference


class PreferencesService:
    def __init__(self, session_factory):
        self._session_factory = session_factory

    def get_preference(self, *, key, default=None):
        with self._session_factory() as session:
            pref = session.get(OwnerPreference, key)
            return pref.value if pref is not None else default

    def set_preference(self, *, key, value):
        with self._session_factory() as session:
            with session.begin():
                pref = session.get(OwnerPreference, key)
                if pref is None:
                    session.add(OwnerPreference(key=key, value=value))
                else:
                    pref.value = value

    def get_all_preferences(self):
        with self._session_factory() as session:
            prefs = session.query(OwnerPreference).order_by(OwnerPreference.key).all()
            return {p.key: p.value for p in prefs}
