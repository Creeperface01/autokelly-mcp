"""Paced, Chrome-impersonating HTTP layer over curl_cffi."""

from __future__ import annotations

import asyncio
import json
import random
import time
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

from curl_cffi.requests import AsyncSession

from autokelly_mcp.errors import BlockedError
from autokelly_mcp.session_store import SessionData

Transport = Callable[..., Awaitable["Response"]]

_ACCEPT_LANGUAGE = "cs-CZ,cs;q=0.9"
_JSON_ACCEPT = "application/json, text/plain, */*"


@dataclass
class Response:
    """Minimal HTTP response. Header keys are always lower-cased."""

    status: int
    headers: dict[str, str] = field(default_factory=dict)
    text: str = ""
    content: bytes = b""
    url: str = ""

    def __post_init__(self) -> None:
        self.headers = {k.lower(): v for k, v in self.headers.items()}


class Fetcher(Protocol):
    """HTTP surface used by every client."""

    async def get(
        self, url: str, *, headers: dict[str, str] | None = None, referer: str | None = None
    ) -> Response: ...

    async def post_json(self, url: str, body: dict | None, *, referer: str | None = None) -> Response: ...

    async def post_form(self, url: str, form: dict, *, referer: str | None = None) -> Response: ...

    async def get_bytes(self, url: str) -> bytes: ...

    def set_session(self, data: SessionData) -> None: ...


class CurlFetcher:
    """curl_cffi fetcher with per-host pacing and the saved session cookies/UA."""

    def __init__(
        self,
        session: SessionData | None = None,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        rng: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._curl = AsyncSession(impersonate="chrome")
        self._session: SessionData | None = None
        self._transport: Transport = transport if transport is not None else self._default_transport
        self._sleep = sleep
        self._clock = clock
        self._rng = rng
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        if session is not None:
            self.set_session(session)

    def set_session(self, data: SessionData) -> None:
        """Load the session cookies into the curl jar and remember the UA."""
        self._session = data
        for cookie in data.cookies:
            name = cookie.get("name")
            if not name:
                continue
            self._curl.cookies.set(
                name,
                cookie.get("value", ""),
                domain=cookie.get("domain", ""),
                path=cookie.get("path", "/"),
            )

    def _headers(self, extra: dict[str, str] | None = None, *, referer: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {"accept-language": _ACCEPT_LANGUAGE}
        if self._session and self._session.user_agent:
            headers["user-agent"] = self._session.user_agent
        if extra:
            headers.update({k.lower(): v for k, v in extra.items()})
        if referer is not None:
            headers["referer"] = referer
        return headers

    async def _request(
        self, method: str, url: str, *, headers: dict[str, str], body: bytes | None
    ) -> Response:
        host = urlsplit(url).hostname or ""
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            last = self._last.get(host)
            now = self._clock()
            if last is not None:
                gap = self._rng(0.3, 0.8)
                wait = gap - (now - last)
                if wait > 0:
                    await self._sleep(wait)
            if body is None:
                resp = await self._transport(method, url, headers=headers)
            else:
                resp = await self._transport(method, url, headers=headers, content=body)
            self._last[host] = self._clock()
            return resp

    async def _default_transport(self, method: str, url: str, **kwargs: Any) -> Response:
        raw = await self._curl.request(method, url, **kwargs)
        headers = {k.lower(): v for k, v in raw.headers.items()}
        return Response(
            status=raw.status_code,
            headers=headers,
            text=raw.text,
            content=bytes(raw.content),
            url=str(raw.url),
        )

    async def get(
        self, url: str, *, headers: dict[str, str] | None = None, referer: str | None = None
    ) -> Response:
        return await self._request("GET", url, headers=self._headers(headers, referer=referer), body=None)

    async def post_json(self, url: str, body: dict | None, *, referer: str | None = None) -> Response:
        extra = {"accept": _JSON_ACCEPT}
        payload: bytes | None = None
        if body is not None:
            extra["content-type"] = "application/json;charset=UTF-8"
            payload = json.dumps(body).encode("utf-8")
        return await self._request("POST", url, headers=self._headers(extra, referer=referer), body=payload)

    async def post_form(self, url: str, form: dict, *, referer: str | None = None) -> Response:
        extra = {
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "x-requested-with": "XMLHttpRequest",
        }
        payload = urllib.parse.urlencode(form).encode("utf-8")
        return await self._request("POST", url, headers=self._headers(extra, referer=referer), body=payload)

    async def get_bytes(self, url: str) -> bytes:
        return (await self.get(url)).content


def classify(resp: Response, expect_json: bool) -> None:
    """Raise BlockedError when the response looks like a block or challenge."""
    if resp.status in (403, 429, 503):
        raise BlockedError(f"Blocked: HTTP {resp.status} for {resp.url}")
    shield = resp.headers.get("shieldsquare-response")
    if shield is not None and shield != "0":
        raise BlockedError(f"Blocked: shieldsquare-response={shield} for {resp.url}")
    if expect_json and (resp.text.strip().startswith("<") or "captcha" in resp.text.lower()):
        raise BlockedError(f"Blocked: non-JSON reply for {resp.url}")


def parse_json(resp: Response) -> object:
    """Classify as JSON, then parse the body."""
    classify(resp, True)
    return json.loads(resp.text)
