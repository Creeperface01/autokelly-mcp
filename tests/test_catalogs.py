"""LaximoClient + CatalogRegistry: open handles, navigation, stale-session recovery."""

from __future__ import annotations

import pytest
from conftest import FakeFetcher, fixture_text, make_response

from autokelly_mcp.catalogs import CatalogRegistry
from autokelly_mcp.errors import CatalogExpiredError
from autokelly_mcp.laximo import LaximoClient
from autokelly_mcp.parsers.laximo import parse_jstree

HYUNDAI_IFRAME = "https://vinsearch.autokelly.cz/cs/search/vin/TESTVINHYUNDAI001"
ALFA_IFRAME = "https://vinsearch.autokelly.cz/cs/search/vin/TESTVINALFA000001"
HYUNDAI_VIN = "TESTVINHYUNDAI001"
ALFA_VIN = "TESTVINALFA000001"


def _hyundai_routes(extra=None):
    routes = [
        ("GET", "search/vin", "laximo/hyundai_entry.html"),
        ("GET", "group-list", "laximo/hyundai_group_list.html"),
        ("GET", "category-list", "laximo/hyundai_category_list.html"),
        ("POST", "group-part-list", "laximo/hyundai_group_part_list_chladic_vody.html"),
        ("POST", "category-unit-list", "laximo/hyundai_category_unit_list_engine.html"),
        ("GET", "/cs/unit", "laximo/hyundai_unit_25-253.html"),
    ]
    if extra:
        routes = extra + routes
    return routes


def _make_registry(routes):
    fetcher = FakeFetcher(routes)
    return fetcher, CatalogRegistry(LaximoClient(fetcher))


@pytest.mark.anyio
async def test_open_two_matches_alfa():
    fetcher, reg = _make_registry([("GET", "search/vin", "laximo/alfa_entry.html")])
    handles = await reg.open(ALFA_VIN, "garage", ALFA_IFRAME)
    assert [h.catalog_id for h in handles] == ["c1", "c2"]
    assert handles[0].match.params["Pohon"] == "LHD"
    assert handles[1].match.params["Pohon"] == "RHD"
    assert fetcher.calls


@pytest.mark.anyio
async def test_search_and_group_parts_hyundai():
    fetcher, reg = _make_registry(_hyundai_routes())
    handles = await reg.open(HYUNDAI_VIN, "garage", HYUNDAI_IFRAME)
    cid = handles[0].catalog_id
    assert cid == "c1"
    results = await reg.search(cid, "chladic vody")
    assert results[0]["id"] == "10203"
    units = await reg.group_parts(cid, "10203")
    assert len(units) == 4
    assert [u["unit_id"] for u in units] == ["u1", "u2", "u3", "u4"]
    assert units[0]["matched_parts"][0]["oem"] == "25310-J7800"
    tree = parse_jstree(fixture_text("laximo/hyundai_group_list.html"))

    def find(nodes, target):
        for node in nodes:
            if node.id == target:
                return node
            found = find(node.children, target)
            if found is not None:
                return found
        return None

    expected_token = find(tree, "10203").token
    posts = [c for c in fetcher.calls if c[0] == "POST" and "group-part-list" in c[1]]
    assert posts
    assert posts[0][2]["token"] == expected_token


@pytest.mark.anyio
async def test_category_units_by_name_and_unit():
    _fetcher, reg = _make_registry(_hyundai_routes())
    handles = await reg.open(HYUNDAI_VIN, "garage", HYUNDAI_IFRAME)
    cid = handles[0].catalog_id
    units = await reg.category_units(cid, "engine")
    assert len(units) == 68
    uid = next(u["unit_id"] for u in units if u["code"] == "25-253")
    ref, detail = await reg.unit(cid, uid)
    assert len(detail.parts) == 43
    assert ref.code == "25-253"


