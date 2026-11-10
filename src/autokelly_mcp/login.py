"""Interactive login window (Playwright).

Opens a visible browser for the user to log in once, then captures the
session cookies and User-Agent. Not unit-tested (it opens a real browser).
"""

from __future__ import annotations

import asyncio
import datetime

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from autokelly_mcp.config import BASE_URL
from autokelly_mcp.errors import LoginFailedError
from autokelly_mcp.session_store import SessionData, load_session

_CAR_LIST_URL = BASE_URL + "/Garage/CarList"
_CREDIT_URL = BASE_URL + "/vin-decoder/credit"
_POLL_S = 2.0

# Cookie keys Playwright's add_cookies accepts; anything else is dropped.
_COOKIE_KEYS = frozenset({"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"})


async def browser_login(timeout_s: int = 300) -> SessionData:
    """Open the login window and wait until the credit endpoint reports a session."""
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(channel="chrome", headless=False)
        except PlaywrightError:
            browser = await p.chromium.launch(headless=False)
        try:
            context = await browser.new_context()
            saved = load_session()
            if saved is not None and saved.cookies:
                await context.add_cookies(
                    [{k: v for k, v in cookie.items() if k in _COOKIE_KEYS} for cookie in saved.cookies]
                )
            page = await context.new_page()
            await page.goto(_CAR_LIST_URL)
            deadline = asyncio.get_running_loop().time() + timeout_s
            while True:
                if page.is_closed() or not browser.is_connected():
                    raise LoginFailedError("login window was closed")
                resp = await context.request.post(
                    _CREDIT_URL, headers={"accept": "application/json, text/plain, */*"}
                )
                try:
                    payload = await resp.json()
                except (ValueError, PlaywrightError):
                    payload = None
                if isinstance(payload, dict) and "data" in payload:
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    raise LoginFailedError("login timed out")
                await asyncio.sleep(_POLL_S)
            user_agent = await page.evaluate("navigator.userAgent")
            raw_cookies = await context.cookies()
            cookies = [c for c in raw_cookies if str(c.get("domain", "")).endswith("autokelly.cz")]
            saved_at = datetime.datetime.now(datetime.UTC).isoformat()
            return SessionData(cookies=cookies, user_agent=str(user_agent), saved_at=saved_at)
        finally:
            await browser.close()
