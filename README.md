# autokelly-mcp

A local, read-only MCP server for [autokelly.cz](https://www.autokelly.cz),
shipped as a Claude Code plugin together with the `autokelly-parts` and
`compare-part-prices` skills.
Talk to the agent in Czech — e.g. "Najdi mi chladič motoru a gumové uložení"
— and it walks the Autokelly VIN catalogs for you: both the tree catalog
("Podle skupin") and the picture catalog ("Podle obrázků"), checks the
diagram callouts, and comes back with OEM numbers plus Autokelly's offers
(manufacturer, price incl. VAT, stock).

Read-only means read-only: the server never touches the cart, never places
orders, and never changes the garage.

## Install in Claude Code

The repository stays local for now (no GitHub remote yet). Install from this
folder via a local marketplace:

```text
/plugin marketplace add /path/to/autokelly-mcp
/plugin install autokelly-mcp@autokelly-local
```

Then run `/mcp`. The `autokelly` server should show as connected with
11 tools.

## Standalone (without Claude Code)

The plugin runs the server with `uvx` straight from the plugin directory:

```sh
uvx --from /path/to/autokelly-mcp autokelly-mcp
```

## Login

The first tool call that needs auth opens installed Google Chrome in a
visible window — log in to autokelly.cz there (about 5 minutes to finish).
If Chrome is missing, install Playwright's Chromium once and the login
falls back to it:

```sh
uvx --from /path/to/autokelly-mcp playwright install chromium
```

The session (cookies, User-Agent, cached search guid) lives in
`~/.autokelly-mcp/session.json` (file mode `0600`, never inside the repo).
To log out, delete it:

```sh
rm ~/.autokelly-mcp/session.json
```

## Price comparison

The `compare-part-prices` skill compares one or more OEM numbers across
Autokelly and three other shops: imdily.cz, autodily-pema.cz and granex.cz.
Ask e.g. "Porovnej ceny 25310-J7800". The parts skill also offers it once
it has found OEM numbers.

- **Autokelly** prices come from the MCP server (`search_autokelly_by_oem`).
- **imdily, Pema and Granex** are read in *your own Chrome*. In Claude Code
  that's Claude in Chrome; elsewhere it's the Codex Chrome extension or Chrome
  DevTools MCP attached to your Chrome. All three shops sit behind a
  Cloudflare check that blocks plain HTTP requests. Pema and Granex also ask
  robots not to use their search. So the MCP server never contacts them. The
  agent opens one tab, visits
  `https://<shop>/vyhledavani?search=<OEM>` on each shop, reads the results
  with `skills/compare-part-prices/extract-offers.js`, and closes the tab.
  - It never clicks through a security check.
  - If a shop can't be read (security check, the extension refusing the site,
    or no browser tool at all), you get its search link instead.
- **Brand list:** `~/.autokelly-mcp/znacky.md` holds the brands you avoid and
  the ones you trust. It lives outside the plugin so updates don't overwrite
  it. Edit it directly, or tell the agent ("Starline nechci"). Brands not on
  the list get the agent's own opinion, labelled as such.
- **The answer:** one brand × shop table with prices incl. VAT and
  availability. The recommendation is the cheapest available offer from a
  trusted brand, with the cheapest overall mentioned alongside. Offers whose
  listed dimensions don't match the rest are flagged: shops' cross-references
  sometimes include a different part.

The extraction script's tests (`tests/test_extract_offers.py`) run it in
headless Chrome against saved pages. Chromium can't start inside the macOS
sandbox, so there they are skipped. Run them outside the sandbox to execute
them.

## VIN credits

- Cars saved in your Autokelly garage open through the free route
  (`open_garage_car`): no credit is spent.
- A VIN outside the garage costs 1 of your N VIN credits
  (`open_vin_with_credit`). The agent must warn you first and wait for an
  explicit yes, and the server itself asks again (MCP elicitation where the
  client supports it, otherwise a one-time `confirm_token` tied to that VIN,
  valid for about 10 minutes). Because confirmation is server-side, don't
  put `open_vin_with_credit` on an "always-allow" list — that would bypass
  the credit check.

## Paid route findings

Live test on 2026-11-10 with a Suzuki Swift VIN outside the garage
(balance 5 credits, confirmed through real MCP elicitation):

- The first `open_vin_with_credit` (2 vehicle matches, TYPE 3 and TYPE 4)
  deducted one credit (`credits_left` 4).
- Opening the same VIN again a few minutes later in the same login
  session, confirmed again, deducted nothing (`credits_left` 4, confirmed
  by a separate `account_status`).
- Which single call deducts the credit could not be isolated: the full
  sequence (`verify-usage-vin` → VIN page → catalog entry → `/decoded`
  with `decodedFromGarage: false` → credit) charged once, and repeating
  it shortly after did not charge again. Whether a re-open stays free
  after a longer time or in a new login session is unknown.
- The garage route (`open_garage_car`) spent no credits.

The server still asks for confirmation before every paid open. When a VIN
already opened through the paid route in this server session is opened
again, the confirmation notes that the re-open likely needs no further
credit — observed free only within minutes in one login session.
