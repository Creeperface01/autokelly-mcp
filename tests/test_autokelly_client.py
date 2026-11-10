"""AutokellyClient: garage, catalog routes and OEM search with prices/stock."""

import pytest
from conftest import FakeFetcher, make_response

from autokelly_mcp.auth import Auth
from autokelly_mcp.autokelly import AutokellyClient
from autokelly_mcp.errors import AutokellyError, CreditRefusedError, UnknownCarError, UnsupportedCarError
from autokelly_mcp.session_store import SessionData, load_session, save_session

_GUID = "11111111-2222-3333-4444-555555555555"
_HYUNDAI_ID = "00000000-0000-0000-0000-000000000001"


def _make_client(routes, *, counter=None):
    if counter is None:
        counter = {"logins": 0}
    fetcher = FakeFetcher(routes)

    async def fake_login() -> SessionData:
        counter["logins"] += 1
        return SessionData(cookies=[], user_agent="ua")

    auth = Auth(fetcher, login=fake_login)
    return fetcher, AutokellyClient(fetcher, auth), counter


def _oem_routes():
    return [
        ("GET", "search/oem/", make_response("<html><body>oem page</body></html>")),
        ("POST", "ProductList/Items/GraphicsCatalogOem/1", "autokelly/oem_items_25310J7800.json"),
        ("POST", "UserPrice/Data", "autokelly/user_price.json"),
        ("POST", "ProductStock/Data", "autokelly/product_stock.json"),
        ("POST", "ProductDisponibility/data", "autokelly/product_disponibility.json"),
    ]


def _credit_ok_routes():
    return [("POST", "vin-decoder/credit", "autokelly/vin_credit.json")]


@pytest.mark.anyio
async def test_find_garage_car_variants():
    _fetcher, client, _ = _make_client([("POST", "Garage/Cars/1", "autokelly/garage_cars.json")])
    for query in (
        "testvinhyundai001",
        " TESTVIN HYUNDAI001 ",
        "1ab 0001",
        "1AB-0001",
        _HYUNDAI_ID,
    ):
        car = await client.find_garage_car(query)
        assert car.vin == "TESTVINHYUNDAI001"
    with pytest.raises(UnknownCarError) as exc_info:
        await client.find_garage_car("XYZ")
    assert len(exc_info.value.cars) == 2


@pytest.mark.anyio
async def test_catalog_entry_garage_caches_guid():
    fetcher, client, _ = _make_client([("GET", "catalog/graphic/VIN/", "autokelly/vin_page_hyundai.html")])
    entry = await client.catalog_entry("TESTVINHYUNDAI001", True)
    assert entry.search_guid == _GUID
    assert any(
        method == "GET" and url.endswith("/catalog/graphic/VIN/TESTVINHYUNDAI001/garage")
        for method, url, _ in fetcher.calls
    )
    assert load_session() is not None
    assert load_session().search_guid == _GUID


@pytest.mark.anyio
async def test_catalog_entry_without_iframe_unsupported():
    _fetcher, client, _ = _make_client(
        [("GET", "catalog/graphic/VIN/", make_response("<html><body>no iframe</body></html>"))]
    )
    with pytest.raises(UnsupportedCarError):
        await client.catalog_entry("TESTVINHYUNDAI001", False)


@pytest.mark.anyio
async def test_oem_search_normalises_and_merges():
    for raw in ("25310-J7800", " 25310 j7800 ", "25310J7800"):
        save_session(SessionData(cookies=[], user_agent="ua", search_guid=_GUID))
        fetcher, client, _ = _make_client(_oem_routes())
        offers = await client.oem_search(raw)
        assert [url for method, url, _ in fetcher.calls if method == "GET"] == [
            f"https://www.autokelly.cz/search/oem/{_GUID}/25310J7800"
        ]
        assert [(o.brand, o.price_vat) for o in offers] == [
            ("NISSENS", "5 239 Kč"),
            ("Originální díl KIA", "12 943 Kč"),
            ("Originální díl HYUNDAI", "13 150 Kč"),
        ]
        assert offers[0].url == "https://www.autokelly.cz/Product/NS-636728/13089926"
        assert offers[0].availability == "Běžně do 17 dnů"
        assert offers[1].stock[2].stock == "do 48h"


@pytest.mark.anyio
async def test_oem_search_without_cached_guid_reads_garage_page_without_decoded():
    fetcher, client, _ = _make_client(
        [
            ("POST", "Garage/Cars/1", "autokelly/garage_cars.json"),
            ("GET", "catalog/graphic/VIN/", "autokelly/vin_page_hyundai.html"),
            *_oem_routes(),
        ]
    )
    offers = await client.oem_search("25310J7800")
    assert len(offers) == 3
    assert load_session() is not None
    assert load_session().search_guid == _GUID
    assert not any("/decoded" in url for _, url, _ in fetcher.calls)


@pytest.mark.anyio
async def test_verify_usage_refused():
    refused = make_response('{"data": {"CanBeUsed": false, "ReasonMessage": "Nedostatek kreditů"}}')
    _, client, _ = _make_client([("POST", "vin-decoder/verify-usage-vin", refused)])
    with pytest.raises(CreditRefusedError) as exc_info:
        await client.verify_usage_vin("TESTVINHYUNDAI001")
    assert exc_info.value.reason == "Nedostatek kreditů"


@pytest.mark.anyio
async def test_never_calls_cart():
    save_session(SessionData(cookies=[], user_agent="ua", search_guid=_GUID))
    fetcher, client, _ = _make_client(
        [
            ("POST", "vin-decoder/credit", "autokelly/vin_credit.json"),
            ("POST", "Garage/Cars/1", "autokelly/garage_cars.json"),
            ("GET", "catalog/graphic/VIN/", "autokelly/vin_page_hyundai.html"),
            ("POST", "catalog/graphic/vin/", make_response("true")),
            ("POST", "vin-decoder/verify-usage-vin", make_response('{"data": {"CanBeUsed": true}}')),
            *_oem_routes(),
        ]
    )
    await client.credits()
    await client.garage_cars()
    await client.garage_vins()
    await client.find_garage_car("TESTVINHYUNDAI001")
    await client.catalog_entry("TESTVINHYUNDAI001", True)
    await client.notify_decoded("TESTVINHYUNDAI001", True)
    await client.verify_usage_vin("TESTVINHYUNDAI001")
    await client.oem_search("25310J7800")
    assert fetcher.calls
    assert not any("/Cart/" in url for _, url, _ in fetcher.calls)


@pytest.mark.anyio
async def test_oem_search_empty_garage_without_guid():
    def empty_garage(method: str, url: str, body: object):
        return make_response('{"Items": []}', url=url)

    _, client, _ = _make_client([("POST", "Garage/Cars/1", empty_garage)])
    with pytest.raises(AutokellyError):
        await client.oem_search("25310J7800")
