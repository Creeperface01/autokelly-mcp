"""Tests for diacritics-insensitive fuzzy search over the parsed group tree."""

from __future__ import annotations

import pytest
from conftest import fixture_text

from autokelly_mcp.parsers.laximo import parse_jstree
from autokelly_mcp.tree_search import normalize, search_tree


@pytest.fixture(scope="module")
def tree():
    return parse_jstree(fixture_text("laximo/hyundai_group_list.html"))


def test_normalize_strips_diacritics_and_collapses_whitespace():
    assert normalize("Chladič  Vody") == "chladic vody"


def test_search_chladic_vody_finds_leaf(tree):
    results = search_tree(tree, "chladič vody")
    assert results
    first = results[0]
    assert first["id"] == "10203"
    assert first["path"] == ["Chlazeni", "Chladic voda/ olej", "Chladic vody"]
    assert first["openable"] is True
    assert first["leaf"] is True


def test_search_case_insensitive_includes_variants(tree):
    texts = [r["text"] for r in search_tree(tree, "CHLADIC")]
    assert "Chladic vody" in texts
    assert "Olejovy chladic" in texts


def test_search_termostat_first(tree):
    results = search_tree(tree, "termostat")
    assert results
    assert results[0]["text"] == "Termostat"


def test_search_typo_still_finds_node(tree):
    ids = [r["id"] for r in search_tree(tree, "chladic vodi")[:3]]
    assert "10203" in ids


def test_search_no_match_returns_empty(tree):
    assert search_tree(tree, "xyzzy") == []
