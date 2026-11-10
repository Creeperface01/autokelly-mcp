"""Session store round-trip, permissions and guid update."""

import os
import stat

from autokelly_mcp.config import session_path
from autokelly_mcp.session_store import SessionData, load_session, save_session, update_search_guid


def _sample() -> SessionData:
    return SessionData(
        cookies=[
            {
                "name": "ASP.NET_SessionId",
                "value": "abc123",
                "domain": "www.autokelly.cz",
                "path": "/",
                "expires": -1,
                "httpOnly": True,
                "secure": False,
            }
        ],
        user_agent="Mozilla/5.0 Chrome/157",
        search_guid="guid-1",
        saved_at="2026-11-10T00:00:00+00:00",
    )


def test_session_roundtrip_and_permissions():
    data = _sample()
    save_session(data)
    loaded = load_session()
    assert loaded == data
    mode = stat.S_IMODE(os.stat(session_path()).st_mode)
    assert mode == 0o600


def test_update_search_guid_persists():
    save_session(_sample())
    update_search_guid("new-guid")
    loaded = load_session()
    assert loaded is not None
    assert loaded.search_guid == "new-guid"
    # Other fields survive the update.
    assert loaded.cookies == _sample().cookies
    assert loaded.user_agent == _sample().user_agent


def test_load_missing_returns_none():
    assert load_session() is None
