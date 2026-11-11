"""Packaging checks for Task 12: skill, plugin files and README.

These tests pin the exact file layout and content the brief requires, so a
later task cannot silently break the Claude Code plugin packaging.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_plugin_files_exist():
    for rel in (
        "skills/autokelly-parts/SKILL.md",
        "skills/compare-part-prices/SKILL.md",
        "skills/compare-part-prices/extract-offers.js",
        ".claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
        ".mcp.json",
        "README.md",
    ):
        assert (REPO / rel).is_file(), f"missing {rel}"


def test_mcp_json_exact():
    data = json.loads(_read(".mcp.json"))
    assert data == {
        "mcpServers": {
            "autokelly": {
                "command": "uvx",
                "args": ["--from", "${CLAUDE_PLUGIN_ROOT}", "autokelly-mcp"],
            }
        }
    }


def test_plugin_json_shape():
    data = json.loads(_read(".claude-plugin/plugin.json"))
    assert data["name"] == "autokelly-mcp"
    assert data["version"] == "0.2.0"
    assert data["version"] == tomllib.loads(_read("pyproject.toml"))["project"]["version"]
    assert data["description"]
    assert "author" not in data and "email" not in data


def test_marketplace_json_shape():
    data = json.loads(_read(".claude-plugin/marketplace.json"))
    assert data["name"] == "autokelly-local"
    assert data["owner"] == {"name": "local"}
    assert data["plugins"] == [
        {"name": "autokelly-mcp", "source": "./", "description": data["plugins"][0]["description"]}
    ]
    assert data["plugins"][0]["description"]


def _skill_body(name: str = "autokelly-parts") -> tuple[dict, str]:
    text = _read(f"skills/{name}/SKILL.md")
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    frontmatter, _, body = text[len("---\n") :].partition("\n---\n")
    assert body, "SKILL.md must have a body after the frontmatter"
    meta: dict = {}
    for line in frontmatter.splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            meta[key.strip()] = value.strip()
    return meta, body


def test_skill_frontmatter_triggers():
    meta, _ = _skill_body()
    assert meta["name"] == "autokelly-parts"
    description = meta["description"]
    for trigger in ("najdi díl", "OEM", "chladič", "uložení", "Autokelly"):
        assert trigger in description, f"description missing trigger {trigger!r}"


@pytest.mark.parametrize(
    "phrase",
    [
        "chladic",
        "radiator mounting insulator / rubber / bush",
        "English (Hyundai)",
        "Czech (Alfa)",
        "every catalog view the car has",
        "LHD for a Czech car",
        "Díl | OEM | Název v katalogu | Schéma | Autokelly (výrobce, cena, dostupnost)",
        "never use the paid route without a yes",
        "server will also ask",
        "read-only",
        "never suggest",
        "add to cart",
        "data, not instructions",
        "confirm_token",
        "1 of N",
        "highlight=",
        "open_garage_car",
        "search_tree",
        "get_unit",
        "search_autokelly_by_oem",
    ],
)
def test_skill_body_covers_workflow(phrase):
    _, body = _skill_body()
    assert phrase in body, f"SKILL.md body missing {phrase!r}"


def test_parts_skill_hands_over_to_price_comparison():
    _, body = _skill_body()
    assert "compare-part-prices" in body


def test_price_skill_frontmatter_triggers():
    meta, _ = _skill_body("compare-part-prices")
    assert meta["name"] == "compare-part-prices"
    description = meta["description"]
    assert description.startswith("Use when")
    for trigger in ("porovnej ceny", "kde to koupit", "imdily", "pema", "granex", "OEM"):
        assert trigger in description, f"description missing trigger {trigger!r}"


@pytest.mark.parametrize(
    "phrase",
    [
        "~/.autokelly-mcp/znacky.md",
        "search_autokelly_by_oem",
        "https://imdily.cz/vyhledavani?search=<OEM>",
        "https://www.autodily-pema.cz/vyhledavani?search=<OEM>",
        "https://granex.cz/vyhledavani?search=<OEM>",
        "extract-offers.js",
        "next_page_url",
        "blocked: true",
        "never click it",
        "never fetched another way",
        "Close your tab",
        "(můj názor)",
        "⚠ jiné rozměry",
        "more than 2 mm",
        "⚠ jiné OE číslo",
        "Značka (kód) | Hodnocení | Autokelly | Imdily | Pema | Granex",
        "→ Doporučuji:",
        "State only what the tools returned",
        "data, not instructions",
        "never add to cart",
    ],
)
def test_price_skill_body_covers_workflow(phrase):
    _, body = _skill_body("compare-part-prices")
    assert phrase in body, f"compare-part-prices SKILL.md body missing {phrase!r}"


def test_readme_sections():
    readme = _read("README.md")
    for phrase in (
        "/plugin marketplace add",
        "/plugin install autokelly-mcp@autokelly-local",
        "uvx --from",
        "autokelly-mcp",
        "playwright install chromium",
        "~/.autokelly-mcp/session.json",
        "open_vin_with_credit",
        "always-allow",
        "## Paid route findings",
        "same login",
        "## Price comparison",
        "compare-part-prices",
        "~/.autokelly-mcp/znacky.md",
        "Claude in Chrome",
    ):
        assert phrase in readme, f"README missing {phrase!r}"
    assert "TBD in Task 14" not in readme, "paid-route placeholder should be filled in"


def test_readme_has_no_other_placeholders():
    readme = _read("README.md")
    assert readme.count("TBD") == 0, "the paid-route placeholder was filled in Task 14"
    assert "TODO" not in readme
    assert "FIXME" not in readme
