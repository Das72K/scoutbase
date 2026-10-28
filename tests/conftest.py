"""Test session setup: every test runs against a throwaway database, never the working one.

POSTGRES_DB is swapped for the test database at import time, before anything connects, so the
tests, Alembic (db/env.py) and pipeline.config all reach scoutbase_test. The session creates
and migrates it, drops it at the end, and fails the run if the working database changed.
"""

import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from psycopg import sql

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
WORKING_DB = os.environ["POSTGRES_DB"]
TEST_DB = os.environ.get("SCOUTBASE_TEST_DB", f"{WORKING_DB}_test")
if TEST_DB == WORKING_DB:
    raise RuntimeError(f"SCOUTBASE_TEST_DB must differ from POSTGRES_DB ({WORKING_DB})")
os.environ["POSTGRES_DB"] = TEST_DB


def _connect(user: str, password: str, dbname: str = TEST_DB, **kwargs) -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5433")),
        dbname=dbname,
        user=user,
        password=password,
        autocommit=True,
        **kwargs,
    )


def _owner_connect(dbname: str, **kwargs) -> psycopg.Connection:
    return _connect(os.environ["POSTGRES_USER"], os.environ["POSTGRES_PASSWORD"], dbname, **kwargs)


def alembic_config() -> Config:
    return Config(str(ROOT / "db" / "alembic.ini"))


def _working_db_snapshot() -> dict[str, object]:
    """Row count of every raw table plus the migration version of the working database."""
    # Read-only session: the check itself cannot change what it is checking.
    with _owner_connect(WORKING_DB, options="-c default_transaction_read_only=on") as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT format('%I.%I', schemaname, tablename) FROM pg_tables "
            "WHERE schemaname = 'raw' ORDER BY 1"
        )]
        snapshot: dict[str, object] = {
            t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables
        }
        if conn.execute("SELECT to_regclass('public.alembic_version')").fetchone()[0]:
            snapshot["alembic_version"] = conn.execute(
                "SELECT version_num FROM public.alembic_version"
            ).fetchone()[0]
    return snapshot


@pytest.fixture(scope="session", autouse=True)
def working_db_untouched() -> Iterator[None]:
    """Fail the session if any raw row count or the migration version of WORKING_DB changed."""
    before = _working_db_snapshot()
    yield
    after = _working_db_snapshot()
    assert after == before, f"tests changed the working database {WORKING_DB}"


@pytest.fixture(scope="session", autouse=True)
def test_database(working_db_untouched) -> Iterator[str]:
    """Create TEST_DB from scratch, migrate it to head, and drop it when the session ends."""
    drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(TEST_DB))
    with _owner_connect("postgres") as admin:
        admin.execute(drop)  # left over from an interrupted session
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DB)))
    command.upgrade(alembic_config(), "head")
    yield TEST_DB
    with _owner_connect("postgres") as admin:
        admin.execute(drop)


@pytest.fixture
def owner() -> Iterator[psycopg.Connection]:
    """The migration owner (POSTGRES_USER): creates app/audit tables like a migration would."""
    with _owner_connect(TEST_DB) as conn:
        yield conn


@pytest.fixture
def login_as() -> Iterator[Callable[[str], psycopg.Connection]]:
    """login_as("scoutbase_app") -> connection as scoutbase_app_user."""
    opened: list[psycopg.Connection] = []

    def connect(group: str) -> psycopg.Connection:
        conn = _connect(f"{group}_user", os.environ[f"{group.upper()}_PASSWORD"])
        opened.append(conn)
        return conn

    yield connect
    for conn in opened:
        conn.close()


@pytest.fixture
def table_name(owner: psycopg.Connection) -> Iterator[Callable[[str], str]]:
    """Unique throwaway table names, dropped after the test."""
    created: list[str] = []

    def make(schema: str) -> str:
        name = f"{schema}.test_{uuid.uuid4().hex[:8]}"
        created.append(name)
        return name

    yield make
    for name in created:
        owner.execute(f"DROP TABLE IF EXISTS {name}")
