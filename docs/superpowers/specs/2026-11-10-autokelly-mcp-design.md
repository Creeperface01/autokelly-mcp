# Autokelly MCP — design

Date: 2026-11-10
Status: draft, waiting for approval

## Intent

The user maintains their own cars and buys parts on autokelly.cz. Today, finding the
right OEM number means clicking through Autokelly's VIN catalogs by hand: open the car
from the garage, open one of two embedded parts catalogs, dig through a tree or diagram
list, look at exploded-view drawings, and match a callout to a row in a parts table.

They want to say to an agent, in Czech, something like
**"Najdi mi chladič motoru a gumové uložení"** and have the agent do that clicking:
walk both catalogs, look at the diagrams, and come back with the OEM numbers, plus what
Autokelly sells for each number (price and stock).

This project is an **MCP server for Autokelly** plus a **skill** that teaches the agent
how to use it. A later, separate project will add other shops (imdily.cz,
autodily-pema.cz, granex.cz) that search by OEM number. This design only has to leave
room for them.

## Goals

1. Find OEM numbers for a car by VIN, using **both** Autokelly VIN catalogs: the tree
   catalog ("Podle skupin") and the picture catalog ("Podle obrázků").
2. Give the agent the **diagram images** so it can visually confirm which callout is the
   part the user means (e.g. which rubber piece is the radiator mount).
3. For an OEM number, return **Autokelly's offers**: product, manufacturer, the user's
   price incl. VAT, and stock/availability.
4. **Two separate routes to a catalog:**
   - a car saved in the user's Autokelly garage (free);
   - any other VIN (uses one of the user's paid VIN credits; the agent must warn and get
     an explicit yes first).
5. **Login once in a real browser**, then do everything with plain HTTP requests that
   look like a normal Chrome session. The browser is used only to log in.
6. Ship as a **Claude Code plugin** (MCP server and skill together), runnable with
   **`uvx` straight from GitHub**.
7. Structure the "search by OEM" part so more shops can be added later without
   reworking the server.

## Non-goals (for this version)

- Other shops (imdily, PEMA, Granex). They come next, in their own design.
- Anything that writes to the account: cart, orders, garage changes, parking cars. **The
  MCP is strictly read-only.**
- Multi-user hosting. It runs locally for one person on their Mac.
- A UI of its own. The agent and the skill are the UI.

## Anti-goals (would be a failure even if it "works")

- **Spending a VIN credit without the user's explicit confirmation.**
- **Getting around the credit system**, e.g. calling the catalog server directly for a
  VIN outside the garage without going through Autokelly's credit check and its
  "decoded" call. Non-garage lookups must follow the same calls the website makes.
- **Getting the account flagged or blocked**: request bursts, parallel crawling, or
  scraping whole catalogs "just in case". Fetch only what the current question needs.
- Touching the cart. Note: the website's own "Zakoupit díly dle VIN" button creates and
  binds a cart (`/Cart/Add/`, `/Cart/{id}/ParkedCar/{id}/bind`). The MCP must not make
  these calls. It loads the catalog page directly instead (verified to work, see below).
- Leaking personal data: cookies in logs, or the user's name, email or customer number
  in committed test fixtures.

## Decisions already made (by the user)

- **Language and runtime: Python, run with `uvx`** from a GitHub repo.
- **Read-only.**
- **Both routes (garage car and any VIN) as separate tools.** The any-VIN route warns
  the user before it spends a credit.
- **A skill ships with the MCP** and tells the agent how to use it.
- The user will talk to the agent **in Czech**.
- Login happens in a browser the MCP opens when the user isn't logged in. The cookies are
  stored and reused. Everything after login is plain requests with legitimate
  browser-like headers.
- **The build may spend up to 2 of the user's VIN credits** to test the paid route end
  to end, including whether re-opening the same VIN charges again. Ask the user for the
  test VIN (one not in the garage) at that point. Spend nothing beyond those 2.
- **The repository stays local for now**; there is no GitHub remote yet.
- **Commit messages carry no Jira key** in this repo. Use the user's usual shape without
  the key: `Feature - <message>` / `Hotfix - <message>`. No Claude co-author or
  attribution lines, per the user's global rules.

## Calls made by Claude (the user can override)

