"""AutokellyClient: garage, catalog routes and OEM search with prices and stock."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import TypeVar

from autokelly_mcp.auth import Auth
from autokelly_mcp.config import BASE_URL
from autokelly_mcp.errors import (
    AutokellyError,
    CreditRefusedError,
    NotLoggedInError,
    UnknownCarError,
    UnsupportedCarError,
)
from autokelly_mcp.http import Fetcher, classify, parse_json
from autokelly_mcp.models import CatalogEntry, Credits, GarageCar, Offer
from autokelly_mcp.parsers.autokelly import (
    parse_catalog_entry,
    parse_credits,
    parse_disponibility,
    parse_garage_cars,
    parse_oem_items,
    parse_stock,
    parse_user_prices,
)
from autokelly_mcp.session_store import load_session, update_search_guid

T = TypeVar("T")

_GARAGE_LIST_REFERER = BASE_URL + "/Garage/CarList"
_HOME_REFERER = BASE_URL + "/"


class AutokellyClient:
    """The only code that talks to www.autokelly.cz endpoints. Never touches /Cart/."""

    def __init__(self, fetcher: Fetcher, auth: Auth) -> None:
        self._fetcher = fetcher
        self._auth = auth

    def _run(self, fn: Callable[[], Awaitable[T]]) -> Awaitable[T]:
        return self._auth.with_relogin(fn)

    async def credits(self) -> Credits:
        """Return the current VIN credit balance."""

        async def impl() -> Credits:
            return await self._credits_impl()

        return await self._run(impl)

    async def _credits_impl(self) -> Credits:
        resp = await self._fetcher.post_json(BASE_URL + "/vin-decoder/credit", None, referer=_HOME_REFERER)
        data = parse_json(resp)
        credits = parse_credits(data if isinstance(data, dict) else {})
        if credits is None:
            raise NotLoggedInError("Not logged in: the credit endpoint returned no data.")
        return credits

    async def garage_cars(self) -> list[GarageCar]:
        """Return all cars in the user's garage."""

        async def impl() -> list[GarageCar]:
            return await self._garage_cars_impl()

        return await self._run(impl)

    async def _garage_cars_impl(self) -> list[GarageCar]:
        resp = await self._fetcher.post_json(BASE_URL + "/Garage/Cars/1", None, referer=_GARAGE_LIST_REFERER)
        classify(resp, expect_json=True)
        if resp.text == "" and resp.status == 200:
            return parse_garage_cars("")
        data = parse_json(resp)
        return parse_garage_cars(data if isinstance(data, dict) else {})

    async def find_garage_car(self, query: str) -> GarageCar:
        """Resolve a car id, VIN or plate (ignoring case and separators) to a garage car."""

        async def impl() -> GarageCar:
            cars = await self._garage_cars_impl()
            for car in cars:
                if query == car.id:
                    return car
            normalised = re.sub(r"[^A-Z0-9]", "", query.upper())
            for car in cars:
                if normalised and (
                    normalised == re.sub(r"[^A-Z0-9]", "", car.vin.upper())
                    or normalised == re.sub(r"[^A-Z0-9]", "", car.plate.upper())
                ):
                    return car
            raise UnknownCarError(f"Unknown car: {query!r}.", cars=cars)

        return await self._run(impl)

    async def garage_vins(self) -> set[str]:
        """Return the VINs of all garage cars."""

        async def impl() -> set[str]:
            return {car.vin for car in await self._garage_cars_impl() if car.vin}

        return await self._run(impl)

    @staticmethod
    def _vin_page_url(vin: str, from_garage: bool) -> tuple[str, str]:
        if from_garage:
            return BASE_URL + f"/catalog/graphic/VIN/{vin}/garage", _GARAGE_LIST_REFERER
        return BASE_URL + f"/catalog/graphic/VIN/{vin}", _HOME_REFERER

    async def catalog_entry(self, vin: str, from_garage: bool) -> CatalogEntry:
        """Open the VIN catalog page and cache its search guid."""

        async def impl() -> CatalogEntry:
            return await self._catalog_entry_impl(vin, from_garage)

        return await self._run(impl)

    async def _catalog_entry_impl(self, vin: str, from_garage: bool) -> CatalogEntry:
        url, referer = self._vin_page_url(vin, from_garage)
        resp = await self._fetcher.get(url, referer=referer)
        classify(resp, expect_json=False)
        entry = parse_catalog_entry(resp.text)
        if entry is None:
            raise UnsupportedCarError(f"No VIN catalog for {vin}")
        update_search_guid(entry.search_guid)
        return entry

    async def notify_decoded(self, vin: str, from_garage: bool) -> None:
        """Tell the site the VIN was decoded, mirroring the website's own call."""

        async def impl() -> None:
            url, _ = self._vin_page_url(vin, from_garage)
            resp = await self._fetcher.post_json(
                BASE_URL + f"/catalog/graphic/vin/{vin}/decoded",
                {"decodedFromGarage": from_garage},
                referer=url,
            )
            parse_json(resp)

        await self._run(impl)

    async def verify_usage_vin(self, vin: str) -> None:
        """Check the paid route may be used; raise CreditRefusedError when it may not."""

        async def impl() -> None:
            resp = await self._fetcher.post_json(
                BASE_URL + "/vin-decoder/verify-usage-vin",
                {"vin": vin, "fromGarage": False},
                referer=_HOME_REFERER,
            )
            data = parse_json(resp)
            payload = data.get("data") if isinstance(data, dict) else None
            payload = payload if isinstance(payload, dict) else {}
            if payload.get("CanBeUsed") is not True:
                reason = str(payload.get("ReasonMessage", "") or "")
                raise CreditRefusedError(reason or "VIN credit use was refused.", reason=reason)

        await self._run(impl)

    async def oem_search(self, oem: str) -> list[Offer]:
        """Search Autokelly offers by OEM number, merging prices, stock and availability."""

        async def impl() -> list[Offer]:
            return await self._oem_search_impl(oem)

        return await self._run(impl)

    async def _oem_search_impl(self, oem: str) -> list[Offer]:
        normalised = re.sub(r"[^A-Z0-9]", "", oem.upper())
        if not normalised:
            raise ValueError("empty OEM number")
        session = load_session()
        guid = session.search_guid if session is not None else None
        if not guid:
            cars = await self._garage_cars_impl()
            if not cars:
                raise AutokellyError("Autokelly search id unknown: no garage car to read it from")
            guid = (await self._catalog_entry_impl(cars[0].vin, True)).search_guid
        page_url = BASE_URL + f"/search/oem/{guid}/{normalised}"
        page_resp = await self._fetcher.get(page_url, referer=_HOME_REFERER)
        classify(page_resp, expect_json=False)
        items_resp = await self._fetcher.post_json(
            BASE_URL + "/ProductList/Items/GraphicsCatalogOem/1", None, referer=page_url
        )
        items_data = parse_json(items_resp)
        items = parse_oem_items(items_data if isinstance(items_data, dict) else {})
        if not items:
            return []
        ids = [item["id"] for item in items]
        price_resp = await self._fetcher.post_json(
            BASE_URL + "/UserPrice/Data", {"productIds": ids}, referer=page_url
        )
        stock_resp = await self._fetcher.post_json(
            BASE_URL + "/ProductStock/Data",
            {"productIds": ids, "listType": "GraphicsCatalogOem", "viewType": "ImageList"},
            referer=page_url,
        )
        disponibility_resp = await self._fetcher.post_json(
            BASE_URL + "/ProductDisponibility/data", {"productIds": ids}, referer=page_url
        )
        price_data = parse_json(price_resp)
        stock_data = parse_json(stock_resp)
        disponibility_data = parse_json(disponibility_resp)
        prices = parse_user_prices(price_data if isinstance(price_data, dict) else {})
        stock = parse_stock(stock_data if isinstance(stock_data, dict) else {})
        disponibility = parse_disponibility(
            disponibility_data if isinstance(disponibility_data, dict) else {}
        )
        offers: list[Offer] = []
        for item in items:
            product_id = item["id"]
            offers.append(
                Offer(
                    shop="autokelly",
                    product_id=product_id,
                    name=item["name"],
                    brand=item["brand"],
                    code=item["code"],
                    price_vat=prices.get(product_id, ""),
                    availability=disponibility.get(product_id) or item["availability"],
                    stock=stock.get(product_id, []),
                    url=BASE_URL + item["link"],
                    is_oe=item["is_oe"],
                )
            )
        return offers
