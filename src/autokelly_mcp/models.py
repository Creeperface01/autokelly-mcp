"""Shared dataclasses used by parsers, clients and tools."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field


def _to_dict(self: object) -> dict:
    return dataclasses.asdict(self)


@dataclass(frozen=True)
class GarageCar:
    id: str
    name: str
    vin: str
    plate: str
    kw: str
    hp: str
    ccm: str
    fuel: str

    to_dict = _to_dict


@dataclass(frozen=True)
class Credits:
    credit: int
    unlimited: bool
    message: str

    to_dict = _to_dict


@dataclass(frozen=True)
class CatalogEntry:
    iframe_url: str
    search_guid: str

    to_dict = _to_dict


@dataclass(frozen=True)
class VehicleMatch:
    name: str
    params: dict[str, str]
    group_list_url: str | None
    category_list_url: str | None

    to_dict = _to_dict


@dataclass
class TreeNode:
    id: str
    text: str
    token: str | None
    children: list[TreeNode] = field(default_factory=list)

    to_dict = _to_dict


@dataclass(frozen=True)
class PartRow:
    callout: str | None
    oem: str
    name: str
    note: str = ""
    models: str = ""
    info: dict[str, str] = field(default_factory=dict)

    to_dict = _to_dict


@dataclass(frozen=True)
class GroupUnit:
    title: str
    unit_url: str
    image_url: str
    thumb_url: str
    matched_parts: list[PartRow]
    other_parts: list[PartRow]

    to_dict = _to_dict


@dataclass(frozen=True)
class UnitRef:
    code: str
    name: str
    unit_url: str
    thumb_url: str

    to_dict = _to_dict


@dataclass(frozen=True)
class Callout:
    code: str
    left: int
    top: int
    width: int
    height: int

    to_dict = _to_dict


@dataclass(frozen=True)
class UnitDetail:
    image_url: str
    callouts: list[Callout]
    parts: list[PartRow]

    to_dict = _to_dict


@dataclass(frozen=True)
class StockEntry:
    location: str
    abbrev: str
    stock: str
    in_stock: bool

    to_dict = _to_dict


@dataclass(frozen=True)
class Offer:
    shop: str
    product_id: str
    name: str
    brand: str
    code: str
    price_vat: str
    availability: str
    stock: list[StockEntry]
    url: str
    is_oe: bool

    to_dict = _to_dict
