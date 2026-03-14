"""Configuration for the sports arbitrage scanner.

Values can be overridden via a .env file in the project root when
python-dotenv is installed.  The module degrades gracefully if the
package is absent.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Optional .env support
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv not installed – silently continue
    pass

# ---------------------------------------------------------------------------
# Bookmakers
# ---------------------------------------------------------------------------
BOOKMAKERS: list[str] = [
    "DraftKings",
    "FanDuel",
    "Caesars",
    "Mock",
]

# ---------------------------------------------------------------------------
# Arbitrage thresholds
# ---------------------------------------------------------------------------

# Minimum edge required to surface an opportunity (as a fraction, not %).
# Edge = 1 − implied_prob_sum.  0.02 → 2 % edge.
DEFAULT_MIN_EDGE: float = float(os.getenv("DEFAULT_MIN_EDGE", "0.02"))

# Implied-probability sum must be *below* this value for an opportunity to
# be reported.  0.98 corresponds to a 2 % edge.
ARB_THRESHOLD: float = float(os.getenv("ARB_THRESHOLD", "0.98"))

# ---------------------------------------------------------------------------
# Polling / refresh
# ---------------------------------------------------------------------------
REFRESH_INTERVAL_SECONDS: int = int(os.getenv("REFRESH_INTERVAL_SECONDS", "60"))

# ---------------------------------------------------------------------------
# Sports & markets
# ---------------------------------------------------------------------------
SUPPORTED_SPORTS: list[str] = ["NBA", "NFL", "soccer"]

SUPPORTED_MARKET_TYPES: list[str] = ["moneyline", "spreads"]
