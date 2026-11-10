"""Exception hierarchy for the Autokelly MCP server."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autokelly_mcp.models import GarageCar


class AutokellyError(Exception):
    """Base error for all Autokelly MCP failures."""


class NotLoggedInError(AutokellyError):
    """The session is not logged in."""


class BlockedError(AutokellyError):
    """Autokelly (or ShieldSquare) blocked the request."""


class LoginFailedError(AutokellyError):
    """The login flow did not produce a usable session."""


class UnsupportedCarError(AutokellyError):
    """The car has no VIN catalog or a layout the parsers cannot handle."""


class UnknownCarError(AutokellyError):
    """The car reference did not match any garage car."""

    def __init__(self, message: str, cars: list[GarageCar] | None = None) -> None:
        super().__init__(message)
        self.cars: list[GarageCar] = list(cars) if cars is not None else []


class CatalogExpiredError(AutokellyError):
    """The Laximo session expired and re-opening did not help."""


class CreditRefusedError(AutokellyError):
    """The site refused to spend (or report) a VIN credit."""

    def __init__(self, message: str, reason: str = "") -> None:
        super().__init__(message)
        self.reason: str = reason


class ConfirmationError(AutokellyError):
    """Credit confirmation was missing, denied or invalid."""
