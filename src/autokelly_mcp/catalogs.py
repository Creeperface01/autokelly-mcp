"""Open Laximo catalogs and navigate them with short stable ids."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from autokelly_mcp.errors import CatalogExpiredError, UnsupportedCarError
from autokelly_mcp.laximo import LaximoClient
from autokelly_mcp.models import GroupUnit, TreeNode, UnitDetail, UnitRef, VehicleMatch
from autokelly_mcp.parsers.laximo import (
    parse_category_units,
    parse_group_parts,
    parse_jstree,
    parse_unit,
    session_param,
)
from autokelly_mcp.tree_search import normalize, search_tree

_UNKNOWN_CATALOG_MESSAGE = "call open_garage_car again"
_CREDIT_EXPIRED_MESSAGE = (
    "catalog session expired; open_vin_with_credit must be called again, which asks the user again"
)


def _with_session(url: str, session: str) -> str:
    """Return ``url`` with its ``session`` query value replaced by ``session``."""
    parts = urlsplit(url)
    pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "session"]
    pairs.append(("session", session))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


def _strip_session(url: str) -> str:
    """Return ``url`` without its ``session`` query value (the unit identity key)."""
    parts = urlsplit(url)
    pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "session"]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


def _find_node(nodes: list[TreeNode], node_id: str) -> TreeNode | None:
    """Find a tree node by id, searching all levels in order."""
    for node in nodes:
        if node.id == node_id:
            return node
        found = _find_node(node.children, node_id)
        if found is not None:
            return found
    return None


def _flatten(nodes: list[TreeNode]) -> list[TreeNode]:
    """List all tree nodes in order, across all levels."""
    flat: list[TreeNode] = []
    for node in nodes:
        flat.append(node)
        flat.extend(_flatten(node.children))
    return flat


@dataclass
class CatalogHandle:
    """One open catalog match. Catalog text is data and is never interpreted."""

    catalog_id: str
    vin: str
    route: Literal["garage", "credit"]
    iframe_url: str
    match_index: int
    match: VehicleMatch
    session: str
    group_tree: list[TreeNode] | None = None
    category_tree: list[TreeNode] | None = None
    units: dict[str, UnitRef | GroupUnit] = field(default_factory=dict)
    unit_keys: dict[str, str] = field(default_factory=dict)


class CatalogRegistry:
    """Keep open catalogs in memory and hand out short ids for them and their units."""

    def __init__(self, laximo: LaximoClient) -> None:
        self._laximo = laximo
        self._catalogs: dict[str, CatalogHandle] = {}
        self._next_catalog = 1

    async def open(
        self, vin: str, route: Literal["garage", "credit"], iframe_url: str
    ) -> list[CatalogHandle]:
        """Open one handle per vehicle match on the entry page."""
        matches = await self._laximo.entry(iframe_url)
        if not matches:
            raise UnsupportedCarError(f"No vehicle found in the catalog for VIN {vin}")
        handles: list[CatalogHandle] = []
        for index, match in enumerate(matches):
            session = session_param(match.group_list_url or match.category_list_url) or ""
            handle = CatalogHandle(
                catalog_id=f"c{self._next_catalog}",
                vin=vin,
                route=route,
                iframe_url=iframe_url,
                match_index=index,
                match=match,
                session=session,
            )
            self._next_catalog += 1
            self._catalogs[handle.catalog_id] = handle
            handles.append(handle)
        return handles

    def get(self, catalog_id: str) -> CatalogHandle:
        """Return the handle for ``catalog_id`` or raise CatalogExpiredError."""
        try:
            return self._catalogs[catalog_id]
        except KeyError:
            raise CatalogExpiredError(_UNKNOWN_CATALOG_MESSAGE) from None

    async def _fetch_fresh(
        self,
        handle: CatalogHandle,
        fetch: Callable[[str], Awaitable[str]],
        is_fresh: Callable[[str], bool],
    ) -> str:
        """Fetch once; on a stale page re-open the entry once (garage route) and retry once."""
        html = await fetch(handle.session)
        if is_fresh(html):
            return html
        if handle.route == "credit":
            raise CatalogExpiredError(_CREDIT_EXPIRED_MESSAGE)
        matches = await self._laximo.entry(handle.iframe_url)
        if handle.match_index >= len(matches):
            raise CatalogExpiredError("catalog session expired; the vehicle list changed on re-open")
        handle.match = matches[handle.match_index]
        new_session = session_param(handle.match.group_list_url or handle.match.category_list_url)
        if new_session:
            handle.session = new_session
        html = await fetch(handle.session)
        if is_fresh(html):
            return html
        raise CatalogExpiredError("catalog session expired; re-opening the catalog did not help")

    def _register_unit(self, handle: CatalogHandle, ref: UnitRef | GroupUnit) -> str:
        """Hand out the per-handle unit id, reusing it for the same session-free URL."""
        key = _strip_session(ref.unit_url)
        existing = handle.unit_keys.get(key)
        if existing is not None:
            return existing
        uid = f"u{len(handle.units) + 1}"
        handle.units[uid] = ref
        handle.unit_keys[key] = uid
        return uid

    async def group_tree(self, catalog_id: str) -> list[TreeNode]:
        """Return (and cache) the parsed tree catalog."""
        handle = self.get(catalog_id)
        if handle.group_tree is not None:
            return handle.group_tree
        if handle.match.group_list_url is None:
            raise UnsupportedCarError("This car has no tree catalog")

        async def fetch(session: str) -> str:
            url = handle.match.group_list_url
            if url is None:
                raise CatalogExpiredError("catalog session expired; the vehicle list changed on re-open")
            return await self._laximo.page(_with_session(url, session))

        html = await self._fetch_fresh(handle, fetch, lambda h: "'data' : [" in h)
        handle.group_tree = parse_jstree(html)
        return handle.group_tree

    async def category_tree(self, catalog_id: str) -> list[TreeNode]:
        """Return (and cache) the parsed picture catalog categories."""
        handle = self.get(catalog_id)
        if handle.category_tree is not None:
            return handle.category_tree
        if handle.match.category_list_url is None:
            raise UnsupportedCarError("This car has no picture catalog")

        async def fetch(session: str) -> str:
            url = handle.match.category_list_url
            if url is None:
                raise CatalogExpiredError("catalog session expired; the vehicle list changed on re-open")
            return await self._laximo.page(_with_session(url, session))

        html = await self._fetch_fresh(handle, fetch, lambda h: "'data' : [" in h)
        handle.category_tree = parse_jstree(html)
        return handle.category_tree

    async def search(self, catalog_id: str, query: str) -> list[dict]:
        """Search the tree catalog (case- and diacritics-insensitive)."""
        tree = await self.group_tree(catalog_id)
        return search_tree(tree, query)

    async def browse(self, catalog_id: str, node_id: str | None) -> list[dict]:
        """List top-level nodes (``None``) or the children of ``node_id``."""
        tree = await self.group_tree(catalog_id)
        if node_id is None:
            nodes = tree
        else:
            node = _find_node(tree, node_id)
            if node is None:
                raise ValueError(f"unknown tree node: {node_id}")
            nodes = node.children
        return [
            {"id": n.id, "text": n.text, "openable": bool(n.token), "leaf": not n.children} for n in nodes
        ]

    async def group_parts(self, catalog_id: str, node_id: str) -> list[dict]:
        """Open a tree leaf and return its units, each with its ``unit_id``."""
        tree = await self.group_tree(catalog_id)
        handle = self.get(catalog_id)
        node = _find_node(tree, node_id)
        if node is None:
            raise ValueError(f"unknown tree node: {node_id}")
        if node.token is None:
            raise ValueError(f"tree node {node_id} ({node.text}) is not openable")

        async def fetch(session: str) -> str:
            return await self._laximo.group_parts(session, node.token or "")

        html = await self._fetch_fresh(handle, fetch, lambda h: "groupsUnitList" in h)
        result: list[dict] = []
        for unit in parse_group_parts(html):
            uid = self._register_unit(handle, unit)
            result.append(unit.to_dict() | {"unit_id": uid})
        return result

    async def category_units(self, catalog_id: str, category: str) -> list[dict]:
        """List the units of a picture category given by id, exact or normalised name."""
        tree = await self.category_tree(catalog_id)
        handle = self.get(catalog_id)
        flat = _flatten(tree)
        node: TreeNode | None = None
        for candidate in flat:
            if candidate.id == category:
                node = candidate
                break
        if node is None:
            for candidate in flat:
                if candidate.text == category:
                    node = candidate
                    break
        if node is None:
            wanted = normalize(category)
            for candidate in flat:
                if normalize(candidate.text) == wanted:
                    node = candidate
                    break
        if node is None:
            available = ", ".join(n.text for n in tree)
            raise ValueError(f"unknown category: {category!r}; available categories: {available}")
        if node.token is None:
            raise ValueError(f"category {category!r} ({node.text}) is not openable")

        async def fetch(session: str) -> str:
            return await self._laximo.category_units(session, node.token or "")

        html = await self._fetch_fresh(handle, fetch, lambda h: "unitItem" in h or "Části vozu" in h)
        result: list[dict] = []
        for ref in parse_category_units(html):
            uid = self._register_unit(handle, ref)
            result.append({"unit_id": uid, "code": ref.code, "name": ref.name})
        return result

    async def unit(self, catalog_id: str, unit_id: str) -> tuple[UnitRef | GroupUnit, UnitDetail]:
        """Return the stored unit reference together with its parsed diagram page."""
        handle = self.get(catalog_id)
        try:
            ref = handle.units[unit_id]
        except KeyError:
            raise ValueError(f"unknown unit: {unit_id}") from None

        async def fetch(session: str) -> str:
            return await self._laximo.page(_with_session(ref.unit_url, session))

        html = await self._fetch_fresh(
            handle, fetch, lambda h: 'id="viewport"' in h or 'id="units"' in h
        )
        return ref, parse_unit(html)
