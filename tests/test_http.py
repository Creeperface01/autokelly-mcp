"""Classify, pacing and header behaviour of the HTTP layer."""

import pytest
from conftest import make_response

from autokelly_mcp.errors import BlockedError
from autokelly_mcp.http import classify


def test_classify():
    # 200 JSON passes.
    classify(make_response("{}", headers={"shieldsquare-response": "0"}), True)

    # Status-based blocks.
    with pytest.raises(BlockedError):
        classify(make_response("{}", status=403), True)
    with pytest.raises(BlockedError):
        classify(make_response("{}", status=429), False)
    with pytest.raises(BlockedError):
        classify(make_response("{}", status=503), False)

    # ShieldSquare header block.
    with pytest.raises(BlockedError):
        classify(make_response("{}", headers={"shieldsquare-response": "2"}), False)

    # HTML where JSON expected.
    with pytest.raises(BlockedError):
        classify(make_response("<html>captcha</html>"), True)

    # HTML is fine when JSON is not expected.
    classify(make_response("<html>ok</html>"), False)


@pytest.mark.anyio
async def test_pacing():
    from autokelly_mcp.http import CurlFetcher

    seen: list[tuple[str, str]] = []

    async def transport(method, url, **kwargs):
        seen.append((method, url))
        return make_response("{}", url=url)

    sleeps: list[float] = []

    async def sleep(d: float) -> None:
        sleeps.append(d)

    now = [1000.0]

    def clock() -> float:
        return now[0]

    fetcher = CurlFetcher(transport=transport, sleep=sleep, clock=clock, rng=lambda a, b: 0.5)
    await fetcher.get("https://www.autokelly.cz/a")
    now[0] += 0.1
    await fetcher.get("https://www.autokelly.cz/b")
    assert len(sleeps) == 1
    assert 0.3 <= sleeps[0] <= 0.8

    # Different hosts: no sleep before the first request to each.
    sleeps2: list[float] = []

    async def sleep2(d: float) -> None:
        sleeps2.append(d)

    fetcher2 = CurlFetcher(transport=transport, sleep=sleep2, clock=lambda: 1000.0, rng=lambda a, b: 0.5)
    await fetcher2.get("https://www.autokelly.cz/a")
    await fetcher2.get("https://vinsearch.autokelly.cz/b")
    assert sleeps2 == []


@pytest.mark.anyio
async def test_default_headers_and_body_rules():
    from autokelly_mcp.http import CurlFetcher

    captured: dict = {}

    async def transport(method, url, **kwargs):
        captured["method"] = method
        captured["headers"] = kwargs.get("headers")
        captured["body"] = kwargs.get("body", kwargs.get("data", None))
        return make_response("{}", url=url)

    fetcher = CurlFetcher(transport=transport, sleep=lambda d: _noop(), clock=lambda: 0.0)
    await fetcher.get("https://www.autokelly.cz/a")
    assert captured["headers"]["accept-language"] == "cs-CZ,cs;q=0.9"

    await fetcher.post_json("https://www.autokelly.cz/j", {"a": 1})
    assert captured["headers"]["accept"] == "application/json, text/plain, */*"
    assert captured["headers"]["content-type"] == "application/json;charset=UTF-8"

    await fetcher.post_json("https://www.autokelly.cz/j", None)
    assert "content-type" not in captured["headers"]

    await fetcher.post_form("https://www.autokelly.cz/f", {"x": "y"})
    assert captured["headers"]["content-type"] == "application/x-www-form-urlencoded; charset=UTF-8"
    assert captured["headers"]["x-requested-with"] == "XMLHttpRequest"


async def _noop() -> None:
    return None
