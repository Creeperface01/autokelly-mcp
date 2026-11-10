"""Opt-in live smoke test against the real site (needs the user to log in).

Run with ``AUTOKELLY_LIVE=1 uv run pytest tests/live -v -s``. The default
``uv run pytest`` run ignores this directory (see ``addopts`` in pyproject).
"""

from __future__ import annotations

import json
import os

import pytest
from mcp.types import ImageContent, TextContent

from autokelly_mcp.server import build_server

pytestmark = pytest.mark.skipif(os.environ.get("AUTOKELLY_LIVE") != "1", reason="live")


def _payload(blocks):
    assert isinstance(blocks[0], TextContent)
    return json.loads(blocks[0].text)


def _payload_list(blocks):
    return [json.loads(block.text) for block in blocks if isinstance(block, TextContent)]


@pytest.mark.anyio
async def test_live_smoke():
    # This test only drives the free garage route. It never calls
    # open_vin_with_credit, so no VIN credit can be spent.
    mcp = build_server()

    first = _payload(await mcp.call_tool("account_status", {}))
    assert first["credits"] >= 0

    cars = _payload_list(await mcp.call_tool("list_garage_cars", {}))
    assert len(cars) == 2
    hyundai = next(car for car in cars if car["name"].startswith("HYUNDAI"))
    alfa = next(car for car in cars if car["name"].startswith("ALFA"))

    opened_hyundai = _payload(await mcp.call_tool("open_garage_car", {"car": hyundai["plate"]}))
    assert opened_hyundai["route"] == "garage"
    hyundai_catalog = opened_hyundai["matches"][0]["catalog_id"]

    found = _payload_list(
        await mcp.call_tool("search_tree", {"catalog_id": hyundai_catalog, "query": "chladic vody"})
    )
    assert found
    units = _payload_list(
        await mcp.call_tool(
            "get_group_parts", {"catalog_id": hyundai_catalog, "node_id": found[0]["id"]}
        )
    )
    assert units
    hyundai_unit = units[0]["unit_id"]
    blocks = await mcp.call_tool(
        "get_unit",
        {"catalog_id": hyundai_catalog, "unit_id": hyundai_unit, "highlight": "25310-J7800"},
    )
    assert len(blocks) == 3
    assert isinstance(blocks[0], TextContent)
    assert isinstance(blocks[1], ImageContent)
    assert isinstance(blocks[2], ImageContent)
    assert json.loads(blocks[0].text)["unit_id"] == hyundai_unit

    offers = _payload_list(
        await mcp.call_tool("search_autokelly_by_oem", {"oem": "25310-J7800"})
    )
    assert len(offers) >= 1

    opened_alfa = _payload(await mcp.call_tool("open_garage_car", {"car": alfa["plate"]}))
    assert opened_alfa["route"] == "garage"
    assert len(opened_alfa["matches"]) == 2
    lhd = next(m for m in opened_alfa["matches"] if m["params"].get("Pohon") == "LHD")
    alfa_catalog = lhd["catalog_id"]

    found_alfa = _payload_list(
        await mcp.call_tool("search_tree", {"catalog_id": alfa_catalog, "query": "chladic vody"})
    )
    assert found_alfa
    units_alfa = _payload_list(
        await mcp.call_tool(
            "get_group_parts", {"catalog_id": alfa_catalog, "node_id": found_alfa[0]["id"]}
        )
    )
    assert units_alfa
    blocks_alfa = await mcp.call_tool(
        "get_unit", {"catalog_id": alfa_catalog, "unit_id": units_alfa[0]["unit_id"]}
    )
    assert isinstance(blocks_alfa[0], TextContent)
    assert isinstance(blocks_alfa[1], ImageContent)

    last = _payload(await mcp.call_tool("account_status", {}))
    assert last["credits"] == first["credits"]
