"""Thin HTTP client for the Laximo catalog server (vinsearch.autokelly.cz)."""

from __future__ import annotations

from autokelly_mcp.config import BASE_URL, VINSEARCH_URL
from autokelly_mcp.http import Fetcher, classify
from autokelly_mcp.models import VehicleMatch
from autokelly_mcp.parsers.laximo import parse_entry

_HOME_REFERER = BASE_URL + "/"
_VINSEARCH_REFERER = VINSEARCH_URL + "/"


class LaximoClient:
    """The only code that talks to vinsearch.autokelly.cz. Never touches /Cart/."""

    def __init__(self, fetcher: Fetcher) -> None:
        self._fetcher = fetcher

    async def entry(self, iframe_url: str) -> list[VehicleMatch]:
        """GET the iframe URL and parse the vehicle matches."""
        resp = await self._fetcher.get(iframe_url, referer=_HOME_REFERER)
        classify(resp, expect_json=False)
        return parse_entry(resp.text)

    async def page(self, path: str) -> str:
        """GET ``VINSEARCH_URL + path`` and return its HTML."""
        resp = await self._fetcher.get(VINSEARCH_URL + path, referer=_VINSEARCH_REFERER)
        classify(resp, expect_json=False)
        return resp.text

    async def group_parts(self, session: str, token: str) -> str:
        """POST a group leaf token and return the group part-list HTML."""
        resp = await self._fetcher.post_form(
            VINSEARCH_URL + f"/cs/catalog/group-part-list?session={session}",
            {"token": token},
            referer=_VINSEARCH_REFERER,
        )
        classify(resp, expect_json=False)
        return resp.text

    async def category_units(self, session: str, token: str) -> str:
        """POST a category token and return the category unit-list HTML."""
        resp = await self._fetcher.post_form(
            VINSEARCH_URL + f"/cs/catalog/category-unit-list?session={session}",
            {"token": token},
            referer=_VINSEARCH_REFERER,
        )
        classify(resp, expect_json=False)
        return resp.text

    async def image(self, url: str) -> bytes:
        """Download raw image bytes (diagram thumbnails need no referer)."""
        return await self._fetcher.get_bytes(url)
