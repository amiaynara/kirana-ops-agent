from sqlalchemy import Column, Integer, String, inspect, text

from app.db import Base, make_engine, make_session_factory


class _Widget(Base):
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


def test_create_all_and_session_roundtrip(tmp_path):
    db_path = tmp_path / "test.db"
    engine = make_engine(str(db_path))
    Base.metadata.create_all(engine)

    assert "test_widgets" in inspect(engine).get_table_names()

    Session = make_session_factory(engine)
    with Session() as session:
        session.add(_Widget(name="sugar"))
        session.commit()

    with Session() as session:
        widget = session.query(_Widget).filter_by(name="sugar").one()
        assert widget.name == "sugar"
