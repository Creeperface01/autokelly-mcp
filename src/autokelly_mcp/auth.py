"""Session check with at most one login before retrying."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import TypeVar

from autokelly_mcp.config import BASE_URL
from autokelly_mcp.errors import NotLoggedInError
from autokelly_mcp.http import Fetcher, parse_json
from autokelly_mcp.login import browser_login
from autokelly_mcp.models import Credits
from autokelly_mcp.parsers.autokelly import parse_credits
from autokelly_mcp.session_store import SessionData, load_session, save_session

T = TypeVar("T")

_CREDIT_URL = BASE_URL + "/vin-decoder/credit"
_HOME_REFERER = BASE_URL + "/"


class Auth:
    """Check the session and run the login at most once before retrying.

    The lock serialises concurrent callers so two tool calls never open two
    login windows; a call that waited on the lock re-checks the session
    inside the lock before logging in again.
    """

    def __init__(
        self, fetcher: Fetcher, login: Callable[[], Awaitable[SessionData]] = browser_login
    ) -> None:
        self._fetcher = fetcher
        self._login = login
        self._lock = asyncio.Lock()

    async def _credits(self) -> Credits | None:
        resp = await self._fetcher.post_json(_CREDIT_URL, None, referer=_HOME_REFERER)
        data = parse_json(resp)
        return parse_credits(data if isinstance(data, dict) else {})

    async def _do_login(self) -> SessionData:
        old = load_session()
        data = await self._login()
        if old is not None and old.search_guid and not data.search_guid:
            data = replace(data, search_guid=old.search_guid)
        save_session(data)
        self._fetcher.set_session(data)
        return data

    async def ensure_session(self) -> Credits:
        """Return usable credits, logging in at most once when the session is stale."""
        async with self._lock:
            if load_session() is not None:
                credits = await self._credits()
                if credits is not None:
                    return credits
            await self._do_login()
            credits = await self._credits()
            if credits is None:
                raise NotLoggedInError("Not logged in: the login did not produce a usable session.")
            return credits

    async def force_login(self) -> Credits:
        """Run the login unconditionally, then return the credit check."""
        async with self._lock:
            await self._do_login()
            credits = await self._credits()
            if credits is None:
                raise NotLoggedInError("Not logged in: the login did not produce a usable session.")
            return credits

    async def with_relogin(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Run fn; on NotLoggedInError log in once (via ensure_session) and retry fn once."""
        try:
            return await fn()
        except NotLoggedInError:
            await self.ensure_session()
            return await fn()
