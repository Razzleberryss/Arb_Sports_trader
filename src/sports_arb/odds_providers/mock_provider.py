"""Mock odds provider with hard-coded stub data.

Three games are defined:
  - Game 1 (NBA, Lakers vs. Celtics)   → **arbitrage opportunity** exists
  - Game 2 (NFL, Chiefs vs. Eagles)    → no arbitrage (vig > 0)
  - Game 3 (EPL, Arsenal vs. Chelsea)  → **arbitrage opportunity** exists

American odds are stored as the source-of-truth and converted to decimal via
the :func:`american_to_decimal` helper defined in this module.

DISCLAIMER: All data is entirely fictitious and exists only for educational
purposes.  No real bookmaker odds are represented.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sports_arb.models import BookmakerOdds
from sports_arb.odds_providers.base import BaseOddsProvider

# ---------------------------------------------------------------------------
# Standalone helper (also re-used by arb_engine; duplicated here to keep the
# provider self-contained and importable without the engine).
# ---------------------------------------------------------------------------

def american_to_decimal(american_odds: int) -> float:
    """Convert American (moneyline) odds to decimal odds.

    Parameters
    ----------
    american_odds:
        Positive value indicates the profit on a $100 wager (underdog).
        Negative value indicates the amount needed to wager to win $100 (favorite).

    Returns
    -------
    float
        Equivalent decimal odds (stake included).

    Examples
    --------
    >>> american_to_decimal(150)
    2.5
    >>> american_to_decimal(-110)
    1.9090909090909092
    >>> american_to_decimal(100)
    2.0
    """
    if american_odds >= 0:
        return (american_odds / 100) + 1.0
    return (100 / abs(american_odds)) + 1.0


# ---------------------------------------------------------------------------
# Stub data definition
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


# Each entry: (game_id, sport, league, home, away, offset_hours,
#              market_type, bookmaker, american_odds_dict)
_RAW_ODDS: list[tuple] = [
    # -----------------------------------------------------------------------
    # Game 1 – NBA Lakers vs. Celtics  → ARB EXISTS
    # MockBook_A offers Lakers +200 (decimal 3.0), Celtics −130 (decimal 1.769)
    # MockBook_B offers Lakers +180 (decimal 2.8),  Celtics −110 (decimal 1.909)
    # MockBook_C offers Lakers +210 (decimal 3.1),  Celtics −140 (decimal 1.714)
    #
    # Best odds: Lakers 3.1 (C) + Celtics 1.909 (B)
    # IP sum = 1/3.1 + 1/1.909 ≈ 0.3226 + 0.5239 ≈ 0.8465  → CLEAR ARB
    # -----------------------------------------------------------------------
    (
        "game_nba_001", "NBA", "NBA",
        "Los Angeles Lakers", "Boston Celtics",
        3, "moneyline",
        "MockBook_A",
        {"home": american_to_decimal(200), "away": american_to_decimal(-130)},
    ),
    (
        "game_nba_001", "NBA", "NBA",
        "Los Angeles Lakers", "Boston Celtics",
        3, "moneyline",
        "MockBook_B",
        {"home": american_to_decimal(180), "away": american_to_decimal(-110)},
    ),
    (
        "game_nba_001", "NBA", "NBA",
        "Los Angeles Lakers", "Boston Celtics",
        3, "moneyline",
        "MockBook_C",
        {"home": american_to_decimal(210), "away": american_to_decimal(-140)},
    ),
    # -----------------------------------------------------------------------
    # Game 2 – NFL Chiefs vs. Eagles  → NO ARB (standard vig on every book)
    # Best odds across books: Chiefs 1.952 (C) + Eagles 2.0 (B)
    # IP sum = 1/1.952 + 1/2.0 ≈ 0.5123 + 0.5000 ≈ 1.012  → no arb
    # -----------------------------------------------------------------------
    (
        "game_nfl_001", "NFL", "NFL",
        "Kansas City Chiefs", "Philadelphia Eagles",
        7, "moneyline",
        "MockBook_A",
        {"home": american_to_decimal(-110), "away": american_to_decimal(-115)},
    ),
    (
        "game_nfl_001", "NFL", "NFL",
        "Kansas City Chiefs", "Philadelphia Eagles",
        7, "moneyline",
        "MockBook_B",
        {"home": american_to_decimal(-115), "away": american_to_decimal(-100)},
    ),
    (
        "game_nfl_001", "NFL", "NFL",
        "Kansas City Chiefs", "Philadelphia Eagles",
        7, "moneyline",
        "MockBook_C",
        {"home": american_to_decimal(-105), "away": american_to_decimal(-120)},
    ),
    # -----------------------------------------------------------------------
    # Game 3 – EPL Arsenal vs. Chelsea  → ARB EXISTS (3-way market)
    # Best odds: Arsenal 2.9 (A) + Draw 3.8 (C) + Chelsea 4.2 (B)
    # IP sum = 1/2.9 + 1/3.8 + 1/4.2 ≈ 0.3448 + 0.2632 + 0.2381 ≈ 0.8461 → ARB
    # -----------------------------------------------------------------------
    (
        "game_epl_001", "soccer", "EPL",
        "Arsenal", "Chelsea",
        24, "moneyline",
        "MockBook_A",
        {
            "home": american_to_decimal(190),   # Arsenal  → 2.9
            "draw": american_to_decimal(240),   # Draw     → 3.4
            "away": american_to_decimal(330),   # Chelsea  → 4.3
        },
    ),
    (
        "game_epl_001", "soccer", "EPL",
        "Arsenal", "Chelsea",
        24, "moneyline",
        "MockBook_B",
        {
            "home": american_to_decimal(170),   # Arsenal  → 2.7
            "draw": american_to_decimal(250),   # Draw     → 3.5
            "away": american_to_decimal(320),   # Chelsea  → 4.2
        },
    ),
    (
        "game_epl_001", "soccer", "EPL",
        "Arsenal", "Chelsea",
        24, "moneyline",
        "MockBook_C",
        {
            "home": american_to_decimal(175),   # Arsenal  → 2.75
            "draw": american_to_decimal(280),   # Draw     → 3.8
            "away": american_to_decimal(290),   # Chelsea  → 3.9
        },
    ),
]


class MockOddsProvider(BaseOddsProvider):
    """Returns hard-coded mock odds for testing and demonstration purposes.

    At least one game will exhibit a clear arbitrage opportunity.
    """

    name: str = "mock"

    def get_current_odds(self) -> list[BookmakerOdds]:
        """Return all mock :class:`~sports_arb.models.BookmakerOdds` records."""
        now = _now_utc()
        records: list[BookmakerOdds] = []

        for row in _RAW_ODDS:
            (
                game_id, sport, league,
                home_team, away_team,
                offset_hours, market_type,
                bookmaker, outcomes,
            ) = row

            records.append(
                BookmakerOdds(
                    bookmaker=bookmaker,
                    game_id=game_id,
                    sport=sport,
                    league=league,
                    home_team=home_team,
                    away_team=away_team,
                    start_time=now + timedelta(hours=offset_hours),
                    market_type=market_type,
                    outcomes=outcomes,
                )
            )

        return records
