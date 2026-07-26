from sqlalchemy import Column, Integer, String, inspect, text
from sqlalchemy.orm import DeclarativeBase

from app.config import Settings
from app.db import Base, init_db, make_engine, make_session_factory


class _TestBase(DeclarativeBase):
    pass


class _Widget(_TestBase):
    __tablename__ = "test_widgets"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


def test_make_engine_enables_wal_mode(tmp_path):
    db_path = tmp_path / "test.db"
    engine = make_engine(str(db_path))
    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert mode.lower() == "wal"


def test_make_engine_enables_foreign_keys(tmp_path):
    db_path = tmp_path / "test.db"
    engine = make_engine(str(db_path))
    with engine.connect() as conn:
        fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
    assert fk == 1


def test_make_engine_enables_busy_timeout(tmp_path):
    db_path = tmp_path / "test.db"
    engine = make_engine(str(db_path))
    with engine.connect() as conn:
        timeout = conn.execute(text("PRAGMA busy_timeout")).scalar()
    assert timeout == 5000


def test_create_all_and_session_roundtrip(tmp_path):
    db_path = tmp_path / "test.db"
    engine = make_engine(str(db_path))
    _TestBase.metadata.create_all(engine)

    assert "test_widgets" in inspect(engine).get_table_names()

    Session = make_session_factory(engine)
    with Session() as session:
        session.add(_Widget(name="sugar"))
        session.commit()

    with Session() as session:
        widget = session.query(_Widget).filter_by(name="sugar").one()
        assert widget.name == "sugar"


def test_make_engine_creates_missing_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "sub" / "test.db"
    assert not db_path.parent.exists()

    engine = make_engine(str(db_path))

    assert db_path.parent.exists()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1


def test_init_db_creates_engine_and_tables(tmp_path):
    db_path = tmp_path / "init_db_test.db"
    settings = Settings(db_path=str(db_path))

    engine = init_db(settings)

    assert db_path.exists()
    table_names = inspect(engine).get_table_names()
    for table in Base.metadata.tables:
        assert table in table_names
