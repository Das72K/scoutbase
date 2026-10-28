import os
import uuid
from collections.abc import Callable, Iterator

import psycopg
import pytest
from dotenv import load_dotenv

load_dotenv()


def _connect(user: str, password: str) -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5433")),
        dbname=os.environ["POSTGRES_DB"],
        user=user,
        password=password,
        autocommit=True,
    )


@pytest.fixture
def owner() -> Iterator[psycopg.Connection]:
    """The migration owner (POSTGRES_USER): creates app/audit tables like a migration would."""
    with _connect(os.environ["POSTGRES_USER"], os.environ["POSTGRES_PASSWORD"]) as conn:
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