- **HTTP client: `curl_cffi`** with Chrome impersonation (TLS and HTTP/2 fingerprint),
  plus a full Chrome header set. Chosen because it survives if Autokelly tightens its
  ShieldSquare bot protection. Plain clients pass today (see findings).
- **MCP SDK:** the official Python `mcp` package (FastMCP).
- **Login browser:** Playwright using the **installed Google Chrome**
  (`channel="chrome"`), so nothing has to be downloaded. Fall back to Playwright's
  Chromium if Chrome is missing.
- **HTML parsing:** a lightweight parser (selectolax or BeautifulSoup; builder's
  choice).
- **Images:** Pillow, to downscale diagrams and draw a box around a requested callout.
- **Cookie store:** `~/.autokelly-mcp/session.json`, file mode `0600`, never inside the
  repo. Store the User-Agent captured at login next to the cookies and send that same UA
  afterwards.
- **Login trigger:** any tool that needs auth and finds no valid session opens the login
  window itself, waits up to about 5 minutes for the user to finish, saves the cookies
  and continues. There is also an explicit login/status tool.
- **Request pacing:** one request at a time per host, with a small randomized delay
  (about 300–800 ms) between requests. No parallel fan-out.
- **Packaging:** a Claude Code plugin (`.claude-plugin/plugin.json`) containing the skill.
  Its MCP config runs `uvx --from ${CLAUDE_PLUGIN_ROOT} autokelly-mcp`, so the same
  config works from the local folder now and from GitHub later, with no hard-coded URL.
  The README also documents the standalone forms: `uvx --from <local path> autokelly-mcp`
  now, and `uvx --from git+https://github.com/<owner>/autokelly-mcp autokelly-mcp` once
  there is a remote. Install locally for Claude Code through a local plugin marketplace
  or `--plugin-dir`; builder's choice, document it.
- **Supported cars:** v1 must work for **both cars in the user's garage** (Hyundai i30,
  Alfa Romeo 147), and generally for any car whose Autokelly VIN page shows the Laximo
  catalog. If a car has no VIN catalog, or its catalog pages have a layout the parsers
  don't recognise, the tool says so clearly ("not supported for this car") instead of
  guessing. Falling back to Autokelly's TecDoc catalog is **out of scope** for v1.
  Not every brand is guaranteed to have both views. "Search both catalogs" means "use
  every view the car has".
- **Several vehicle matches per VIN:** handled explicitly (see the Alfa finding below).
- **OEM search works on its own**, without an open catalog. The user may paste an OEM
  number, and the later shop comparison needs it. How to get there depends on what the
  builder finds out about `searchGuid`, in this order of preference:
  (1) if the guid is stable per user, read it once from any VIN page and cache it on
  disk next to the cookies;
  (2) otherwise, use Autokelly's ordinary site search, after checking that it returns
  the same products for an OEM number;
  (3) as a last resort, GET a **garage** car's VIN page just to read a fresh guid. That is
  free, and it must not call `/decoded`.
  The `search_autokelly_by_oem(oem)` signature stays OEM-only either way.
- **Credit confirmation is enforced by the server, not only by the skill.** The paid tool
  uses **MCP elicitation** where the client supports it: the server itself asks the user
  "Použít 1 z N VIN kreditů na VIN …?" and proceeds only on an explicit yes. Where
  elicitation isn't available, it falls back to two steps with a one-time token: the
  warning call returns a token tied to that VIN, valid for about 10 minutes, and the
  confirm call must send it back. The README tells the user not to put this tool on an
  "always allow" permission list.
- **Future shops live in this same server** (agreed in conversation). The package and
  plugin keep the name `autokelly-mcp`.
- **Scrub list for fixtures** also covers VINs, licence plates and garage car ids, not
  only name, email and customer number.

## What the site actually does (recon, 2026-11-10)

Recon was done in a Playwright browser logged into the user's account. The garage had
two cars: Hyundai i30 combi (PDE) 1.5 T-GDI, VIN `TMAH…`, and Alfa Romeo
147.

### www.autokelly.cz (ASP.NET + AngularJS)

**Auth cookies** (all on `www.autokelly.cz`): `PersistentLogon_www_autokelly_cz` (about
1 year), `LKQEshop` (about 1 year), `ASP.NET_SessionId` (session),
`__RequestVerificationToken`, and the ShieldSquare cookies `__uzma`, `__uzmb`,
`__uzmc`, `__uzmd`, `__uzme` and the `__uzm*j0` variants. The consent cookie
`OptanonConsent` is on `.autokelly.cz`.

