"""Tests for Laximo entry page and jstree parsers (first half of parsers/laximo.py)."""

from __future__ import annotations

from collections.abc import Iterator

from conftest import fixture_text

from autokelly_mcp.models import TreeNode
from autokelly_mcp.parsers.laximo import parse_entry, parse_jstree, session_param


def walk(
    nodes: list[TreeNode], prefix: list[str] | None = None
) -> Iterator[tuple[TreeNode, list[str]]]:
    """Yield (node, path) depth-first, pre-order."""
    prefix = prefix or []
    for node in nodes:
        path = [*prefix, node.text]
        yield node, path
        yield from walk(node.children, path)


def test_entry_single_match_hyundai():
    m = parse_entry(fixture_text("laximo/hyundai_entry.html"))
    assert len(m) == 1 and m[0].name == "HYUNDAI i30"
    assert m[0].params["Engine no."] == "G4LKPZ000000" and m[0].params["Model"] == "G4W5K8G17"
    assert m[0].group_list_url.startswith("/cs/catalog/group-list/")
    assert m[0].category_list_url.startswith("/cs/catalog/category-list/")
    assert session_param(m[0].group_list_url) == "0000000000001"


def test_entry_two_matches_alfa_lhd_rhd():
    m = parse_entry(fixture_text("laximo/alfa_entry.html"))
    assert [x.name for x in m] == ["ALFA ROMEO 147 [147 BZ/DS (2000-2010)]"] * 2
    assert [x.params["Pohon"] for x in m] == ["LHD", "RHD"]
    assert m[0].params["Motor"] == "2000 TS 16V (M10)"


def test_entry_none():
    assert parse_entry("<html><body>Nenalezeno</body></html>") == []


def test_group_tree_hyundai_and_alfa():
    for car, total in [("hyundai", 430), ("alfa", 382)]:
        tree = parse_jstree(fixture_text(f"laximo/{car}_group_list.html"))
        assert len(tree) == 28 and tree[0].text == "Karoserie"
        flat = list(walk(tree))                      # helper in the test: yields (node, path)
        assert len(flat) == total
        node, path = next((n, p) for n, p in flat if n.id == "10203")
        assert node.text == "Chladic vody" and path == ["Chlazeni", "Chladic voda/ olej", "Chladic vody"]
        assert node.token


def test_category_tree():
    h = parse_jstree(fixture_text("laximo/hyundai_category_list.html"))
    assert [n.text for n in h] == ["ENGINE", "TRANSMISSION", "CHASSIS", "BODY", "TRIM", "ELECTRICAL"]
    a = parse_jstree(fixture_text("laximo/alfa_category_list.html"))
    assert a[0].text == "MOTOR A ZÁVĚŠENÍ" and len(list(walk(a))) == 137
