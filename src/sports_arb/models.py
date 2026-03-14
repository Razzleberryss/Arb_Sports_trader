"""Typed data models for the sports arbitrage scanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Outcome:
    """A single wagerable outcome offered by one bookmaker."""

    name: str           # e.g. "home", "away", "draw"
    decimal_odds: float
    bookmaker: str


@dataclass
class Game:
    """Aggregated view of a game with the best available odds per outcome.

    ``outcomes`` contains one :class:`Outcome` per side, each sourced from
    whichever bookmaker offered the highest decimal odds for that side.
    """

    game_id: str
    sport: str           # "NBA", "NFL", "soccer"
    league: str          # "NBA", "NFL", "EPL", etc.
    home_team: str
    away_team: str
    start_time: datetime
    market_type: str     # "moneyline", "spreads"
    outcomes: list[Outcome]


@dataclass
class BookmakerOdds:
    """Raw odds snapshot from a single bookmaker for one game / market."""

    bookmaker: str
    game_id: str
    sport: str
    league: str
    home_team: str
    away_team: str
    start_time: datetime
    market_type: str
    outcomes: dict[str, float] = field(default_factory=dict)
    # outcome_name -> decimal_odds


@dataclass
class ArbitrageOpportunity:
    """A confirmed arbitrage opportunity across one or more bookmakers."""

    game_id: str
    sport: str
    league: str
    home_team: str
    away_team: str
    start_time: datetime
    market_type: str
    involved_books: list[str]
    best_odds: dict[str, float]          # outcome -> best decimal odds
    best_odds_books: dict[str, str]      # outcome -> bookmaker name
    implied_prob_sum: float
    edge_pct: float                      # (1 − implied_prob_sum) × 100
    stakes: dict[str, float]            # outcome -> recommended stake ($)
    expected_profit: float              # dollars for the configured bankroll
    expected_profit_pct: float          # profit as % of bankroll
