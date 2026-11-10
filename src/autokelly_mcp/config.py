"""Paths, base URLs and constants."""

import os
from pathlib import Path

BASE_URL = "https://www.autokelly.cz"
VINSEARCH_URL = "https://vinsearch.autokelly.cz"


def home_dir() -> Path:
    """Return the config home, overridable via AUTOKELLY_MCP_HOME (used by tests)."""
    override = os.environ.get("AUTOKELLY_MCP_HOME")
    if override:
        return Path(override)
    return Path.home() / ".autokelly-mcp"


def session_path() -> Path:
    """Path of the session file holding cookies, UA and cached search guid."""
    return home_dir() / "session.json"
