"""Shared pytest helpers: fixture loaders and isolated home directory."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from autokelly_mcp.http import Response
from autokelly_mcp.session_store import SessionData

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


@pytest.fixture
def anyio_backend():
    """Run async tests on asyncio."""
    return "asyncio"


def make_response(text: str, status: int = 200, headers: dict | None = None, url: str = "") -> Response:
    """Build a Response test double with lower-cased header keys."""
    return Response(
        status=status, headers=dict(headers or {}), text=text, content=text.encode("utf-8"), url=url
    )


RouteTarget = str | Response | Callable[[str, str, object], Response]


class FakeFetcher:
    """In-memory Fetcher double routed by (method, url regex) pairs."""

    def __init__(self, routes: list[tuple[str, str, RouteTarget]]) -> None:
        self._routes = routes
        self.calls: list[tuple[str, str, object]] = []
        self.session: SessionData | None = None

    def set_session(self, data: SessionData) -> None:
        self.session = data

    async def get(
        self, url: str, *, headers: dict[str, str] | None = None, referer: str | None = None
    ) -> Response:
        return self._route("GET", url, None)

    async def post_json(self, url: str, body: dict | None, *, referer: str | None = None) -> Response:
        return self._route("POST", url, body)

    async def post_form(self, url: str, form: dict, *, referer: str | None = None) -> Response:
        return self._route("POST", url, form)

    async def get_bytes(self, url: str) -> bytes:
        return (await self.get(url)).content

    def _route(self, method: str, url: str, body: object) -> Response:
        self.calls.append((method, url, body))
        for route_method, pattern, target in self._routes:
            if route_method == method and re.search(pattern, url):
                return self._resolve(target, method, url, body)
        raise AssertionError(f"No FakeFetcher route for {method} {url}")

    def _resolve(self, target: RouteTarget, method: str, url: str, body: object) -> Response:
        if isinstance(target, Response):
            return target
        if callable(target):
            return target(method, url, body)
        text = fixture_text(target)
        if target.endswith(".json"):
            headers = {"content-type": "application/json"}
        else:
            headers = {"content-type": "text/html"}
        return Response(status=200, headers=headers, text=text, content=text.encode("utf-8"), url=url)
