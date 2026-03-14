"""odds_providers package – exports the base class and provider registry."""

from __future__ import annotations

import os

from sports_arb.odds_providers.base import BaseOddsProvider
from sports_arb.odds_providers.mock_provider import MockOddsProvider

# Registry maps provider name -> class so callers can instantiate by name.
PROVIDER_REGISTRY: dict[str, type[BaseOddsProvider]] = {
    MockOddsProvider.name: MockOddsProvider,
}

# Register the real Odds API provider when an API key is available.
if os.getenv("ODDS_API_KEY"):
    from sports_arb.odds_providers.the_odds_api import TheOddsApiProvider

    PROVIDER_REGISTRY[TheOddsApiProvider.name] = TheOddsApiProvider

__all__ = [
    "BaseOddsProvider",
    "MockOddsProvider",
    "PROVIDER_REGISTRY",
]
