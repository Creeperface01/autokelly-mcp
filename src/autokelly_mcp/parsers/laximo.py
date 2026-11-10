"""Parsers for Laximo catalog pages: entry matches, trees, part lists and units."""

from __future__ import annotations

import html
import json
import re
from urllib.parse import parse_qs, urlparse

from selectolax.lexbor import LexborHTMLParser

from autokelly_mcp.errors import UnsupportedCarError
from autokelly_mcp.models import Callout, GroupUnit, PartRow, TreeNode, UnitDetail, UnitRef, VehicleMatch
from autokelly_mcp.parsers.autokelly import clean

_JSTREE_MARKER = "'data' : ["
_STYLE_VALUE_RE = re.compile(r"(width|height|margin-top|margin-left)\s*:\s*([\d.]+)\s*px", re.IGNORECASE)


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


def _enclosing_unit_row(block):
    """Return the nearest ancestor ``<tr>`` holding this image block's unit."""
    node = block.parent
    while node is not None:
        if node.tag == "tr" and node.css_first("a.title") is not None:
            return node
        node = node.parent
    return None


def parse_group_parts(html_text: str) -> list[GroupUnit]:
    """Parse a group part-list page into one GroupUnit per image block.

    The title is ``a.title``, the image is the ``a.fancybox`` href, the
    thumbnail is the ``.image img`` src. Rows (``tr[id^=d_]``) whose first
    class token is ``top`` are matched parts, the rest are other parts.
    """
    tree = LexborHTMLParser(html_text)
    units: list[GroupUnit] = []
    for block in tree.css("div.groupListImage"):
        scope = _enclosing_unit_row(block)
        if scope is None:
            continue
        title_node = scope.css_first("a.title")
        if title_node is None:
            continue
        fancy = block.css_first("a.fancybox")
        thumb = block.css_first(".image img")
        matched: list[PartRow] = []
        other: list[PartRow] = []
        for row in scope.css("tr[id^=d_]"):
            if not row.attributes.get("id", "").startswith("d_"):
                continue
            cells = row.css("td")
            if len(cells) < 2:
                continue
            part = PartRow(
                callout=row.attributes.get("name") or None,
                oem=clean(cells[0].text()),
                name=clean(cells[1].text()),
            )
            first_token = (row.attributes.get("class", "") or "").split()
            (matched if first_token and first_token[0] == "top" else other).append(part)
        units.append(
            GroupUnit(
                title=clean(title_node.text()),
                unit_url=html.unescape(title_node.attributes.get("href", "")),
                image_url=html.unescape(fancy.attributes.get("href", "") if fancy is not None else ""),
                thumb_url=html.unescape(thumb.attributes.get("src", "") if thumb is not None else ""),
                matched_parts=matched,
                other_parts=other,
            )
        )
    return units


def parse_category_units(html_text: str) -> list[UnitRef]:
    """Parse a category unit-list page into one UnitRef per ``div.unitItem``."""
    tree = LexborHTMLParser(html_text)
    refs: list[UnitRef] = []
    for item in tree.css("div.unitItem"):
        link = item.css_first("p a")
        if link is None:
            continue
        strong = link.css_first("strong")
        code = clean(strong.text()) if strong is not None else ""
        full = clean(link.text())
        name = full[len(code):].strip() if code and full.startswith(code) else full
        thumb_url = ""
        for anchor in item.css('a[href^="/cs/unit"]'):
            img = anchor.css_first("img")
            if img is not None:
                thumb_url = html.unescape(img.attributes.get("src", ""))
                break
        refs.append(
            UnitRef(
                code=code,
                name=name,
                unit_url=html.unescape(link.attributes.get("href", "")),
                thumb_url=thumb_url,
            )
        )
    return refs


def _style_px(style: str, prop: str) -> int:
    for match in _STYLE_VALUE_RE.finditer(style):
        if match.group(1).lower() == prop:
            return round(float(match.group(2)))
    return 0


def parse_unit(html_text: str) -> UnitDetail:
    """Parse a unit (diagram) page into its image, callouts and parts.

    Raises UnsupportedCarError when neither ``#viewport`` nor
    ``table#units`` is present (an unrecognised layout).
    """
    tree = LexborHTMLParser(html_text)
    if tree.css_first("#viewport") is None and tree.css_first("table#units") is None:
        raise UnsupportedCarError("Unsupported car: the unit page has no diagram or parts table.")
    viewport_img = tree.css_first("#viewport img.dragger")
    image_url = html.unescape(viewport_img.attributes.get("src", "") if viewport_img is not None else "")
    callouts = [
        Callout(
            code=div.attributes.get("name", ""),
            left=_style_px(div.attributes.get("style", ""), "margin-left"),
            top=_style_px(div.attributes.get("style", ""), "margin-top"),
            width=_style_px(div.attributes.get("style", ""), "width"),
            height=_style_px(div.attributes.get("style", ""), "height"),
        )
        for div in tree.css("div.dragger.g_highlight[name]")
    ]
    parts: list[PartRow] = []
    table = tree.css_first("table#units")
    if table is not None:
        for row in table.css("tr[id^=d_]"):
            if not row.attributes.get("id", "").startswith("d_"):
                continue
            oem_node = row.css_first("td.g_oem")
            name_node = row.css_first("td.g_ttd")
            note_node = row.css_first("td.g_note")
            models_node = row.css_first("td.g_models")
            info: dict[str, str] = {}
            for entry in row.css(".infoBox tr"):
                key_node = entry.css_first("th")
                value_node = entry.css_first("td")
                if key_node is None or value_node is None:
                    continue
                key = clean(key_node.text()).rstrip(":").strip()
                if not key or key == "OEM":
                    continue
                info[key] = clean(value_node.text())
            parts.append(
                PartRow(
                    callout=row.attributes.get("name") or None,
                    oem=clean(oem_node.text()) if oem_node is not None else "",
                    name=clean(name_node.text()) if name_node is not None else "",
                    note=clean(note_node.text()) if note_node is not None else "",
                    models=clean(models_node.text()) if models_node is not None else "",
                    info=info,
                )
            )
    return UnitDetail(image_url=image_url, callouts=callouts, parts=parts)
