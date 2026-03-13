"""odds_providers package – exports the base class and provider registry."""

from __future__ import annotations

from sports_arb.odds_providers.base import BaseOddsProvider
from sports_arb.odds_providers.mock_provider import MockOddsProvider

# Registry maps provider name -> class so callers can instantiate by name.
PROVIDER_REGISTRY: dict[str, type[BaseOddsProvider]] = {
    MockOddsProvider.name: MockOddsProvider,
}

__all__ = [
    "BaseOddsProvider",
    "MockOddsProvider",
    "PROVIDER_REGISTRY",
]
