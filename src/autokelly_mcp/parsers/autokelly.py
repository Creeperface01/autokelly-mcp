"""Parsers for Autokelly JSON/HTML responses (garage, credits, OEM offers)."""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, urlparse

from selectolax.lexbor import LexborHTMLParser

from autokelly_mcp.errors import NotLoggedInError
from autokelly_mcp.models import CatalogEntry, Credits, GarageCar, StockEntry

_OEM_GUID_RE = re.compile(r"/oem/([^/]+)/", re.IGNORECASE)


def clean(value: object) -> str:
    """Collapse whitespace and unescape HTML entities."""
    if value is None:
        return ""
    return " ".join(html.unescape(str(value)).split())


def parse_garage_cars(data: object) -> list[GarageCar]:
    """Parse the POST /Garage/Cars/{page} response into garage cars."""
    if data == "":
        raise NotLoggedInError("Not logged in: the garage endpoint returned an empty response.")
    if not isinstance(data, dict):
        raise NotLoggedInError("Not logged in: unexpected garage response.")
    cars: list[GarageCar] = []
    items = data.get("Items", [])
    if not isinstance(items, list):
        return []
    for item in items:
        if not isinstance(item, dict):
            continue
        cars.append(
            GarageCar(
                id=str(item.get("Id", "")),
                name=clean(item.get("Name", "")),
                vin=clean(item.get("VIN", "")),
                plate=clean(item.get("LicencePlate", "")),
                kw=clean(item.get("KW", "")),
                hp=clean(item.get("HP", "")),
                ccm=clean(item.get("CCM", "")),
                fuel=clean(item.get("Fuel", "")),
            )
        )
    return cars


def parse_credits(data: dict) -> Credits | None:
    """Parse the POST /vin-decoder/credit response. None means logged out."""
    if not isinstance(data, dict):
        return None
    payload = data.get("data")
    if not isinstance(payload, dict):
        return None
    return Credits(
        credit=int(payload.get("Credit", 0)),
        unlimited=bool(payload.get("HasUnlimitedAccess", False)),
        message=clean(payload.get("VinCreditMessage", "")),
    )


def parse_catalog_entry(html_text: str) -> CatalogEntry | None:
    """Extract the Laximo iframe URL and search guid from a VIN catalog page."""
    tree = LexborHTMLParser(html_text)
    iframe = tree.css_first("#laximoFrame")
    if iframe is None:
        return None
    src = iframe.attributes.get("src", "")
    if not src:
        return None
    iframe_url = html.unescape(src)
    query = parse_qs(urlparse(iframe_url).query)
    search_urls = query.get("searchurl", [])
    if not search_urls:
        return None
    match = _OEM_GUID_RE.search(search_urls[0])
    if not match:
        return None
    return CatalogEntry(iframe_url=iframe_url, search_guid=match.group(1))


def parse_oem_items(data: dict) -> list[dict]:
    """Parse POST /ProductList/Items/GraphicsCatalogOem/1 into plain offer dicts."""
    items = data.get("Items", []) if isinstance(data, dict) else []
    result: list[dict] = []
    if not isinstance(items, list):
        return []
    for item in items:
        if not isinstance(item, dict):
            continue
        disponibility = item.get("Disponibility") or {}
        availability = disponibility.get("Text", "") if isinstance(disponibility, dict) else ""
        result.append(
            {
                "id": str(item.get("Id", "")),
                "name": clean(item.get("Text", "")),
                "brand": clean(item.get("Brand", "")),
                "code": clean(item.get("Code", "")),
                "link": str(item.get("Link", "")),
                "is_oe": bool(item.get("IsOEPart", False)),
                "availability": clean(availability),
            }
        )
    return result


def parse_user_prices(data: dict) -> dict[str, str]:
    """Parse POST /UserPrice/Data into product id -> PriceVat."""
    content = data.get("Content", []) if isinstance(data, dict) else []
    prices: dict[str, str] = {}
    if not isinstance(content, list):
        return {}
    for entry in content:
        if not isinstance(entry, dict):
            continue
        prices[str(entry.get("ProductId", ""))] = clean(entry.get("PriceVat", ""))
    return prices


def parse_stock(data: dict) -> dict[str, list[StockEntry]]:
    """Parse POST /ProductStock/Data into product id -> stock entries."""
    items = data.get("items", []) if isinstance(data, dict) else []
    stock: dict[str, list[StockEntry]] = {}
    if not isinstance(items, list):
        return {}
    for item in items:
        if not isinstance(item, dict):
            continue
        entries: list[StockEntry] = []
        storages = item.get("storages", [])
        if isinstance(storages, list):
            for storage in storages:
                if not isinstance(storage, dict):
                    continue
                entries.append(
                    StockEntry(
                        location=clean(storage.get("Text", "")),
                        abbrev=clean(storage.get("Abbrev", "")),
                        stock=clean(storage.get("Stock", "")),
                        in_stock=bool(storage.get("IsStock", False)),
                    )
                )
        stock[str(item.get("productId", ""))] = entries
    return stock


def parse_disponibility(data: dict) -> dict[str, str]:
    """Parse POST /ProductDisponibility/data into product id -> availability text."""
    items = data.get("items", []) if isinstance(data, dict) else []
    result: dict[str, str] = {}
    if not isinstance(items, list):
        return {}
    for item in items:
        if not isinstance(item, dict):
            continue
        disponibility = item.get("Disponibility") or {}
        text = disponibility.get("Text", "") if isinstance(disponibility, dict) else ""
        result[str(item.get("ProductId", ""))] = clean(text)
    return result
