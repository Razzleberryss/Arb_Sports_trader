"""Paper trade executor – simulation only, no real exchange calls.

This module tracks simulated (paper) positions in memory and logs
execution details.  It is intentionally restricted to logging and
in-memory tracking: no network requests are made and no real orders
are sent to any exchange or bookmaker.

Usage
-----
Set ``AUTO_TRADE_ENABLED=true`` in your ``.env`` file to enable paper
execution.  When the flag is absent or ``false`` the executor logs a
skip message and returns without recording any position.

DISCLAIMER: This module is for educational / testing use only.
            No real bets are placed.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field

from sports_arb.models import ArbitrageOpportunity

# ---------------------------------------------------------------------------
# Optional .env support (mirrors config.py pattern)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv not installed – silently continue
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class PaperLeg:
    """A single simulated leg of a paper trade."""

    venue: str       # bookmaker / exchange name
    market_id: str   # game_id used as the market identifier
    outcome: str     # e.g. "home", "away", "draw"
    side: str        # "BUY" or "SELL"
    price: float     # decimal odds at time of paper execution
    size: float      # notional stake in the paper account


@dataclass
class PaperPositionBook:
    """In-memory book of open paper legs.

    A module-level singleton (``book``) is provided below so that all
    calls to :func:`execute_arb` accumulate legs in the same book
    throughout the scanner's lifetime.

    ``add_legs`` and ``summary`` are protected by an internal
    :class:`threading.Lock` so they are safe to call from concurrent
    pregame (sync thread) and live (async event loop) scan cycles.
    """

    legs: list[PaperLeg] = field(default_factory=list)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    def add_legs(self, legs: list[PaperLeg]) -> None:
        """Append *legs* to the position book (thread-safe)."""
        with self._lock:
            self.legs.extend(legs)

    def summary(self) -> str:
        """Return a human-readable count of open paper legs (thread-safe)."""
        with self._lock:
            n = len(self.legs)
        noun = "leg" if n == 1 else "legs"
        return f"{n} paper {noun} open"


#: Module-level paper position book shared across all execute_arb calls.
book = PaperPositionBook()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _size_from_opportunity(opp: ArbitrageOpportunity) -> float:  # noqa: ARG001
    """Return the paper stake to use for each leg.

    A future real executor would derive position size from bankroll,
    the Kelly criterion, or explicit risk limits.  For now a fixed
    value is returned.
    """
    return 10.0


# ---------------------------------------------------------------------------
# Main executor
# ---------------------------------------------------------------------------


def execute_arb(opp: ArbitrageOpportunity) -> None:
    """Simulate execution of an arbitrage opportunity (paper mode only).

    Reads ``AUTO_TRADE_ENABLED`` from the environment (``.env`` is loaded
    automatically when *python-dotenv* is installed).  Accepted truthy
    values: ``"true"``, ``"1"``, ``"yes"`` (case-insensitive).

    If the flag is false or absent the function logs a skip message and
    returns immediately without modifying the position book.

    No real exchange API calls are made.

    Parameters
    ----------
    opp:
        The arbitrage opportunity to (paper-)execute.
    """
    enabled_raw = os.getenv("AUTO_TRADE_ENABLED", "false").strip().lower()
    auto_trade_enabled = enabled_raw in {"1", "true", "yes"}

    if not auto_trade_enabled:
        logger.debug(
            "AUTO_TRADE_ENABLED is false; skipping paper execution. "
            "Would have traded opportunity: %s",
            opp,
        )
        return

    stake = _size_from_opportunity(opp)
    legs: list[PaperLeg] = [
        PaperLeg(
            venue=opp.best_odds_books[outcome],
            market_id=opp.game_id,
            outcome=outcome,
            side="BUY",
            price=price,
            size=stake,
        )
        for outcome, price in opp.best_odds.items()
    ]

    book.add_legs(legs)

    logger.info(
        "Executed PAPER arb with %d legs, stake=%s. %s",
        len(legs),
        stake,
        book.summary(),
    )
    for leg in legs:
        logger.info(
            "PAPER %s %s %s %s @ %s x %s",
            leg.venue,
            leg.market_id,
            leg.outcome,
            leg.side,
            leg.price,
            leg.size,
        )
