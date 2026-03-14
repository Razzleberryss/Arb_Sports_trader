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
# Pre-game scanner mode
# ---------------------------------------------------------------------------

#: How often the pre-game scanner polls (seconds).  Default: 5 minutes.
PREGAME_INTERVAL_SECONDS: int = int(os.getenv("PREGAME_INTERVAL_SECONDS", "300"))

#: Implied-probability threshold for pre-game mode (2 % edge).
PREGAME_ARB_THRESHOLD: float = float(os.getenv("PREGAME_ARB_THRESHOLD", "0.98"))

#: Log file path for pre-game opportunities.
PREGAME_LOG_FILE: str = os.getenv("PREGAME_LOG_FILE", "logs/pregame_opps.log")

#: Games starting within this many minutes are excluded from pre-game scanning.
PREGAME_BUFFER_MINUTES: int = int(os.getenv("PREGAME_BUFFER_MINUTES", "5"))

# ---------------------------------------------------------------------------
# Live / in-play scanner mode
# ---------------------------------------------------------------------------

#: How often the live scanner polls (seconds).  Default: 30 seconds.
LIVE_INTERVAL_SECONDS: int = int(os.getenv("LIVE_INTERVAL_SECONDS", "30"))

#: Tighter implied-probability threshold for live mode (4 % edge).
LIVE_ARB_THRESHOLD: float = float(os.getenv("LIVE_ARB_THRESHOLD", "0.96"))

#: Log file path for live opportunities.
LIVE_LOG_FILE: str = os.getenv("LIVE_LOG_FILE", "logs/live_opps.log")

#: Edge % above which ⚡ LIVE ARB is printed to console.
LIVE_ALERT_THRESHOLD_PCT: float = float(os.getenv("LIVE_ALERT_THRESHOLD_PCT", "2.0"))

# ---------------------------------------------------------------------------
# Sports & markets
# ---------------------------------------------------------------------------
SUPPORTED_SPORTS: list[str] = ["NBA", "NFL", "soccer"]

SUPPORTED_MARKET_TYPES: list[str] = ["moneyline", "spreads"]
