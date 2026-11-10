"""Persistence of the login session (cookies, User-Agent, cached search guid)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, replace

from autokelly_mcp.config import home_dir, session_path


@dataclass
class SessionData:
    """Login session: Playwright-shaped cookies, the UA captured at login, cached guid."""

    cookies: list[dict] = field(default_factory=list)
    user_agent: str = ""
    search_guid: str | None = None
    saved_at: str = ""


def load_session() -> SessionData | None:
    """Load the session file; return None when it does not exist."""
    path = session_path()
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return SessionData(
        cookies=list(payload.get("cookies", [])),
        user_agent=str(payload.get("user_agent", "")),
        search_guid=payload.get("search_guid"),
        saved_at=str(payload.get("saved_at", "")),
    )


def save_session(data: SessionData) -> None:
    """Write the session file atomically with mode 0600 (dir mode 0700)."""
    home = home_dir()
    home.mkdir(parents=True, exist_ok=True)
    os.chmod(home, 0o700)
    payload = {
        "cookies": data.cookies,
        "user_agent": data.user_agent,
        "search_guid": data.search_guid,
        "saved_at": data.saved_at,
    }
    fd, tmp_name = tempfile.mkstemp(dir=str(home), prefix="session-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, session_path())
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def update_search_guid(guid: str) -> None:
    """Cache a new search guid, keeping the rest of the session intact."""
    data = load_session()
    if data is None:
        data = SessionData()
    save_session(replace(data, search_guid=guid))