@pytest.mark.anyio
async def test_same_unit_url_reuses_id():
    _fetcher, reg = _make_registry(_hyundai_routes())
    handles = await reg.open(HYUNDAI_VIN, "garage", HYUNDAI_IFRAME)
    cid = handles[0].catalog_id
    first = await reg.group_parts(cid, "10203")
    ids_first = [u["unit_id"] for u in first]
    # Same node fetched again must reuse the same unit ids.
    second = await reg.group_parts(cid, "10203")
    assert [u["unit_id"] for u in second] == ids_first
    # Same unit URL with a different session param must reuse its id.
    handle = reg.get(cid)
    handle.session = "9999999999999"
    third = await reg.group_parts(cid, "10203")
    assert [u["unit_id"] for u in third] == ids_first


@pytest.mark.anyio
async def test_stale_session_reopens_once():
    entry_text = fixture_text("laximo/hyundai_entry.html")
    entry_calls = {"n": 0}

    def entry_route(method, url, body):
        entry_calls["n"] += 1
        if entry_calls["n"] == 1:
            return make_response(entry_text, url=url)
        return make_response(entry_text.replace("0000000000001", "0000000000002"), url=url)

    post_calls = {"n": 0}

    def group_parts_route(method, url, body):
        post_calls["n"] += 1
        if post_calls["n"] == 1:
            assert "session=0000000000001" in url
            return make_response("<html></html>", url=url)
        assert "session=0000000000002" in url
        return make_response(
            fixture_text("laximo/hyundai_group_part_list_chladic_vody.html"), url=url
        )

    fetcher = FakeFetcher(
        [
            ("GET", "search/vin", entry_route),
            ("GET", "group-list", "laximo/hyundai_group_list.html"),
            ("POST", "group-part-list", group_parts_route),
        ]
    )
    reg = CatalogRegistry(LaximoClient(fetcher))
    handles = await reg.open(HYUNDAI_VIN, "garage", HYUNDAI_IFRAME)
    units = await reg.group_parts(handles[0].catalog_id, "10203")
    assert len(units) == 4
    assert entry_calls["n"] == 2

    # Still stale after reopen -> CatalogExpiredError, entry fetched exactly 2x total.
    entry_calls2 = {"n": 0}

    def entry_route2(method, url, body):
        entry_calls2["n"] += 1
        return make_response(entry_text, url=url)

    def stale_route(method, url, body):
        return make_response("<html></html>", url=url)

    fetcher2 = FakeFetcher(
        [
            ("GET", "search/vin", entry_route2),
            ("GET", "group-list", "laximo/hyundai_group_list.html"),
            ("POST", "group-part-list", stale_route),
        ]
    )
    reg2 = CatalogRegistry(LaximoClient(fetcher2))
    handles2 = await reg2.open(HYUNDAI_VIN, "garage", HYUNDAI_IFRAME)
    with pytest.raises(CatalogExpiredError):
        await reg2.group_parts(handles2[0].catalog_id, "10203")
    assert entry_calls2["n"] == 2


@pytest.mark.anyio
async def test_stale_session_credit_route_does_not_reopen():
    entry_calls = {"n": 0}
    entry_text = fixture_text("laximo/hyundai_entry.html")

    def entry_route(method, url, body):
        entry_calls["n"] += 1
        return make_response(entry_text, url=url)

    fetcher = FakeFetcher(
        [
            ("GET", "search/vin", entry_route),
            ("GET", "group-list", "laximo/hyundai_group_list.html"),
            ("POST", "group-part-list", make_response("<html></html>")),
        ]
    )
    reg = CatalogRegistry(LaximoClient(fetcher))
    handles = await reg.open(HYUNDAI_VIN, "credit", HYUNDAI_IFRAME)
    with pytest.raises(CatalogExpiredError):
        await reg.group_parts(handles[0].catalog_id, "10203")
    assert entry_calls["n"] == 1


@pytest.mark.anyio
async def test_unknown_catalog_id():
    _fetcher, reg = _make_registry(_hyundai_routes())
    with pytest.raises(CatalogExpiredError):
        reg.get("c999")
    with pytest.raises(CatalogExpiredError):
        await reg.group_tree("c999")
