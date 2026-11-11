"""Tests for skills/compare-part-prices/extract-offers.js, run in a real headless browser.

The script runs in the user's browser on imdily.cz, autodily-pema.cz and granex.cz search
pages. Here it runs against saved pages served at the real shop URLs through request
interception, so nothing goes to the network. Chromium cannot start inside the macOS
sandbox; there these tests are skipped with the launch error as the reason.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
SCRIPT = (REPO / "skills/compare-part-prices/extract-offers.js").read_text(encoding="utf-8")
SHOPS = Path(__file__).parent / "fixtures" / "shops"


@pytest.fixture(scope="module")
def browser() -> Iterator[object]:
    from playwright.sync_api import Error, sync_playwright

    with sync_playwright() as p:
        launched = None
        errors: list[str] = []
        for kwargs in ({"channel": "chrome"}, {}):
            try:
                launched = p.chromium.launch(headless=True, **kwargs)
                break
            except Error as exc:
                errors.append(str(exc).splitlines()[0])
        if launched is None:
            pytest.skip(f"no headless browser available: {errors}")
        yield launched
        launched.close()


def run(browser, html: str, url: str) -> dict:
    """Serve ``html`` as the document at ``url``, block everything else, run the script."""
    page = browser.new_page()
    try:

        def handle(route):
            if route.request.url == url:
                route.fulfill(status=200, body=html, content_type="text/html; charset=utf-8")
            else:
                route.abort()

        page.route("**/*", handle)
        page.goto(url)
        return page.evaluate(SCRIPT)
    finally:
        page.close()


def fixture(name: str) -> str:
    return (SHOPS / name).read_text(encoding="utf-8")


PEMA_URL = "https://www.autodily-pema.cz/vyhledavani?search=25310-J7800"
GRANEX_URL = "https://granex.cz/vyhledavani?search=26300-35505"


def test_radiator_page_reads_offers(browser):
    result = run(browser, fixture("search_radiator.html"), PEMA_URL)
    assert result["shop"] == "autodily-pema.cz"
    assert result["query"] == "25310-J7800"
    assert result["blocked"] is False
    assert result["has_more"] is False
    assert [o["brand"] for o in result["offers"]] == ["MAXGEAR", "NISSENS", "NRF", "HYUNDAI-KIA"]
    assert all(o["brand_source"] == "shop" for o in result["offers"])

    maxgear = result["offers"][0]
    assert maxgear["code"] == "AC230412"
    assert maxgear["price_czk"] == 1369
    assert maxgear["availability"] == {"label": "Skladem na externím skladě", "available": True}
    assert maxgear["oe"] is False
    assert maxgear["params"]["Délka sítě"] == "648 mm"
    assert maxgear["url"] == "https://www.autodily-pema.cz/chladic-chlazeni-motoru-maxgear-ac230412"


def test_radiator_page_keeps_dimensions_for_mismatch_check(browser):
    offers = run(browser, fixture("search_radiator.html"), PEMA_URL)["offers"]
    sizes = {o["brand"]: (o["params"].get("Délka sítě"), o["params"].get("Šířka sítě")) for o in offers}
    assert sizes["MAXGEAR"] == ("648 mm", "291 mm")
    assert sizes["NRF"] == ("505 mm", "388 mm")


def test_original_part_is_marked(browser):
    oe = run(browser, fixture("search_radiator.html"), PEMA_URL)["offers"][3]
    assert oe["oe"] is True
    assert oe["brand"] == "HYUNDAI-KIA"
    assert oe["code"] == "25310F3300"
    assert oe["price_czk"] == 3730
    assert oe["notes"] == []


def test_brands_are_guessed_without_analytics(browser):
    offers = run(browser, fixture("search_oil_filter_page1.html"), GRANEX_URL)["offers"]
    assert [(o["brand"], o["code"]) for o in offers[1:]] == [
        ("MANN-FILTER", "W 811/80"),
        ("BLUE PRINT", "ADS72101"),
        ("FILTRON", "OP 617"),
        ("HELLA", "8ZO 366 100-281"),
    ]
    assert all(o["brand_source"] == "guess" for o in offers)


def test_original_without_brand_and_shop_notes(browser):
    oe = run(browser, fixture("search_oil_filter_page1.html"), GRANEX_URL)["offers"][0]
    assert oe["oe"] is True
    assert oe["brand"] == ""
    assert oe["name"] == "Olejový filtr Kia/Hyundai OE 2630035505"
    assert oe["availability"] == {"label": "Skladem > 5 ks", "available": True}
    assert oe["notes"] == ["Díl není možné vrátit zpět v případě nákupu na IČ."]


def test_unorderable_offer_has_no_price(browser):
    hella = run(browser, fixture("search_oil_filter_page1.html"), GRANEX_URL)["offers"][4]
    assert hella["price_czk"] is None
    assert hella["availability"] == {"label": "Nelze objednat", "available": False}


def test_pagination_gives_next_page(browser):
    result = run(browser, fixture("search_oil_filter_page1.html"), GRANEX_URL)
    assert result["page"] == 1
    assert result["last_page"] == 2
    assert result["has_more"] is True
    assert result["next_page_url"] == "https://granex.cz/vyhledavani?search=26300-35505&page=2"


def test_last_page_has_no_next(browser):
    url = "https://granex.cz/vyhledavani?search=26300-35505&page=2"
    result = run(browser, fixture("search_oil_filter_page1.html"), url)
    assert result["page"] == 2
    assert result["has_more"] is False
    assert result["next_page_url"] == ""


def test_challenge_page_is_reported_blocked(browser):
    result = run(browser, fixture("challenge.html"), "https://imdily.cz/vyhledavani?search=25310-J7800")
    assert result["blocked"] is True
    assert result["offers"] == []


def test_ua_analytics_format_gives_brands(browser):
    html = """<html><head><script>
      window.dataLayer = [{ecommerce: {impressions: [
        {name: "Olejový filtr HERTH+BUSS JAKOPARTS J1317003", brand: "HERTH+BUSS JAKOPARTS"}]}}];
    </script></head><body><main>
      <section class="productInline"><h2 class="productInline__heading">
        <a href="/x">Olejový filtr HERTH+BUSS JAKOPARTS J1317003</a></h2></section>
    </main></body></html>"""
    offer = run(browser, html, "https://imdily.cz/vyhledavani?search=26300-35505")["offers"][0]
    assert (offer["brand"], offer["brand_source"], offer["code"]) == (
        "HERTH+BUSS JAKOPARTS",
        "shop",
        "J1317003",
    )


def test_no_results(browser):
    html = "<html><body><main><h1>Vyhledávání „XYZ“</h1><p>Nic nenalezeno.</p></main></body></html>"
    result = run(browser, html, "https://imdily.cz/vyhledavani?search=XYZ")
    assert result["offers"] == []
    assert result["has_more"] is False
    assert result["blocked"] is False


def test_output_stays_small_for_truncating_tools(browser):
    card = (
        '<section class="productInline"><h2 class="productInline__heading"><a href="/p{i}">'
        "Olejový filtr BOSCH {long}{i}</a></h2></section>"
    )
    long_code = "X" * 400
    html = "<html><body><main>" + "".join(card.format(i=i, long=long_code) for i in range(120))
    html += "</main></body></html>"
    result = run(browser, html, "https://imdily.cz/vyhledavani?search=0451103316")
    assert len(result["offers"]) == 100
    longest = max(len(s) for s in _strings(result))
    assert longest <= 200


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def test_result_is_json_serialisable(browser):
    result = run(browser, fixture("search_radiator.html"), PEMA_URL)
    assert json.loads(json.dumps(result)) == result
