"""Shared pytest helpers: fixture loaders and isolated home directory."""

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def fixture_text(rel: str) -> str:
    """Read a text fixture relative to tests/fixtures/."""
    return (FIXTURES_DIR / rel).read_text(encoding="utf-8")


def fixture_json(rel: str) -> object:
    """Read and parse a JSON fixture relative to tests/fixtures/."""
    return json.loads(fixture_text(rel))


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Point AUTOKELLY_MCP_HOME at a fresh tmp dir for every test."""
    monkeypatch.setenv("AUTOKELLY_MCP_HOME", str(tmp_path))
    yield
