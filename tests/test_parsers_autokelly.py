import pytest
from conftest import fixture_json, fixture_text

from autokelly_mcp.errors import NotLoggedInError
from autokelly_mcp.models import Credits, StockEntry
from autokelly_mcp.parsers.autokelly import (
    parse_catalog_entry,
    parse_credits,
    parse_disponibility,
    parse_garage_cars,
    parse_oem_items,
    parse_stock,
    parse_user_prices,
)


def test_garage_cars():
    cars = parse_garage_cars(fixture_json("autokelly/garage_cars.json"))
    assert [c.vin for c in cars] == ["TESTVINHYUNDAI001", "TESTVINALFA000001"]
    assert cars[0].id == "00000000-0000-0000-0000-000000000001"
    assert cars[0].plate == "1AB0001" and cars[0].kw == "118"
    assert cars[0].name == "HYUNDAI / I30 combi (PDE) / 1.5 T-GDI Hybrid 48V"


def test_garage_logged_out_raises():
    with pytest.raises(NotLoggedInError):
        parse_garage_cars(fixture_json("autokelly/garage_cars_logged_out.json"))


def test_credits_and_logged_out():
    assert parse_credits(fixture_json("autokelly/vin_credit.json")) == Credits(5, False, "Počet VIN kreditů: 5")
    assert parse_credits(fixture_json("autokelly/vin_credit_logged_out.json")) is None


def test_catalog_entry():
    e = parse_catalog_entry(fixture_text("autokelly/vin_page_hyundai.html"))
    assert e.iframe_url.startswith("https://vinsearch.autokelly.cz/cs/search/vin/TESTVINHYUNDAI001?domain=https://www.autokelly.cz&blank=0&cc=AK_CZ&cn=9999999&searchurl=")
    assert e.search_guid == "11111111-2222-3333-4444-555555555555"
    assert parse_catalog_entry("<html><body>no catalog</body></html>") is None


def test_oem_items_prices_stock_disponibility():
    items = parse_oem_items(fixture_json("autokelly/oem_items_25310J7800.json"))
    assert [i["id"] for i in items] == ["13089926", "1008231127", "1020327787"]
    assert items[0]["name"] == "Chladič vody NISSENS"
    assert (items[0]["brand"], items[0]["code"], items[0]["link"]) == ("NISSENS", "NS 636728", "/Product/NS-636728/13089926")
    assert parse_user_prices(fixture_json("autokelly/user_price.json")) == {
        "13089926": "5 239 Kč", "1008231127": "12 943 Kč", "1020327787": "13 150 Kč"}
    stock = parse_stock(fixture_json("autokelly/product_stock.json"))
    assert stock["13089926"][0] == StockEntry("Ostrava-Poruba", "OSPO", "0", False)
    assert stock["1008231127"][2] == StockEntry("", "Jiné", "do 48h", False)
    assert parse_disponibility(fixture_json("autokelly/product_disponibility.json")) == {
        "13089926": "Běžně do 17 dnů", "1008231127": "Běžně do 48h", "1020327787": "Běžně do 48h"}