**Logged-out signal:** `/Garage/CarList` redirects to `/page/MojeGaraz`, and the header
shows "Přihlášení". The builder should pick a reliable programmatic check, e.g. what
`POST /Garage/Cars/1` returns when logged out (not yet observed).

**Bot protection: ShieldSquare (Radware).** Responses carry `shieldsquare-response: 0`
(allowed). Some XHRs from the site's own JS also send a `uzlc` header (a ShieldSquare
token), e.g. on `/decoded`. **Test:** requests from a non-browser HTTP stack (Node),
carrying the session cookies, succeeded both with a Chrome UA and with UA `node`, and
were not challenged. So the protection is currently permissive. Even so, send realistic
headers, and treat a non-JSON reply, a challenge page, or `shieldsquare-response` ≠ 0 as
"blocked". On block, stop, tell the user, and offer to re-open the login browser, which
refreshes the ShieldSquare cookies. Never retry in a loop.

Headers the site's XHRs send: Chrome 157 macOS UA, `sec-ch-ua*`,
`accept: application/json, text/plain, */*`,
`content-type: application/json;charset=UTF-8` (for JSON POSTs), and `referer` set to the
page the call belongs to.

**Garage:**
- `POST /Garage/Cars/{page}` (page 1, size 20) returns
  `{Paging:{Page,Size,Total,TotalCount}, Items:[{Id, Name, VIN, LicencePlate, KW, HP, CCM, Fuel, CatalogLink, CPath, HasTecDocId, ...}]}`.

**VIN credits:**
- `POST /vin-decoder/credit` returns
  `{data:{Credit:5, VinCreditMessage:"Počet VIN kreditů: 5", HasUnlimitedAccess:false}}`.
- Opening a **garage** car's catalog did **not** change the credit count (5 before, 5
  after).

**Garage-car catalog route (free):**
- `GET /catalog/graphic/VIN/{VIN}/garage` returns HTML that contains
  `<iframe id="laximoFrame" src="https://vinsearch.autokelly.cz/cs/search/vin/{VIN}?domain=https://www.autokelly.cz&blank=0&cc=AK_CZ&cn={customerNumber}&searchurl=https%3a%2f%2fwww.autokelly.cz%2fsearch%2foem%2f{searchGuid}%2f_OEM_">`.
  A plain request to this URL (no cart calls first) returned 200 with the iframe.
- After the iframe decodes the VIN, the website calls
  `POST /catalog/graphic/vin/{VIN}/decoded` with body `{"decodedFromGarage": true}`,
  which returns `true`. The MCP should make the same call, to stay faithful to the site.

**Any-VIN route (uses a credit). Taken from the site's JS bundle (`AK.Search2`,
`AK.Catalog.getVinDecoder2`, `AK.GraphicCatalog`); not exercised, to avoid spending a
credit:**
1. `POST /vin-decoder/verify-usage-vin` with body
   `{"vin": "...", "fromGarage": false}` returns
   `{data:{CanBeUsed: bool, ReasonMessage: string}}`. If `CanBeUsed` is false, show
   `ReasonMessage` and stop.
2. `GET /catalog/graphic/VIN/{VIN}` (no `/garage` suffix) gives the page with the
   iframe.
3. Once the catalog has decoded the VIN: `POST /catalog/graphic/vin/{VIN}/decoded` with
   `{"decodedFromGarage": false}`.
4. `POST /vin-decoder/credit` to report the new balance.

Which step actually deducts the credit is **unverified**. The MCP must do all of these
steps, in this order, and only after the user has confirmed.

**OEM search (Autokelly offers):**
- Page: `GET /search/oem/{searchGuid}/{OEM_without_dashes}`, e.g. `.../25310J7800`. The
  catalog links to it through the `searchurl` template above, replacing `_OEM_`.
- `POST /ProductList/Items/GraphicsCatalogOem/1` returns
  `{Items:[{Id, Text, Description(HTML with attributes), IsFake, Attributes, ...}], Paging, ...}`.
  The request had no body. It probably depends on server-side state set by the page GET
  (unverified).
