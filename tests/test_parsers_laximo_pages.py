"""Tests for Laximo part-list, unit-list and unit-page parsers (parsers/laximo.py)."""

from __future__ import annotations

import pytest
from conftest import fixture_text

from autokelly_mcp.errors import UnsupportedCarError
from autokelly_mcp.models import Callout, PartRow
from autokelly_mcp.parsers.laximo import parse_category_units, parse_group_parts, parse_unit


def test_group_parts_hyundai_radiator():
    units = parse_group_parts(fixture_text("laximo/hyundai_group_part_list_chladic_vody.html"))
    assert len(units) == 4 and {u.title for u in units} == {"25-253: ENGINE COOLING SYSTEM"}
    assert len({u.unit_url for u in units}) == 4
    u = units[0]
    assert u.unit_url.startswith("/cs/unit?token=") and "&session=0000000000001" in u.unit_url
    assert u.image_url.endswith("/source/cat/1/H/HEURPG420/2525311.gif?s=342122797&k=fad4582c75f1c97a1184db8dd5a38a6c")
    assert u.matched_parts == [PartRow("25310", "25310-J7800", "RADIATOR ASSY")]
    assert len(u.other_parts) == 42
    oems = {p.oem: p.name for p in u.other_parts}
    assert oems["25343-F2000"] == "RUBBER INSULATION"
    assert oems["25336-F2000"] == "INSULATOR - RADIATOR MOUNTING, LOWER"


def test_group_parts_alfa_czech_names():
    (u,) = parse_group_parts(fixture_text("laximo/alfa_group_part_list_chladic_vody.html"))
    assert u.title == "10401/00: CHLADIČ A HADICE (Var.: 1/Rev.: 0)"
    assert u.matched_parts == [PartRow("1", "51702463", "CHLADIČ")]
    assert [p.oem for p in u.other_parts if p.name == "ELASTICKÉ POUZDRO"] == ["46746135", "46436961"]


def test_category_units():
    h = parse_category_units(fixture_text("laximo/hyundai_category_unit_list_engine.html"))
    assert len(h) == 68 and (h[0].code, h[0].name) == ("09-091", "OWNERS VEHICLE MAINTENANCE TOOL")
    assert sum(1 for r in h if (r.code, r.name) == ("25-253", "ENGINE COOLING SYSTEM")) == 4
    a = parse_category_units(fixture_text("laximo/alfa_category_unit_list_motor.html"))
    assert len(a) == 6 and (a[0].code, a[0].name) == ("10000/01", "MOTOR (Var.: 1/Rev.: 0)")


def test_unit_hyundai():
    d = parse_unit(fixture_text("laximo/hyundai_unit_25-253.html"))
    assert d.image_url == ("https://img.altechopersys.com/YQHC3/source/cat/1/H/HEURPG420/2525311.gif"
                           "?s=342122797&k=fad4582c75f1c97a1184db8dd5a38a6c")
    assert len(d.callouts) == 55 and d.callouts[0] == Callout("1120AE", 470, 348, 48, 18)
    assert len(d.parts) == 43
    assert PartRow("25310", "25310-J7800", "RADIATOR ASSY") in [PartRow(p.callout, p.oem, p.name) for p in d.parts]
    assert [p.oem for p in d.parts if p.callout == "14720A"][:2] == ["14720-14006S", "14720-22006S"]
    assert all(p.oem != "51110029880" and "OEM" not in p.info for p in d.parts)


def test_unit_alfa():
    d = parse_unit(fixture_text("laximo/alfa_unit_10401.html"))
    assert len(d.callouts) == 17 and d.callouts[0] == Callout("1", 949, 790, 57, 57)
    assert len(d.parts) == 8 and (d.parts[0].callout, d.parts[0].oem, d.parts[0].name) == ("1", "51702463", "CHLADIČ")
    assert d.parts[0].info["Familyname"] == "OOP ENGINE RADIATOR"


def test_unit_unrecognised_layout():
    with pytest.raises(UnsupportedCarError):
        parse_unit("<html><body><p>other layout</p></body></html>")
