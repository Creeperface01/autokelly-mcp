"""Parsers for Laximo catalog pages: VIN entry matches and jstree trees."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from selectolax.lexbor import LexborHTMLParser

from autokelly_mcp.models import TreeNode, VehicleMatch
from autokelly_mcp.parsers.autokelly import clean

_JSTREE_MARKER = "'data' : ["


def session_param(url: str | None) -> str | None:
    """Return the ``session`` query value of a Laximo URL, or None."""
    if not url:
        return None
    values = parse_qs(urlparse(url).query).get("session", [])
    return values[0] if values else None


def parse_entry(html_text: str) -> list[VehicleMatch]:
    """Parse the Laximo VIN entry page into vehicle matches.

    Each ``div.carName`` block starts one match: its ``h2 a`` text is the
    name and its ``a.linkButton`` hrefs are the group-list and
    category-list URLs. The match's params are the two-cell
    ``<td>key</td><td>value</td>`` rows after its ``carName`` block and
    before the next one. Returns ``[]`` when there are no matches.
    """
    tree = LexborHTMLParser(html_text)
    matches: list[VehicleMatch] = []
    names: list[str] = []
    group_urls: list[str | None] = []
    category_urls: list[str | None] = []
    params: list[dict[str, str]] = []

    def current() -> int:
        return len(names) - 1

    for node in tree.css("div.carName, table.parameters tr"):
        if node.tag == "div":
            name_node = node.css_first("h2 a")
            names.append(clean(name_node.text() if name_node else ""))
            group_url: str | None = None
            category_url: str | None = None
            for link in node.css("a.linkButton"):
                href = link.attributes.get("href", "")
                if not href:
                    continue
                if "group-list" in href:
                    group_url = href
                elif "category-list" in href:
                    category_url = href
            group_urls.append(group_url)
            category_urls.append(category_url)
            params.append({})
        elif current() >= 0 and node.tag == "tr":
            cells = node.css("td")
            if len(cells) != 2:
                continue
            key = clean(cells[0].text())
            if key:
                params[current()][key] = clean(cells[1].text())

    for i, name in enumerate(names):
        matches.append(
            VehicleMatch(
                name=name,
                params=params[i],
                group_list_url=group_urls[i],
                category_list_url=category_urls[i],
            )
        )
    return matches


def _build_node(item: dict) -> TreeNode:
    return TreeNode(
        id=item.get("id", ""),
        text=clean(item.get("text", "")),
        token=item.get("token"),
        children=[_build_node(child) for child in item.get("children") or []],
    )


def parse_jstree(html_text: str) -> list[TreeNode]:
    """Parse the jstree JSON embedded in a group/category list page.

    Locates ``'data' : [`` in the jstree init script and bracket-matches
    the JSON array. Returns ``[]`` if the marker is absent (or the JSON
    does not parse, e.g. on a stale-session page).
    """
    marker_at = html_text.find(_JSTREE_MARKER)
    if marker_at == -1:
        return []
    start = marker_at + len(_JSTREE_MARKER) - 1  # position of the opening '['
    depth = 0
    in_string = False
    escaped = False
    for pos in range(start, len(html_text)):
        char = html_text[pos]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(html_text[start : pos + 1])
                except json.JSONDecodeError:
                    return []
                return [_build_node(item) for item in data]
    return []
