"""Tests for diagram image preparation and highlighting (images.py)."""

from __future__ import annotations

from io import BytesIO

from conftest import fixture_text
from PIL import Image

from autokelly_mcp.images import annotate, crop_around, find_callouts, prepare
from autokelly_mcp.models import Callout
from autokelly_mcp.parsers.laximo import parse_unit


def make_white_png(width: int = 2000, height: int = 1200) -> bytes:
    img = Image.new("RGB", (width, height), (255, 255, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def open_png(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data))


def test_prepare_downscales_longest_side():
    img = open_png(prepare(make_white_png(2000, 1200)))
    assert (img.width, img.height) == (1600, 960)
    assert img.mode == "RGB"
    assert img.format == "PNG"


def test_find_callouts_by_oem_radiator():
    detail = parse_unit(fixture_text("laximo/hyundai_unit_25-253.html"))
    hits = find_callouts(detail, "25310-J7800")
    assert len(hits) >= 1
    assert {c.code for c in hits} == {"25310"}


def test_find_callouts_by_oem_repeated_callout():
    detail = parse_unit(fixture_text("laximo/hyundai_unit_25-253.html"))
    hits = find_callouts(detail, "14720-22006S")
    assert len(hits) >= 1
    assert {c.code for c in hits} == {"14720A"}


def test_find_callouts_no_match():
    detail = parse_unit(fixture_text("laximo/hyundai_unit_25-253.html"))
    assert find_callouts(detail, "nope") == []


def test_annotate_draws_red_box():
    img = open_png(annotate(make_white_png(), [Callout("X", 100, 100, 50, 20)]))
    assert img.getpixel((97, 97)) == (255, 0, 0)
    assert img.getpixel((500, 500)) == (255, 255, 255)


def test_crop_around_bounds_result_size():
    callouts = [Callout("X", 100, 100, 50, 20)]
    margin = 250
    img = open_png(crop_around(make_white_png(), callouts, margin=margin))
    assert img.width <= 50 + 2 * margin
    assert img.height <= 20 + 2 * margin
