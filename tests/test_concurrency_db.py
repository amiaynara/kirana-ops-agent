import threading
import time

from sqlalchemy import Column, Integer
from sqlalchemy.orm import DeclarativeBase

from app.db import make_engine, make_session_factory


class _CounterBase(DeclarativeBase):
    pass


class _Counter(_CounterBase):
    __tablename__ = "concurrency_test_counter"
    id = Column(Integer, primary_key=True)
    value = Column(Integer, nullable=False)


def test_begin_immediate_prevents_lost_update_on_concurrent_read_then_write(tmp_path):
    engine = make_engine(str(tmp_path / "concurrency.db"))
    _CounterBase.metadata.create_all(engine)
    Session = make_session_factory(engine)

    with Session() as session:
        with session.begin():
            session.add(_Counter(id=1, value=0))

    errors = []
    started = threading.Event()

    def increment():
        try:
            with Session() as session:
                with session.begin():
                    started.set()
                    counter = session.get(_Counter, 1)
                    time.sleep(0.1)
                    counter.value += 1
        except Exception as exc:  # noqa: BLE001 - capturing the failure mode under test
            errors.append(exc)

    t1 = threading.Thread(target=increment)
    t1.start()
    assert started.wait(timeout=5), "t1 never entered its transaction"
    t2 = threading.Thread(target=increment)
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"concurrent writers raised: {errors}"
    with Session() as session:
        assert session.get(_Counter, 1).value == 2
