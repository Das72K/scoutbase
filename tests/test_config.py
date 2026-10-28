"""Where provider data is read from and fetched to (pipeline.config.data_dir)."""

import pytest

from pipeline import config


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Only the environment set by each test counts, not a SCOUTBASE_DATA_DIR in .env."""
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)


def test_data_dir_defaults_to_linux_user_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("SCOUTBASE_DATA_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert config.data_dir() == tmp_path / "scoutbase"
    assert config.sources_dir() == tmp_path / "scoutbase" / "sources"


def test_data_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SCOUTBASE_DATA_DIR", str(tmp_path / "elsewhere"))
    assert config.data_dir() == tmp_path / "elsewhere"


def test_relative_data_dir_is_resolved_against_the_repository(monkeypatch):
    monkeypatch.setenv("SCOUTBASE_DATA_DIR", "data")
    assert config.data_dir() == config.FALLBACK_DATA_DIR == config.ROOT / "data"


def test_falls_back_to_repository_data_dir_when_default_is_unusable(monkeypatch, tmp_path):
    monkeypatch.delenv("SCOUTBASE_DATA_DIR", raising=False)
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")  # mkdir below a regular file fails
    monkeypatch.setenv("XDG_DATA_HOME", str(blocker))
    assert config.data_dir() == config.FALLBACK_DATA_DIR
