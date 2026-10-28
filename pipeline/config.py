"""Paths, source configuration and the pipeline database connection."""

import os
from pathlib import Path
from typing import Any

import psycopg
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SOURCES_DIR = ROOT / "data" / "sources"  # gitignored: provider data is never committed
SOURCES_FILE = ROOT / "config" / "sources.yaml"


def load_sources() -> dict[str, Any]:
    return yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8"))


def connect_pipeline() -> psycopg.Connection:
    """Connect as scoutbase_pipeline_user, which runs as the scoutbase_pipeline role (0003)."""
    load_dotenv(ROOT / ".env")  # real environment variables (e.g. in CI) take precedence
    return psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5433")),
        dbname=os.environ["POSTGRES_DB"],
        user="scoutbase_pipeline_user",
        password=os.environ["SCOUTBASE_PIPELINE_PASSWORD"],
        # Transactions are opened explicitly, one per file (see pipeline.ingest).
        autocommit=True,
    )