- `POST /UserPrice/Data` with `{"productIds": ["13089926", ...]}` returns
  `{Content:[{ProductId, PriceVat:"5 239 Kč", Price, Discount, OriginalPrice, BonusPrice*...}]}`.
  These are the user's own prices.
- `POST /ProductStock/Data` returns
  `{items:[{productId, storages:[{Abbrev:"OSPO", Text:"Ostrava-Poruba", Stock:"0", ...}, {Abbrev:"CS"...}, {Abbrev:"Jiné", Stock:"do 48h"...}]}]}`.
- Also seen: `POST /ProductDisponibility/data`, `/UserPrice/WithoutDeposit/Data`,
  `/ProductList/Filter/Brands/GraphicsCatalogOem`, `/ProductList/Attributes`. Request
  bodies for the stock and disponibility calls were not captured; the builder should
  check them.
- Example result for `25310J7800`: Chladič vody NISSENS 5 239 Kč, KIA original
  12 943 Kč, Hyundai original 13 150 Kč. Stock at OSPO 0; "Jiné" do 48h.
- **Unverified:** what `searchGuid` is (per user? per session?). Always take it from the
  iframe `src` of the current catalog page, never invent or reuse one.

### vinsearch.autokelly.cz (Laximo "Guayaquil" catalog, PHP/Symfony)

- **No ShieldSquare.** Session = `PHPSESSID` cookie plus a `session=` query parameter
  (e.g. `session=6af30dee3a9f2`) that the server appends to every link it renders.
- All navigation uses **opaque tokens** (long base64url-like strings) in paths and form
  fields. Scrape them from the HTML; never build them yourself.
- **Entry:** GET the iframe `src`. You get a vehicle table (model, date, engine no.,
  options, colour…) and two links:
  - "Podle skupin" (tree): `/cs/catalog/group-list/{tokenA}/{tokenB}?session=…`
  - "Podle obrázků" (pictures): `/cs/catalog/category-list/{token}?session=…`

**Several vehicles per VIN (seen on the Alfa Romeo 147, VIN `ZAR…`):** the entry page
lists **more than one vehicle block**. Each block has its own heading (e.g.
`ALFA ROMEO 147 [147 BZ/DS (2000-2010)]`), its own parameter table and its own pair of
links ("Stromový katalog" → `group-list/…`, "Obrázkový katalog" → `category-list/…`).
For the Alfa the two blocks were identical except `Pohon: LHD` vs `Pohon: RHD`.
The parameter tables also differ by brand: the Alfa has MVS, MVS popis, Motor,
Varianta, Dveře, Pohon; the Hyundai has Model, Výbava, Trh, Engine no., Color. The
Hyundai's entry page showed a single block with the two catalog buttons.
→ `open_garage_car` / `open_vin_with_credit` return **all** matches with their
parameters. When there is more than one, the skill picks the one that clearly fits
(e.g. LHD for a Czech car) or asks the user. The catalog tools then take the chosen
match. Parsers must treat the parameter table as generic key/value pairs.

**Tree catalog** (`group-list`):
- The **whole tree is embedded as JSON** in the jstree init script:
  `'data' : [{"id":"10107","text":"Chlazeni","state":{...},"children":[...],"token":...}]`.
  It has 28 top-level groups (Karoserie, Motor, Filtr, Remeny, …, Chlazeni, …,
  Kola/pneu). The names are Czech, **mostly without diacritics**. Leaves carry a `token`.
  Example path: Chlazeni → Chladic voda/ olej → Chladic vody.
- Opening a leaf: `POST /cs/catalog/group-part-list?session=…`, form field
  `token=<leaf token>`. It returns an HTML fragment with one block per diagram ("unit"):
  - a category heading (e.g. `ENGINE`);
  - a thumbnail `https://img.altechopersys.com/…/200/…gif?s=…&k=…` and a full image
    `…/source/…gif?s=…&k=…`;
  - a unit link `/cs/unit?token=…&session=…` titled e.g.
    `25-253: ENGINE COOLING SYSTEM`;
  - a table of the matching part(s) (e.g. `25310-J7800 RADIATOR ASSY`), each with an
    Autokelly search link
    (`onclick="window.parent.location.href='https://www.autokelly.cz/search/oem/{guid}/25310J7800'"`);
  - "Ostatní náhradní díly": the other parts on that diagram, OEM number and English
    name, e.g. `25343-F2000 RUBBER INSULATION`,
    `25336-F2000 INSULATOR - RADIATOR MOUNTING, LOWER`, `25333-S0000 BRACKET ASSY …`.
  - The same unit can appear several times (variants or repeated images). Deduplicate.

