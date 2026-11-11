// Read the part offers from a shop search results page on imdily.cz, autodily-pema.cz or
// granex.cz (all three run the same Kvikshop platform). Open
// https://<shop>/vyhledavani?search=<OEM> first, then evaluate this whole file in the page.
// It is one expression and returns a plain, JSON-serialisable object; every string is kept
// short and offers are capped at 100, so browser tools that truncate long output keep it whole.
(() => {
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const text = (el) => (el ? clean(el.textContent) : "");
  const short = (s, n = 120) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
  const bodyText = document.body ? document.body.innerText || document.body.textContent || "" : "";

  const result = {
    shop: location.hostname.replace(/^www\./, ""),
    query: new URLSearchParams(location.search).get("search") || "",
    blocked: false,
    offers: [],
    page: 1,
    last_page: 1,
    has_more: false,
    next_page_url: "",
  };

  // Security check (Cloudflare challenge): report it, never try to get past it.
  const challengeText =
    /Potřebujeme zkontrolovat zabezpečení|Just a moment|Verify you are human|Ověřte, že jste člověk/i;
  if (
    challengeText.test(document.title + " " + bodyText.slice(0, 3000)) ||
    document.querySelector('script[src*="challenges.cloudflare.com"], iframe[src*="challenges.cloudflare.com"]')
  ) {
    result.blocked = true;
    return result;
  }

  // Brands as the shop itself tags them in its analytics list event (gtag or UA format).
  const brandByName = new Map();
  const remember = (name, brand) => {
    if (name && brand && !brandByName.has(clean(name))) brandByName.set(clean(name), clean(brand));
  };
  for (const entry of window.dataLayer || []) {
    if (!entry) continue;
    const gtag = entry[1] === "view_item_list" ? entry[2] : null;
    for (const item of (gtag && gtag.items) || []) remember(item.item_name, item.item_brand);
    const ua = entry.ecommerce && entry.ecommerce.impressions;
    for (const item of ua || []) remember(item.name, item.brand);
  }

  // Fallback when the analytics list is missing: the brand is the first upper-case token
  // after the Czech part type, plus one more upper-case word of 3+ letters ("BLUE PRINT").
  const upper = /^[A-Z0-9ÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ&.+\-]+$/;
  const guessBrand = (name) => {
    const tokens = name.split(" ");
    const start = tokens.findIndex(
      (t) => t.length >= 2 && /[A-Z]/.test(t) && upper.test(t) && !/^(OE|ORIGINAL|ORIGINÁL)$/.test(t),
    );
    if (start < 0) return "";
    let end = start + 1;
    const next = tokens[end];
    if (next && tokens[end + 1] && next.length >= 3 && /^[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ\-]+$/.test(next)) end += 1;
    return tokens.slice(start, end).join(" ");
  };

  const price = (card) => {
    const el =
      card.querySelector(".productPrices__block.--yourPrice .price__primary") ||
      card.querySelector(".price__primary");
    const digits = text(el).replace(/[^\d,]/g, "").replace(",", ".");
    return digits ? Number(digits) : null;
  };

  const availability = (card) => {
    const box = card.querySelector(".productAvailabilityShort");
    const cls = box ? box.className : "";
    const label = short(text(card.querySelector(".productAvailabilityShort__label")), 80);
    let available = null;
    if (/--notAvailable\b/.test(cls) || /Nedostupn|Prodej skončil|Vyprodáno|Nelze objednat/i.test(label)) {
      available = false;
    }
    else if (/--available\b/.test(cls) || /Skladem/i.test(label)) available = true;
    return { label, available };
  };

  const params = (card) => {
    const out = {};
    const box = card.querySelector(".productInline__parameters");
    if (!box) return out;
    for (const label of box.querySelectorAll("span")) {
      const value = label.nextElementSibling;
      if (!value || value.tagName !== "B") continue;
      const key = short(text(label), 60);
      if (key && !(key in out)) out[key] = short(text(value), 80);
    }
    return out;
  };

  const cards = [...document.querySelectorAll(".productInline")];
  for (const card of cards.slice(0, 100)) {
    const link = card.querySelector(".productInline__heading a") || card.querySelector("a[href]");
    const name = text(card.querySelector(".productInline__heading") || link);
    if (!name) continue;
    const labels = [...card.querySelectorAll(".productSpecialInfo__label")].map(text).filter(Boolean);
    let brand = brandByName.get(name) || "";
    const brandSource = brand ? "shop" : "guess";
    if (!brand) brand = guessBrand(name);
    let code = "";
    const at = brand ? name.toUpperCase().indexOf(brand.toUpperCase()) : -1;
    if (at >= 0) code = clean(name.slice(at + brand.length));
    const oeBrand = /^(OE|ORIGINAL|ORIGINÁL)\s+/i;
    const oe =
      labels.some((l) => /ORIGINÁLNÍ DÍL/i.test(l)) ||
      /^Originální díl/i.test(name) ||
      /\sOE\s/.test(` ${name} `) ||
      oeBrand.test(brand);
    let url = "";
    if (link && link.href) {
      const u = new URL(link.href, location.href);
      url = u.origin + u.pathname;
    }
    result.offers.push({
      brand: short(brand.replace(oeBrand, ""), 60),
      brand_source: brandSource,
      code: short(code, 60),
      name: short(name),
      price_czk: price(card),
      availability: availability(card),
      oe,
      params: params(card),
      notes: labels.filter((l) => !/ORIGINÁLNÍ DÍL/i.test(l)).map((l) => short(l, 160)),
      url: short(url, 200),
    });
  }

  // Pagination: numbered links carry ?page=N (page 1 has no parameter).
  const pageOf = (href) => Number(new URL(href, location.href).searchParams.get("page") || 1);
  const current = pageOf(location.href);
  const last = Math.max(
    current,
    ...[...document.querySelectorAll(".pagination a[href]")].map((a) => pageOf(a.href)),
  );
  result.page = current;
  result.last_page = last;
  if (last > current) {
    const next = new URL(location.href);
    next.searchParams.set("page", String(current + 1));
    result.next_page_url = next.href;
  }
  result.has_more = last > current;
  return result;
})()
