"""Shop interface for OEM searches (Autokelly first, other shops later)."""

from __future__ import annotations

from typing import Protocol

from autokelly_mcp.autokelly import AutokellyClient
from autokelly_mcp.models import Offer


class OemSource(Protocol):
    """A shop that can be searched by OEM number."""

    name: str

    async def search(self, oem: str) -> list[Offer]:
        """Return the shop's offers for an OEM number."""
        ...


class AutokellySource:
    """OemSource backed by the Autokelly catalog client."""

    name = "autokelly"

    def __init__(self, client: AutokellyClient) -> None:
        self._client = client

    async def search(self, oem: str) -> list[Offer]:
        """Return Autokelly's offers for an OEM number."""
        return await self._client.oem_search(oem)