**Picture catalog** (`category-list`):
- Top categories: ENGINE, TRANSMISSION, CHASSIS, BODY, TRIM, ELECTRICAL (a jstree with
  tokens).
- Selecting one: `POST /cs/catalog/category-unit-list?session=…`, form field `token=…`.
  You get a list of units, each with a code, an English name, a thumbnail and a unit
  link, e.g. `25-253 ENGINE COOLING SYSTEM`, `20-216B ENGINE & TRANSAXLE MOUNTING`,
  `28-286B MUFFLER & EXHAUST PIPE`.

**Unit (diagram) page, shared by both catalogs:** `GET /cs/unit?token=…&session=…`
- Full-size image (`…/source/…`).
- Callouts:
  `<div name="{calloutCode}" class="dragger g_highlight" owidth oheight oleft otop>`.
  These give **positions in original image pixels**. A code can appear more than once.
- Parts table:
  `<tr class="g_highlight…" name="{calloutCode}">` with columns č. (callout code, e.g.
  `1125AD`), an info box (Název, OEM, Date_range e.g. `24.10.2019 - ...`), Název, OEM,
  Poznámka, Modely, and an Autokelly search link.
- Part names are **English** (manufacturer data). Tree group names are Czech.

**Images:** `img.altechopersys.com` URLs are signed (`s`, `k`). Unverified: whether they
need cookies or a referer. Use the vinsearch page as referer to be safe.

## Shape of the server

### Tools

Names are illustrative; the builder decides final naming. Every tool returns compact,
structured data. Large HTML never goes to the agent.

| Tool | Purpose |
|---|---|
| `account_status` | Logged in? Customer name, VIN credits left. Opens the login window if there is no valid session. |
| `login` | Explicitly (re)open the login browser and save cookies. |
| `list_garage_cars` | Cars from the garage: id, name, VIN, plate, engine. |
| `open_garage_car(car)` | Free route. Accepts car id, VIN or plate. Opens the catalog session and returns a `catalog_id` handle, the vehicle info table, the tree's top level and the picture categories. |
| `open_vin_with_credit(vin, confirm_token=None)` | Paid route. Before anything else it checks whether the VIN is in the garage; if it is, it says so and points to the free route. Otherwise it gets the user's yes **through the server**: MCP elicitation, or else the two-step one-time token (see "Calls made by Claude"). Only then does it run the website's verify → page → decoded → credit sequence. It returns the same as `open_garage_car`, plus the new credit balance. |
| `search_tree(catalog_id, query)` | Search tree node names (case- and diacritics-insensitive, substring/fuzzy). Returns matching nodes with their full path and node ids. |
| `browse_tree(catalog_id, node_id?)` | Children of a node, for browsing when search misses. |
| `get_group_parts(catalog_id, node_id)` | For a tree leaf: units (diagram ids, names), the matched part rows and the "other parts" list, each with OEM number and name. |
| `list_picture_units(catalog_id, category)` | For a picture-catalog category: unit codes and names. |
| `get_unit(catalog_id, unit_id, highlight=None)` | The diagram: **image content** (downscaled to a sensible size), the callout list with positions, and the parts table. `highlight` takes a callout code or OEM number and returns an extra image with that callout boxed, or a crop around it. |
| `search_autokelly_by_oem(oem)` | Autokelly offers: product id, name, manufacturer, price incl. VAT, stock per location, availability text, product URL. Accepts OEM numbers with or without dashes. |

Catalog handles (`catalog_id`) map to the vinsearch session, the scraped tokens and the
`searchGuid` for that car. They live in memory. If vinsearch rejects an expired session,
the server re-opens the car transparently: free for garage cars, but for credit VINs
**ask again**, unless the site doesn't charge again; verify this before relying on it.

### Shops interface (for later)

Define a small interface such as `OemSource.search(oem) -> list[Offer]` with a common
`Offer` shape (shop, product name, manufacturer, price, currency, stock/availability,
url). Autokelly is the first implementation. The later shops plug in as more sources,
plus a tool that searches all of them.

