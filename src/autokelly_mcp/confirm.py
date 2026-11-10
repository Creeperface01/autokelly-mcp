"""Server-side credit confirmation: MCP elicitation or a one-time token.

Looking up a VIN outside the user's garage spends a paid VIN credit, so the
server itself must collect the user's explicit yes before any paid call: via
MCP elicitation when the client supports it, otherwise via a one-time token
that the caller passes back on the retry.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from typing import Any, Literal

from mcp import types
from pydantic import BaseModel, Field

from autokelly_mcp.errors import ConfirmationError
from autokelly_mcp.models import Credits

TOKEN_TTL_S = 600


class CreditConsent(BaseModel):
    """Elicitation schema asking for an explicit yes to spend a VIN credit."""

    confirm: bool = Field(description="Potvrďte použití VIN kreditu")


class TokenBook:
    """Issues and consumes single-use confirmation tokens, one VIN at a time."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._tokens: dict[str, tuple[str, float]] = {}

    def issue(self, vin: str) -> str:
        """Issue a fresh token for *vin*, replacing any earlier unused one."""
        token = secrets.token_urlsafe(8)
        self._tokens[vin] = (token, self._clock())
        return token

    def consume(self, vin: str, token: str) -> None:
        """Consume a token, or raise ConfirmationError when it is invalid."""
        entry = self._tokens.get(vin)
        if entry is None or entry[0] != token:
            raise ConfirmationError("Unknown or mismatched confirmation token.")
        issued_at = entry[1]
        del self._tokens[vin]
        if self._clock() - issued_at > TOKEN_TTL_S:
            raise ConfirmationError("The confirmation token has expired.")


def _elicitation_message(vin: str, credits: Credits) -> str:
    if credits.unlimited:
        return f"Použít VIN kredit (neomezený přístup) na VIN {vin}? Tuto akci nelze vrátit."
    return f"Použít 1 z {credits.credit} VIN kreditů na VIN {vin}? Tuto akci nelze vrátit."


def _token_warning(vin: str, credits: Credits) -> str:
    if credits.unlimited:
        return (
            f"Vyhledání VIN {vin} použije VIN kredit (neomezený přístup). "
            "Tuto akci nelze vrátit. Pro pokračování zavolejte nástroj znovu s confirm_token."
        )
    return (
        f"Vyhledání VIN {vin} použije 1 z {credits.credit} VIN kreditů. "
        "Tuto akci nelze vrátit. Pro pokračování zavolejte nástroj znovu s confirm_token."
    )


async def confirm_credit_use(
    ctx: Any,
    vin: str,
    credits: Credits,
    book: TokenBook,
    confirm_token: str | None,
) -> Literal["confirmed", "declined"] | dict:
    """Collect the user's yes to spend a VIN credit, or decline.

    When the client supports MCP elicitation the user is asked inline and the
    result is "confirmed" only on accept with confirm=True. Otherwise the first
    call returns a confirmation_required dict with a one-time token, and the
    retry with that token returns "confirmed".
    """
    supports_elicitation = ctx.session.check_client_capability(
        types.ClientCapabilities(elicitation=types.ElicitationCapability())
    )
    if supports_elicitation:
        result = await ctx.elicit(message=_elicitation_message(vin, credits), schema=CreditConsent)
        if getattr(result, "action", None) == "accept":
            data = getattr(result, "data", None)
            if isinstance(data, dict):
                ok = data.get("confirm") is True
            else:
                ok = getattr(data, "confirm", None) is True
            if ok:
                return "confirmed"
        return "declined"
    if confirm_token is None:
        return {
            "status": "confirmation_required",
            "credits_left": credits.credit,
            "confirm_token": book.issue(vin),
            "expires_in_s": TOKEN_TTL_S,
            "message": _token_warning(vin, credits),
        }
    book.consume(vin, confirm_token)
    return "confirmed"
