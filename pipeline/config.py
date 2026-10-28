"""Paths, source configuration and the pipeline database connection."""

import os
from pathlib import Path
from typing import Any

import psycopg
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SOURCES_FILE = ROOT / "config" / "sources.yaml"
FALLBACK_DATA_DIR = ROOT / "data"  # gitignored: provider data is never committed


def data_dir() -> Path:
    """Where provider data lives: SCOUTBASE_DATA_DIR, else ~/.local/share/scoutbase.

    WHY not the repository's data/ by default: under WSL the repository usually sits on a
    Windows drive (/mnt/<drive>, a 9p share) where reading hundreds of MB is several times
    slower than on the Linux filesystem. A relative SCOUTBASE_DATA_DIR (e.g. `data`) is
    resolved against the repository, and data/ is also the fallback when the default
    location cannot be created.
    """
    load_dotenv(ROOT / ".env")  # real environment variables take precedence
    configured = os.environ.get("SCOUTBASE_DATA_DIR")
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else ROOT / path
    try:
        xdg = os.environ.get("XDG_DATA_HOME")
        default = (Path(xdg) if xdg else Path.home() / ".local" / "share") / "scoutbase"
        default.mkdir(parents=True, exist_ok=True)
        return default
    except (OSError, RuntimeError):  # no home directory, or not writable
        return FALLBACK_DATA_DIR


def sources_dir() -> Path:
    """One checkout per provider below it, e.g. <data dir>/sources/statsbomb."""
    return data_dir() / "sources"


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
