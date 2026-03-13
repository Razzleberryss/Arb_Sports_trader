"""Tests for src/sports_arb/models.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sports_arb.models import (
    ArbitrageOpportunity,
    BookmakerOdds,
    Game,
    Outcome,
)


# ---------------------------------------------------------------------------
# Outcome
# ---------------------------------------------------------------------------

def test_outcome_fields() -> None:
    o = Outcome(name="home", decimal_odds=2.5, bookmaker="MockBook_A")
    assert o.name == "home"
    assert o.decimal_odds == 2.5
    assert o.bookmaker == "MockBook_A"


def test_outcome_away() -> None:
    o = Outcome(name="away", decimal_odds=1.909, bookmaker="MockBook_B")
    assert o.name == "away"
    assert o.decimal_odds == pytest.approx(1.909, rel=1e-4)


def test_outcome_draw() -> None:
    o = Outcome(name="draw", decimal_odds=3.5, bookmaker="MockBook_C")
    assert o.name == "draw"


# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------

def test_game_construction() -> None:
    now = datetime.now(tz=timezone.utc)
    outcomes = [
        Outcome("home", 2.0, "BookA"),
        Outcome("away", 2.0, "BookB"),
    ]
    game = Game(
        game_id="g1",
        sport="NBA",
        league="NBA",
        home_team="Lakers",
        away_team="Celtics",
        start_time=now,
        market_type="moneyline",
        outcomes=outcomes,
    )
    assert game.game_id == "g1"
    assert game.sport == "NBA"
    assert len(game.outcomes) == 2
    assert game.outcomes[0].name == "home"


def test_game_start_time_is_datetime() -> None:
    now = datetime.now(tz=timezone.utc)
    game = Game(
        game_id="g2",
        sport="NFL",
        league="NFL",
        home_team="Chiefs",
        away_team="Eagles",
        start_time=now,
        market_type="moneyline",
        outcomes=[],
    )
    assert isinstance(game.start_time, datetime)


# ---------------------------------------------------------------------------
# BookmakerOdds
# ---------------------------------------------------------------------------

def test_bookmaker_odds_construction() -> None:
    now = datetime.now(tz=timezone.utc)
    record = BookmakerOdds(
        bookmaker="FanDuel",
        game_id="nba_123",
        sport="NBA",
        league="NBA",
        home_team="Lakers",
        away_team="Celtics",
        start_time=now,
        market_type="moneyline",
        outcomes={"home": 2.1, "away": 1.8},
    )
    assert record.bookmaker == "FanDuel"
    assert record.outcomes["home"] == pytest.approx(2.1)
    assert record.outcomes["away"] == pytest.approx(1.8)


def test_bookmaker_odds_default_outcomes_empty() -> None:
    now = datetime.now(tz=timezone.utc)
    record = BookmakerOdds(
        bookmaker="DraftKings",
        game_id="nfl_456",
        sport="NFL",
        league="NFL",
        home_team="Chiefs",
        away_team="Eagles",
        start_time=now,
        market_type="spreads",
    )
    assert record.outcomes == {}


def test_bookmaker_odds_three_way_market() -> None:
    now = datetime.now(tz=timezone.utc)
    record = BookmakerOdds(
        bookmaker="Caesars",
        game_id="epl_789",
        sport="soccer",
        league="EPL",
        home_team="Arsenal",
        away_team="Chelsea",
        start_time=now,
        market_type="moneyline",
        outcomes={"home": 2.9, "draw": 3.8, "away": 4.2},
    )
    assert len(record.outcomes) == 3
    assert "draw" in record.outcomes


# ---------------------------------------------------------------------------
# ArbitrageOpportunity
# ---------------------------------------------------------------------------

def _make_arb_opp() -> ArbitrageOpportunity:
    now = datetime.now(tz=timezone.utc)
    return ArbitrageOpportunity(
        game_id="arb_001",
        sport="NBA",
        league="NBA",
        home_team="Lakers",
        away_team="Celtics",
        start_time=now,
        market_type="moneyline",
        involved_books=["BookA", "BookB"],
        best_odds={"home": 3.1, "away": 2.5},
        best_odds_books={"home": "BookA", "away": "BookB"},
        implied_prob_sum=0.7226,
        edge_pct=27.74,
        stakes={"home": 32.26, "away": 40.0},
        expected_profit=19.0,
        expected_profit_pct=19.0,
    )


def test_arb_opportunity_construction() -> None:
    opp = _make_arb_opp()
    assert opp.game_id == "arb_001"
    assert opp.edge_pct == pytest.approx(27.74)
    assert opp.implied_prob_sum == pytest.approx(0.7226)
    assert "BookA" in opp.involved_books


def test_arb_opportunity_best_odds() -> None:
    opp = _make_arb_opp()
    assert opp.best_odds["home"] == pytest.approx(3.1)
    assert opp.best_odds_books["home"] == "BookA"


def test_arb_opportunity_stakes() -> None:
    opp = _make_arb_opp()
    assert "home" in opp.stakes
    assert "away" in opp.stakes


def test_arb_opportunity_start_time_future() -> None:
    """Confirm start_time can be set to a future datetime."""
    future = datetime.now(tz=timezone.utc) + timedelta(hours=3)
    opp = ArbitrageOpportunity(
        game_id="future_001",
        sport="NFL",
        league="NFL",
        home_team="Chiefs",
        away_team="Eagles",
        start_time=future,
        market_type="moneyline",
        involved_books=["BookA"],
        best_odds={"home": 2.0, "away": 2.1},
        best_odds_books={"home": "BookA", "away": "BookA"},
        implied_prob_sum=0.976,
        edge_pct=2.4,
        stakes={"home": 51.2, "away": 48.8},
        expected_profit=2.4,
        expected_profit_pct=2.4,
    )
    assert opp.start_time > datetime.now(tz=timezone.utc)
