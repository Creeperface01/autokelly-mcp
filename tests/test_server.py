"""FastMCP server tools: garage flow, credit flow, and error mapping."""

from __future__ import annotations

import json
import re
from io import BytesIO

import pytest
from conftest import FakeFetcher, fixture_text, make_response
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ImageContent, TextContent
from PIL import Image as PILImage

from autokelly_mcp.confirm import confirm_credit_use
from autokelly_mcp.http import Response
from autokelly_mcp.server import build_server
from autokelly_mcp.session_store import SessionData

EXTERNAL_VIN = "TESTVINEXTERN0001"


def _test_png() -> bytes:
    img = PILImage.new("RGB", (800, 600), (255, 255, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_TEST_PNG = _test_png()


class _NoElicitSession:
    def check_client_capability(self, capability) -> bool:
        return False


class _NoElicitCtx:
    def __init__(self) -> None:
        self.session = _NoElicitSession()

    async def elicit(self, message, schema):  # pragma: no cover - must not be called
        raise AssertionError("elicit must not be called when unsupported")


async def _token_confirm(ctx, vin, credits, book, token, *, reopen=False):
    """Wrap the real confirm_credit_use with a ctx that has no elicitation."""
    return await confirm_credit_use(_NoElicitCtx(), vin, credits, book, token, reopen=reopen)


async def _decline_confirm(ctx, vin, credits, book, token, *, reopen=False):
    return "declined"


async def _fake_login() -> SessionData:
    return SessionData(cookies=[], user_agent="ua")


def _vin_page_external(method: str, url: str, body: object) -> Response:
    html = fixture_text("autokelly/vin_page_hyundai.html").replace("TESTVINHYUNDAI001", EXTERNAL_VIN)
    return make_response(html, url=url)


def _image_route(method: str, url: str, body: object) -> Response:
    return Response(status=200, headers={}, text="", content=_TEST_PNG, url=url)


def _routes(*, vin_page="autokelly/vin_page_hyundai.html"):
    return [
        ("POST", "Garage/Cars/1", "autokelly/garage_cars.json"),
        ("POST", "vin-decoder/credit", "autokelly/vin_credit.json"),
        ("GET", "catalog/graphic/VIN/", vin_page),
        ("POST", "catalog/graphic/vin/", make_response("true")),
        ("POST", "vin-decoder/verify-usage-vin", make_response('{"data": {"CanBeUsed": true}}')),
        ("GET", "search/vin", "laximo/hyundai_entry.html"),
        ("GET", "group-list", "laximo/hyundai_group_list.html"),
        ("POST", "group-part-list", "laximo/hyundai_group_part_list_chladic_vody.html"),
        ("GET", "/cs/unit", "laximo/hyundai_unit_25-253.html"),
        ("GET", "img.altechopersys.com", _image_route),
    ]


def _payload(blocks):
    assert isinstance(blocks[0], TextContent)
    return json.loads(blocks[0].text)


def _payload_list(blocks):
    return [json.loads(block.text) for block in blocks if isinstance(block, TextContent)]


def _no_paid_calls(calls) -> bool:
    return (
        not any("verify-usage-vin" in url for _, url, _ in calls)
        and not any(method == "GET" and "catalog/graphic/VIN/" in url for method, url, _ in calls)
        and not any("/decoded" in url for _, url, _ in calls)
    )


@pytest.mark.anyio
async def test_tool_list():
    mcp = build_server(fetcher=FakeFetcher([]), login=_fake_login)
    names = sorted(tool.name for tool in await mcp.list_tools())
    assert names == sorted(
        [
            "account_status",
            "login",
            "list_garage_cars",
            "open_garage_car",
            "open_vin_with_credit",
            "search_tree",
            "browse_tree",
            "get_group_parts",
            "list_picture_units",
            "get_unit",
            "search_autokelly_by_oem",
        ]
    )


@pytest.mark.anyio
async def test_account_status_reports_credits():
    fetcher = FakeFetcher([("POST", "vin-decoder/credit", "autokelly/vin_credit.json")])
    mcp = build_server(fetcher=fetcher, login=_fake_login, confirm=_token_confirm)
    assert _payload(await mcp.call_tool("account_status", {})) == {
        "logged_in": True,
        "credits": 5,
        "unlimited": False,
    }


@pytest.mark.anyio
async def test_garage_flow_hyundai():
    fetcher = FakeFetcher(_routes())
    mcp = build_server(fetcher=fetcher, login=_fake_login, confirm=_token_confirm)

    opened = _payload(await mcp.call_tool("open_garage_car", {"car": "1AB0001"}))
    assert opened["vin"] == "TESTVINHYUNDAI001"
    assert opened["route"] == "garage"
    assert len(opened["matches"]) == 1
    match = opened["matches"][0]
    assert set(match) == {"catalog_id", "name", "params", "has_tree", "has_pictures"}
    decoded = [(method, url, body) for method, url, body in fetcher.calls if "/decoded" in url]
    assert len(decoded) == 1
    assert decoded[0][2] == {"decodedFromGarage": True}

    cid = match["catalog_id"]
    found = _payload_list(
        await mcp.call_tool("search_tree", {"catalog_id": cid, "query": "chladic vody"})
    )
    assert found[0]["id"] == "10203"
    units = _payload_list(
        await mcp.call_tool("get_group_parts", {"catalog_id": cid, "node_id": "10203"})
    )
    assert len(units) == 4
    blocks = await mcp.call_tool(
        "get_unit", {"catalog_id": cid, "unit_id": units[0]["unit_id"], "highlight": "25310-J7800"}
    )
    assert len(blocks) == 3
    assert isinstance(blocks[0], TextContent)
    assert isinstance(blocks[1], ImageContent)
    assert isinstance(blocks[2], ImageContent)
    assert json.loads(blocks[0].text)["unit_id"] == units[0]["unit_id"]

    assert not any("/Cart/" in url for _, url, _ in fetcher.calls)


@pytest.mark.anyio
async def test_open_vin_in_garage_redirects():
    fetcher = FakeFetcher(_routes())
    mcp = build_server(fetcher=fetcher, login=_fake_login, confirm=_token_confirm)
    result = _payload(await mcp.call_tool("open_vin_with_credit", {"vin": "testvinhyundai001"}))
    assert result["status"] == "in_garage"
    assert result["hint"] == "use open_garage_car"
    assert result["car"]["vin"] == "TESTVINHYUNDAI001"
    assert not any("verify-usage-vin" in url for _, url, _ in fetcher.calls)


@pytest.mark.anyio
async def test_open_vin_in_garage_form_differs_single_lookup_no_paid_calls():
    """A garage VIN stored lowercase must still take the free route (one fetch)."""

    def garage_lower(method: str, url: str, body: object) -> Response:
        text = fixture_text("autokelly/garage_cars.json").replace(
            "TESTVINHYUNDAI001", "testvinhyundai001"
        )
        return make_response(text, url=url)

    routes = [route for route in _routes() if "Garage/Cars" not in route[1]]
    routes.append(("POST", "Garage/Cars/1", garage_lower))
    fetcher = FakeFetcher(routes)
    mcp = build_server(fetcher=fetcher, login=_fake_login, confirm=_token_confirm)
    result = _payload(
        await mcp.call_tool("open_vin_with_credit", {"vin": " TESTVIN hyundai001 "})
    )
    assert result["status"] == "in_garage"
    assert result["hint"] == "use open_garage_car"
    assert result["car"]["vin"] == "testvinhyundai001"
    assert _no_paid_calls(fetcher.calls)
    assert sum(1 for _, url, _ in fetcher.calls if "Garage/Cars" in url) == 1


@pytest.mark.anyio
async def test_credit_flow_token_path():
    routes = _routes(vin_page=_vin_page_external)
    fetcher = FakeFetcher(routes)
    mcp = build_server(fetcher=fetcher, login=_fake_login, confirm=_token_confirm)

    first = _payload(await mcp.call_tool("open_vin_with_credit", {"vin": EXTERNAL_VIN}))
    assert first["status"] == "confirmation_required"
    assert first["confirm_token"]
    assert _no_paid_calls(fetcher.calls)

    seen = len(fetcher.calls)
    second = _payload(
        await mcp.call_tool(
            "open_vin_with_credit", {"vin": EXTERNAL_VIN, "confirm_token": first["confirm_token"]}
        )
    )
    new = fetcher.calls[seen:]

    def index(pred):
        return next(i for i, (method, url, _) in enumerate(new) if pred(method, url))

    i_verify = index(lambda m, u: "verify-usage-vin" in u)
    i_vinpage = index(lambda m, u: m == "GET" and u.endswith(f"/catalog/graphic/VIN/{EXTERNAL_VIN}"))
    i_entry = index(lambda m, u: "search/vin" in u)
    i_decoded = index(lambda m, u: "/decoded" in u)
    credits = [i for i, (m, u, _) in enumerate(new) if "vin-decoder/credit" in u]
    i_credit = credits[-1]
    assert i_verify < i_vinpage < i_entry < i_decoded < i_credit
    assert new[i_decoded][2] == {"decodedFromGarage": False}

    assert second["vin"] == EXTERNAL_VIN
    assert second["credits_left"] == 5
    assert len(second["matches"]) == 1

    def count(pred) -> int:
        return sum(1 for method, url, _ in new if pred(method, url))

    assert count(lambda m, u: "verify-usage-vin" in u) == 1
    assert count(lambda m, u: m == "GET" and u.endswith(f"/catalog/graphic/VIN/{EXTERNAL_VIN}")) == 1
    assert count(lambda m, u: "search/vin" in u) == 1
    assert count(lambda m, u: "/decoded" in u) == 1


@pytest.mark.anyio
async def test_zero_credits_refuses_without_confirmation_or_paid_calls():
    def credit_zero(method: str, url: str, body: object) -> Response:
        return make_response(
            '{"data": {"Credit": 0, "VinCreditMessage": "0", "HasUnlimitedAccess": false}}',
            url=url,
        )

    routes = [
        route for route in _routes(vin_page=_vin_page_external) if "vin-decoder/credit" not in route[1]
    ]
    routes.append(("POST", "vin-decoder/credit", credit_zero))
    fetcher = FakeFetcher(routes)
    confirm_calls: list = []

    async def _never_confirm(ctx, vin, credits, book, token, *, reopen=False):
        confirm_calls.append(vin)
        raise AssertionError("confirmation must not be asked with zero credits")

    mcp = build_server(fetcher=fetcher, login=_fake_login, confirm=_never_confirm)
    with pytest.raises(ToolError, match="No VIN credits left"):
        await mcp.call_tool("open_vin_with_credit", {"vin": EXTERNAL_VIN})
    assert confirm_calls == []
    assert _no_paid_calls(fetcher.calls)


@pytest.mark.anyio
async def test_reopen_note_expires_after_window():
    now = [2000.0]
    fetcher = FakeFetcher(_routes(vin_page=_vin_page_external))
    mcp = build_server(
        fetcher=fetcher, login=_fake_login, confirm=_token_confirm, clock=lambda: now[0]
    )

    first = _payload(await mcp.call_tool("open_vin_with_credit", {"vin": EXTERNAL_VIN}))
    assert first["status"] == "confirmation_required"
    assert "pravděpodobně" not in first["message"]
    second = _payload(
        await mcp.call_tool(
            "open_vin_with_credit", {"vin": EXTERNAL_VIN, "confirm_token": first["confirm_token"]}
        )
    )
    assert second["vin"] == EXTERNAL_VIN

    now[0] += 3599.0
    third = _payload(await mcp.call_tool("open_vin_with_credit", {"vin": EXTERNAL_VIN}))
    assert third["status"] == "confirmation_required"
    assert "pravděpodobně" in third["message"]

    now[0] += 2.0
    fourth = _payload(await mcp.call_tool("open_vin_with_credit", {"vin": EXTERNAL_VIN}))
    assert fourth["status"] == "confirmation_required"
    assert "pravděpodobně" not in fourth["message"]


@pytest.mark.anyio
async def test_credit_flow_declined_makes_no_calls():
    fetcher = FakeFetcher(_routes(vin_page=_vin_page_external))
    mcp = build_server(fetcher=fetcher, login=_fake_login, confirm=_decline_confirm)
    result = _payload(await mcp.call_tool("open_vin_with_credit", {"vin": EXTERNAL_VIN}))
    assert result == {"status": "declined"}
    assert _no_paid_calls(fetcher.calls)


@pytest.mark.anyio
async def test_invalid_vin_rejected():
    mcp = build_server(fetcher=FakeFetcher(_routes()), login=_fake_login, confirm=_token_confirm)
    with pytest.raises(ToolError):
        await mcp.call_tool("open_vin_with_credit", {"vin": "ABC"})


@pytest.mark.anyio
async def test_reopen_after_paid_open_mentions_probably_free():
    routes = _routes(vin_page=_vin_page_external)
    fetcher = FakeFetcher(routes)
    mcp = build_server(fetcher=fetcher, login=_fake_login, confirm=_token_confirm)

    first = _payload(await mcp.call_tool("open_vin_with_credit", {"vin": EXTERNAL_VIN}))
    second = _payload(
        await mcp.call_tool(
            "open_vin_with_credit", {"vin": EXTERNAL_VIN, "confirm_token": first["confirm_token"]}
        )
    )
    assert second["credits_left"] == 5

    seen = len(fetcher.calls)
    reopen = _payload(await mcp.call_tool("open_vin_with_credit", {"vin": EXTERNAL_VIN}))
    assert reopen["status"] == "confirmation_required"
    assert "pravděpodobně" in reopen["message"]
    assert _no_paid_calls(fetcher.calls[seen:])


async def _open_garage_unit(routes):
    """Open the Hyundai garage flow and return (mcp, catalog_id, unit_id)."""
    fetcher = FakeFetcher(routes)
    mcp = build_server(fetcher=fetcher, login=_fake_login, confirm=_token_confirm)
    opened = _payload(await mcp.call_tool("open_garage_car", {"car": "1AB0001"}))
    cid = opened["matches"][0]["catalog_id"]
    units = _payload_list(await mcp.call_tool("get_group_parts", {"catalog_id": cid, "node_id": "10203"}))
    return mcp, cid, units[0]["unit_id"]


@pytest.mark.anyio
async def test_get_unit_reports_image_size_and_scale():
    mcp, cid, unit_id = await _open_garage_unit(_routes())
    blocks = await mcp.call_tool(
        "get_unit", {"catalog_id": cid, "unit_id": unit_id, "highlight": "25310-J7800"}
    )
    assert len(blocks) == 3
    assert isinstance(blocks[0], TextContent)
    summary = json.loads(blocks[0].text)
    assert summary["image_size"] == [800, 600]
    assert summary["scale"] == 1.0
    assert "image_note" not in summary
    assert isinstance(blocks[1], ImageContent)
    assert isinstance(blocks[2], ImageContent)


@pytest.mark.anyio
async def test_get_unit_without_image_returns_summary_with_note():
    def unit_no_image(method: str, url: str, body: object) -> Response:
        text = fixture_text("laximo/hyundai_unit_25-253.html")
        stripped, count = re.subn(r'src="https://img\.altechopersys\.com[^"]*"', 'src=""', text)
        assert count == 1
        return make_response(stripped, url=url)

    routes = [route for route in _routes() if "/cs/unit" not in route[1]]
    routes.append(("GET", "/cs/unit", unit_no_image))
    mcp, cid, unit_id = await _open_garage_unit(routes)
    blocks = await mcp.call_tool("get_unit", {"catalog_id": cid, "unit_id": unit_id})
    assert len(blocks) == 1
    assert isinstance(blocks[0], TextContent)
    summary = json.loads(blocks[0].text)
    assert summary["unit_id"] == unit_id
    assert summary["image_note"]
    assert summary["parts"]
    assert "image_size" not in summary


@pytest.mark.anyio
async def test_get_unit_with_undecodable_image_returns_summary_with_note():
    def bad_image(method: str, url: str, body: object) -> Response:
        return Response(status=200, headers={}, text="not-an-image", content=b"not-an-image", url=url)

    routes = [route for route in _routes() if "img.altechopersys" not in route[1]]
    routes.append(("GET", "img.altechopersys.com", bad_image))
    mcp, cid, unit_id = await _open_garage_unit(routes)
    blocks = await mcp.call_tool(
        "get_unit", {"catalog_id": cid, "unit_id": unit_id, "highlight": "25310-J7800"}
    )
    assert len(blocks) == 1
    assert isinstance(blocks[0], TextContent)
    summary = json.loads(blocks[0].text)
    assert summary["unit_id"] == unit_id
    assert summary["image_note"]
    assert summary["parts"]
    assert "image_size" not in summary