### Suggested module layout (builder may change)

- `auth`: cookie store, validity check, Playwright login.
- `http`: curl_cffi session factory, header profile, pacing, block detection.
- `autokelly`: garage, credits, catalog page, OEM search, prices, stock.
- `laximo`: catalog sessions, tree, group parts, picture units, unit page.
- `parsers`: pure functions from HTML/JSON to dataclasses. No I/O, easy to test.
- `images`: download, downscale, annotate, crop.
- `server`: FastMCP tool definitions.

## The skill

A skill shipped in the plugin (e.g. `skills/autokelly-parts/SKILL.md`) that triggers on
Czech and English requests about finding car parts or OEM numbers. It tells the agent:

1. **Pick the car.** Use the garage by default (match by name, plate or VIN). If the
   user gives a VIN that isn't in the garage, **say it will use 1 of N VIN credits and
   wait for an explicit yes** before calling the paid route with `confirm=true`.
2. **Translate the request.** Turn the Czech request into (a) Czech tree terms without
   diacritics ("chladič" → "chladic") and (b) English manufacturer terms ("gumové
   uložení chladiče" → "radiator mounting insulator / rubber / bush").
3. **Search both catalogs.** Search the tree, open likely leaves, and check likely
   picture-catalog units. Prefer a few targeted calls over broad browsing.
4. **Confirm visually.** Open the unit diagram, look at the image, and match the callout
   to the part the user described. Use `highlight` to double-check.
5. **Handle ambiguity by asking.** Left/right, upper/lower, several date ranges or
   variants, or several plausible parts: show the options briefly and ask.
6. **Answer in Czech** with a compact table: part (Czech), OEM number, catalog name,
   diagram (unit code and name), plus Autokelly offers (manufacturer, price, stock).
7. **Never** touch the cart, and **never** spend a credit without that explicit yes.

## Testing

- **Parser unit tests** run against saved fixtures: the garage JSON, the vinsearch entry
  page, the group-list page (tree JSON), the group-part-list fragment, the
  category-unit-list fragment, the unit page, and the OEM items, price and stock JSON.
  **Scrub the fixtures**: the customer number `cn`, the user's name and email (they
  appear in the Autokelly page HTML, e.g. in the GTM dataLayer), and session ids and
  tokens where practical.
- **Tool-level tests** run with the HTTP layer faked by the fixtures.
- **A live smoke test** (opt-in through an env var, never in CI): status → garage →
  open the Hyundai → search "chladic" → get the parts for "Chladic vody" → get the
  unit → OEM search `25310J7800`. It also opens the **Alfa** (several matches → pick
  LHD) → one tree leaf → one unit. It never runs the paid route.
- **Fixtures for both cars:** the builder captures the Alfa's tree, group-part-list,
  picture-catalog and unit pages too, since another brand may use different markup.
- **The paid route is verified manually, with at most 2 credits** (approved by the
  user): open a non-garage VIN once (check which call deducts), then open it again
  (check whether it charges again). Record the results in the README and adjust the
  re-open behaviour to match.

## Privacy and security

- The cookie file lives outside the repo with `0600` permissions. Never log cookie
  values or full request headers.
- The recon folder `.playwright-mcp/` in the project root holds screenshots and
  snapshots with the user's name. It must be in `.gitignore` and must never be
  committed.
- The customer number is personal data. Don't hard-code it; read it from the page.

## Left to the builder

- Final tool names and parameter shapes, within the behaviour above.
- Parser library, caching details, image size limits and the crop/annotation style.
- Fuzzy-matching method for `search_tree`.
- How to detect "logged out" and "blocked" reliably (observe the real responses).
- Exact request bodies for the stock and disponibility endpoints (capture them during
  the build).

## Open points to verify during the build

1. The meaning and lifetime of `searchGuid`, and whether
   `/ProductList/Items/GraphicsCatalogOem/1` needs the page GET first.
2. How long a vinsearch session lasts, and whether tokens survive across sessions.
3. Which step of the paid route deducts the credit, and whether re-opening a recently
   decoded VIN charges again. This needs the user's approval to spend 1 credit.
4. Whether image URLs need a referer or cookies.
5. What the Autokelly endpoints return when the session is logged out.
