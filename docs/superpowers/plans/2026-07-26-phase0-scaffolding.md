# Phase 0 — Repo Scaffolding & Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get a runnable Python package with environment-aware config and a working SQLite (WAL) database bootstrap — the foundation every later phase builds on.

**Architecture:** `pyproject.toml`-based package `app/`. `app/config.py` loads env-specific settings via pydantic-settings (`ENV` var → `.env.<env>` file). `app/db.py` creates the SQLAlchemy engine/session factory with WAL mode enabled, and exposes the `Base` declarative class Phase 1's models will attach to.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x, pydantic-settings 2.x, pytest 8.x

## Global Constraints

- Python >= 3.11 (per spec's target runtime)
- SQLite in WAL mode for all environments (spec §5, concurrency)
- `ENV` var selects config; no per-env branching in code beyond config load (spec §10)
- `.env.example` committed; `.env.local`/`.env.stage`/`.env.prod` gitignored (spec §10)
- Default local DB path: `./data/local.db` (spec §10)
- No placeholder/TODO code — every function fully implemented per its task

---

### Task 1: Package scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `tests/__init__.py`
- Create: `.gitignore`
- Create: `.env.example`

**Interfaces:**
- Produces: importable package `app`, `pytest` runnable from repo root

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "kirana-ops-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "sqlalchemy>=2.0,<3.0",
    "pydantic-settings>=2.4,<3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0,<9.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["app*"]
```

- [ ] **Step 2: Create empty package markers**

`app/__init__.py`:
```python
```

`tests/__init__.py`:
```python
```

- [ ] **Step 3: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
venv/
data/
.env.local
.env.stage
.env.prod
*.egg-info/
.pytest_cache/
```

- [ ] **Step 4: Write `.env.example`**

```
ENV=local
ANTHROPIC_API_KEY=
TELEGRAM_BOT_TOKEN=
DB_PATH=./data/local.db
LOG_LEVEL=INFO
```

- [ ] **Step 5: Install and verify**

Run:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -c "import app; print('ok')"
pytest --collect-only
```
Expected: `ok` printed; pytest collects 0 items with no errors (exit code 0 or 5 for "no tests collected" — both acceptable at this step).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml app/__init__.py tests/__init__.py .gitignore .env.example
git commit -m "chore: scaffold package structure"
```

---

### Task 2: Environment-aware settings

**Files:**
- Create: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing (first real module)
- Produces: `Settings` class (fields: `env: str`, `anthropic_api_key: str`, `telegram_bot_token: str`, `db_path: str`, `log_level: str`); `load_settings(env: str | None = None) -> Settings`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
import os
from pathlib import Path

import pytest

from app.config import load_settings


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    content = (
        "ENV=test\n"
        "ANTHROPIC_API_KEY=sk-test-123\n"
        "TELEGRAM_BOT_TOKEN=bot-test-456\n"
        "DB_PATH=./data/test.db\n"
        "LOG_LEVEL=DEBUG\n"
    )
    Path(".env.test").write_text(content)
    return tmp_path


def test_load_settings_reads_env_specific_file(env_file):
    settings = load_settings(env="test")
    assert settings.env == "test"
    assert settings.anthropic_api_key == "sk-test-123"
    assert settings.telegram_bot_token == "bot-test-456"
    assert settings.db_path == "./data/test.db"
    assert settings.log_level == "DEBUG"


def test_load_settings_defaults_env_from_ENV_var(env_file, monkeypatch):
    monkeypatch.setenv("ENV", "test")
    settings = load_settings()
    assert settings.env == "test"


def test_load_settings_falls_back_to_local_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ENV", raising=False)
    settings = load_settings()
    assert settings.env == "local"
    assert settings.db_path == "./data/local.db"
    assert settings.log_level == "INFO"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: Write minimal implementation**

`app/config.py`:
```python
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    env: str = "local"
    anthropic_api_key: str = ""
    telegram_bot_token: str = ""
    db_path: str = "./data/local.db"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


def load_settings(env: str | None = None) -> Settings:
    env_name = env or os.environ.get("ENV", "local")
    env_file = f".env.{env_name}"
    return Settings(_env_file=env_file, env=env_name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add environment-aware settings loader"
```

---

### Task 3: SQLite (WAL) database bootstrap

**Files:**
- Create: `app/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing (models attach to `Base` in Phase 1)
- Produces: `Base` (SQLAlchemy declarative base), `make_engine(db_path: str) -> Engine`, `make_session_factory(engine: Engine) -> sessionmaker`

- [ ] **Step 1: Write the failing test**

`tests/test_db.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 3: Write minimal implementation**

`app/db.py`:
```python
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


def make_engine(db_path: str) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: add SQLite WAL-mode engine and session bootstrap"
```

---

### Task 4: Full test suite sanity pass

**Files:** none created — verification only

- [ ] **Step 1: Run entire suite**

Run: `pytest -v`
Expected: all tests from Task 2 and Task 3 pass (6 passed), 0 failures

- [ ] **Step 2: Verify package installs clean in a fresh venv**

Run:
```bash
deactivate 2>/dev/null; rm -rf .venv-check
python3 -m venv .venv-check && source .venv-check/bin/activate
pip install -e ".[dev]" && pytest -q
deactivate
rm -rf .venv-check
```
Expected: pytest reports all passing, no install errors

No commit for this task — verification only.

---

## Deferred to Phase 1

`scripts/seed_dev_data.py` (real SKU seed data) is **not** part of Phase 0 — it depends on the `Product` model defined in Phase 1. It is the last task of the Phase 1 plan instead.
