"""Tests for server-side credit confirmation (confirm.py)."""

from __future__ import annotations

import pytest

from autokelly_mcp.errors import ConfirmationError
from autokelly_mcp.models import Credits

VIN = "TESTVINHYUNDAI001"


def _credits(n: int = 5) -> Credits:
    return Credits(credit=n, unlimited=False, message="msg")


class _NoElicitSession:
    def check_client_capability(self, capability) -> bool:
        return False


class _NoElicitCtx:
    def __init__(self) -> None:
        self.session = _NoElicitSession()

    async def elicit(self, message, schema):  # pragma: no cover - must not be called
        raise AssertionError("elicit must not be called when unsupported")


class _ElicitResult:
    def __init__(self, action: str, data=None) -> None:
        self.action = action
        self.data = data


class _YesSession:
    def check_client_capability(self, capability) -> bool:
        return True


class _YesCtx:
    def __init__(self, action: str, data=None) -> None:
        self.session = _YesSession()
        self._action = action
        self._data = data
        self.messages: list[str] = []
        self.schemas: list = []

    async def elicit(self, message, schema):
        self.messages.append(message)
        self.schemas.append(schema)
        return _ElicitResult(self._action, self._data)


def test_token_works_once_then_fails():
    from autokelly_mcp.confirm import TokenBook

    book = TokenBook()
    token = book.issue(VIN)
    book.consume(VIN, token)
    with pytest.raises(ConfirmationError):
        book.consume(VIN, token)


def test_token_wrong_vin_fails():
    from autokelly_mcp.confirm import TokenBook

    book = TokenBook()
    token = book.issue(VIN)
    with pytest.raises(ConfirmationError):
        book.consume("OTHERVIN000000001", token)


def test_token_expired_fails():
    from autokelly_mcp.confirm import TokenBook

    now = [1000.0]
    book = TokenBook(clock=lambda: now[0])
    token = book.issue(VIN)
    now[0] += 601.0
    with pytest.raises(ConfirmationError):
        book.consume(VIN, token)


def test_issue_replaces_earlier_token():
    from autokelly_mcp.confirm import TokenBook

    book = TokenBook()
    first = book.issue(VIN)
    second = book.issue(VIN)
    assert second != first
    with pytest.raises(ConfirmationError):
        book.consume(VIN, first)
    book.consume(VIN, second)


@pytest.mark.anyio
async def test_token_path_first_call_returns_dict_second_confirms():
    from autokelly_mcp.confirm import TokenBook, confirm_credit_use

    book = TokenBook()
    first = await confirm_credit_use(_NoElicitCtx(), VIN, _credits(), book, None)
    assert isinstance(first, dict)
    assert first["status"] == "confirmation_required"
    assert first["credits_left"] == 5
    assert first["expires_in_s"] == 600
    assert first["confirm_token"]
    assert VIN in first["message"]

    second = await confirm_credit_use(_NoElicitCtx(), VIN, _credits(), book, first["confirm_token"])
    assert second == "confirmed"

    with pytest.raises(ConfirmationError):
        await confirm_credit_use(_NoElicitCtx(), VIN, _credits(), book, first["confirm_token"])


@pytest.mark.anyio
async def test_token_path_bad_token_fails():
    from autokelly_mcp.confirm import TokenBook, confirm_credit_use

    with pytest.raises(ConfirmationError):
        await confirm_credit_use(_NoElicitCtx(), VIN, _credits(), TokenBook(), "bogus")


@pytest.mark.anyio
async def test_elicit_accept_true_confirms():
    from autokelly_mcp.confirm import CreditConsent, TokenBook, confirm_credit_use

    ctx = _YesCtx("accept", {"confirm": True})
    result = await confirm_credit_use(ctx, VIN, _credits(), TokenBook(), None)
    assert result == "confirmed"
    assert len(ctx.messages) == 1
    assert "1 z 5" in ctx.messages[0]
    assert VIN in ctx.messages[0]
    assert ctx.schemas[0] is CreditConsent


@pytest.mark.anyio
async def test_elicit_accept_false_declines():
    from autokelly_mcp.confirm import TokenBook, confirm_credit_use

    ctx = _YesCtx("accept", {"confirm": False})
    assert await confirm_credit_use(ctx, VIN, _credits(), TokenBook(), None) == "declined"


@pytest.mark.anyio
async def test_elicit_decline_declines():
    from autokelly_mcp.confirm import TokenBook, confirm_credit_use

    ctx = _YesCtx("decline")
    assert await confirm_credit_use(ctx, VIN, _credits(), TokenBook(), None) == "declined"


@pytest.mark.anyio
async def test_elicit_cancel_declines():
    from autokelly_mcp.confirm import TokenBook, confirm_credit_use

    ctx = _YesCtx("cancel")
    assert await confirm_credit_use(ctx, VIN, _credits(), TokenBook(), None) == "declined"
