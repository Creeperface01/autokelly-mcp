"""Browser-login session checks: login-once behaviour and with_relogin retry."""

import pytest
from conftest import FakeFetcher, fixture_text, make_response

from autokelly_mcp.auth import Auth
from autokelly_mcp.errors import LoginFailedError, NotLoggedInError
from autokelly_mcp.models import Credits
from autokelly_mcp.session_store import SessionData, load_session, save_session

_OK = fixture_text("autokelly/vin_credit.json")
_LOGGED_OUT = fixture_text("autokelly/vin_credit_logged_out.json")


def _fake_login(counter: dict, data: SessionData | None = None):
    async def login() -> SessionData:
        counter["logins"] += 1
        if data is not None:
            return data
        return SessionData(cookies=[{"name": "c", "value": "v"}], user_agent="TestUA/1.0")

    return login


def _sequential_credit(*bodies: str):
    state = {"n": 0}

    def target(method: str, url: str, body: object):
        index = min(state["n"], len(bodies) - 1)
        state["n"] += 1
        return make_response(bodies[index], url=url)

    return target


@pytest.mark.anyio
async def test_no_session_triggers_login_then_ok():
    counter = {"logins": 0}
    fetcher = FakeFetcher([("POST", "vin-decoder/credit", "autokelly/vin_credit.json")])
    auth = Auth(fetcher, login=_fake_login(counter))

    credits = await auth.ensure_session()

    assert credits == Credits(credit=5, unlimited=False, message="Počet VIN kreditů: 5")
    assert counter["logins"] == 1
    # No session file means no credit check happens before the login.
    assert len(fetcher.calls) == 1
    saved = load_session()
    assert saved is not None
    assert saved.user_agent == "TestUA/1.0"
    assert fetcher.session == saved


@pytest.mark.anyio
async def test_logged_out_relogin_once():
    save_session(SessionData(cookies=[], user_agent="OldUA", search_guid="guid-123"))
    counter = {"logins": 0}
    fetcher = FakeFetcher([("POST", "vin-decoder/credit", _sequential_credit(_LOGGED_OUT, _OK))])
    auth = Auth(fetcher, login=_fake_login(counter))

    credits = await auth.ensure_session()

    assert credits == Credits(credit=5, unlimited=False, message="Počet VIN kreditů: 5")
    assert counter["logins"] == 1
    assert len(fetcher.calls) == 2
    # The older session's search guid carries over into the freshly saved session.
    saved = load_session()
    assert saved is not None
    assert saved.search_guid == "guid-123"
    assert fetcher.session == saved


@pytest.mark.anyio
async def test_logged_out_twice_raises():
    save_session(SessionData(cookies=[], user_agent="OldUA"))
    counter = {"logins": 0}
    fetcher = FakeFetcher([("POST", "vin-decoder/credit", _sequential_credit(_LOGGED_OUT))])
    auth = Auth(fetcher, login=_fake_login(counter))

    with pytest.raises(NotLoggedInError):
        await auth.ensure_session()

    assert counter["logins"] == 1
    assert len(fetcher.calls) == 2


@pytest.mark.anyio
async def test_with_relogin_retries_once():
    counter = {"logins": 0}
    fetcher = FakeFetcher([("POST", "vin-decoder/credit", "autokelly/vin_credit.json")])
    auth = Auth(fetcher, login=_fake_login(counter))
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise NotLoggedInError("stale session")
        return "ok"

    assert await auth.with_relogin(flaky) == "ok"
    assert counter["logins"] == 1
    assert calls["n"] == 2


@pytest.mark.anyio
async def test_with_relogin_gives_up_after_retry():
    counter = {"logins": 0}
    fetcher = FakeFetcher([("POST", "vin-decoder/credit", "autokelly/vin_credit.json")])
    auth = Auth(fetcher, login=_fake_login(counter))
    calls = {"n": 0}

    async def always_down() -> str:
        calls["n"] += 1
        raise NotLoggedInError("stale session")

    with pytest.raises(NotLoggedInError):
        await auth.with_relogin(always_down)
    assert calls["n"] == 2
    assert counter["logins"] == 1


@pytest.mark.anyio
async def test_login_failure_propagates():
    async def failing_login() -> SessionData:
        raise LoginFailedError("login window was closed")

    fetcher = FakeFetcher([("POST", "vin-decoder/credit", "autokelly/vin_credit.json")])
    auth = Auth(fetcher, login=failing_login)

    with pytest.raises(LoginFailedError):
        await auth.ensure_session()

    assert load_session() is None
    assert fetcher.session is None
