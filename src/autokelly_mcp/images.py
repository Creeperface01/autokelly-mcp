"""Diagram image helpers: downscale, find callouts, annotate, crop.

Pure module: bytes in, bytes out. No I/O, no logging.
"""

from __future__ import annotations

import re
from io import BytesIO

from PIL import Image, ImageDraw

from autokelly_mcp.models import Callout, UnitDetail

MAX_SIDE = 1600

_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def _normalise_oem(value: str) -> str:
    return _NON_ALNUM.sub("", value.upper())


def _to_png(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def prepare(png_or_gif: bytes) -> bytes:
    """Return PNG RGB bytes with the longest side at most MAX_SIDE."""
    img = Image.open(BytesIO(png_or_gif)).convert("RGB")
    if max(img.width, img.height) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    return _to_png(img)


def find_callouts(detail: UnitDetail, key: str) -> list[Callout]:
    """Find callouts for a callout code or an OEM number."""
    stripped = key.strip()
    if not stripped:
        return []
    lowered = stripped.lower()
    exact = [c for c in detail.callouts if c.code.lower() == lowered]
    if exact:
        return exact
    wanted = _normalise_oem(stripped)
    codes = {p.callout for p in detail.parts if p.callout and _normalise_oem(p.oem) == wanted}
    if not codes:
        return []
    return [c for c in detail.callouts if c.code in codes]


def annotate(img: bytes, callouts: list[Callout]) -> bytes:
    """Draw a red 4 px rectangle, padded by 6 px, around each callout."""
    canvas = Image.open(BytesIO(img)).convert("RGB")
    if not callouts:
        return _to_png(canvas)
    draw = ImageDraw.Draw(canvas)
    for c in callouts:
        draw.rectangle(
            [c.left - 6, c.top - 6, c.left + c.width + 6, c.top + c.height + 6],
            outline=(255, 0, 0),
            width=4,
        )
    return _to_png(canvas)


def crop_around(img: bytes, callouts: list[Callout], margin: int = 250) -> bytes:
    """Crop to the callouts' bounding box expanded by margin, clamped to the image."""
    if not callouts:
        raise ValueError("callouts must not be empty")
    canvas = Image.open(BytesIO(img)).convert("RGB")
    left = min(c.left for c in callouts) - margin
    top = min(c.top for c in callouts) - margin
    right = max(c.left + c.width for c in callouts) + margin
    bottom = max(c.top + c.height for c in callouts) + margin
    box = (max(left, 0), max(top, 0), min(right, canvas.width), min(bottom, canvas.height))
    return _to_png(canvas.crop(box))
