"""Tests for src/sports_arb/arb_engine.py."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sports_arb.arb_engine import (
    american_to_decimal,
    compute_expected_profit,
    compute_implied_prob_sum,
    compute_stakes,
    decimal_to_implied_prob,
    detect_arbitrage,
    find_best_odds,
    fractional_to_decimal,
)
from sports_arb.models import BookmakerOdds

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_odds(
    bookmaker: str,
    game_id: str,
    market_type: str,
    outcomes: dict[str, float],
    sport: str = "NBA",
    league: str = "NBA",
    home: str = "Team A",
    away: str = "Team B",
) -> BookmakerOdds:
    return BookmakerOdds(
        bookmaker=bookmaker,
        game_id=game_id,
        sport=sport,
        league=league,
        home_team=home,
        away_team=away,
        start_time=_now(),
        market_type=market_type,
        outcomes=outcomes,
    )


# ---------------------------------------------------------------------------
# Odds conversion tests
# ---------------------------------------------------------------------------

def test_american_to_decimal_positive() -> None:
    assert american_to_decimal(150) == pytest.approx(2.5)


def test_american_to_decimal_negative() -> None:
    assert american_to_decimal(-110) == pytest.approx(100 / 110 + 1, rel=1e-6)


def test_american_to_decimal_even() -> None:
    assert american_to_decimal(100) == pytest.approx(2.0)


def test_fractional_to_decimal() -> None:
    assert fractional_to_decimal(3, 1) == pytest.approx(4.0)


def test_fractional_to_decimal_half() -> None:
    assert fractional_to_decimal(1, 2) == pytest.approx(1.5)


def test_fractional_to_decimal_zero_denominator() -> None:
    with pytest.raises(ValueError):
        fractional_to_decimal(3, 0)


def test_decimal_to_implied_prob() -> None:
    assert decimal_to_implied_prob(2.0) == pytest.approx(0.5)


def test_decimal_to_implied_prob_quarter() -> None:
    assert decimal_to_implied_prob(4.0) == pytest.approx(0.25)


def test_decimal_to_implied_prob_invalid() -> None:
    with pytest.raises(ValueError):
        decimal_to_implied_prob(0.0)


# ---------------------------------------------------------------------------
# find_best_odds
# ---------------------------------------------------------------------------

def test_find_best_odds_returns_best_per_outcome() -> None:
    """Given two books with different odds on the same game, pick the highest."""
    records = [
        _make_odds("BookA", "g1", "moneyline", {"home": 2.0, "away": 1.8}),
        _make_odds("BookB", "g1", "moneyline", {"home": 1.9, "away": 2.1}),
    ]
    best = find_best_odds(records, "g1", "moneyline")

    assert best["home"] == (2.0, "BookA")
    assert best["away"] == (2.1, "BookB")


def test_find_best_odds_ignores_other_games() -> None:
    records = [
        _make_odds("BookA", "g1", "moneyline", {"home": 2.0, "away": 1.8}),
        _make_odds("BookA", "g2", "moneyline", {"home": 3.0, "away": 3.0}),
    ]
    best = find_best_odds(records, "g1", "moneyline")
    assert set(best.keys()) == {"home", "away"}


def test_find_best_odds_no_match() -> None:
    records = [
        _make_odds("BookA", "g1", "moneyline", {"home": 2.0, "away": 1.8}),
    ]
    assert find_best_odds(records, "g99", "moneyline") == {}


# ---------------------------------------------------------------------------
# compute_implied_prob_sum
# ---------------------------------------------------------------------------

def test_compute_implied_prob_sum_arb_exists() -> None:
    """With odds that cross-book create an arb, the IP sum should be < 1."""
    best: dict[str, tuple[float, str]] = {
        "home": (3.1, "BookC"),
        "away": (1.909, "BookB"),
    }
    ip_sum = compute_implied_prob_sum(best)
    assert ip_sum < 1.0


def test_compute_implied_prob_sum_no_arb() -> None:
    """Standard vig odds should produce IP sum >= 1."""
    best: dict[str, tuple[float, str]] = {
        "home": (1.909, "BookA"),   # −110
        "away": (1.909, "BookB"),   # −110
    }
    ip_sum = compute_implied_prob_sum(best)
    assert ip_sum > 1.0


# ---------------------------------------------------------------------------
# compute_stakes
# ---------------------------------------------------------------------------

def test_compute_stakes_sum_to_bankroll() -> None:
    """Total stakes must equal the bankroll exactly."""
    bankroll = 100.0
    best: dict[str, tuple[float, str]] = {
        "home": (3.1, "BookC"),
        "away": (1.909, "BookB"),
    }
    stakes = compute_stakes(best, bankroll=bankroll)
    assert sum(stakes.values()) == pytest.approx(bankroll, rel=1e-9)


def test_compute_stakes_equal_payout() -> None:
    """Each leg should return the same gross payout."""
    bankroll = 100.0
    best: dict[str, tuple[float, str]] = {
        "home": (3.1, "BookC"),
        "away": (1.909, "BookB"),
    }
    stakes = compute_stakes(best, bankroll=bankroll)
    payouts = [stakes[o] * odds for o, (odds, _) in best.items()]
    # All payouts should be equal
    assert payouts[0] == pytest.approx(payouts[1], rel=1e-6)


def test_compute_stakes_three_outcomes() -> None:
    """Works correctly for 3-way markets (e.g. soccer)."""
    bankroll = 100.0
    best: dict[str, tuple[float, str]] = {
        "home": (2.9, "BookA"),
        "draw": (3.8, "BookC"),
        "away": (4.2, "BookB"),
    }
    stakes = compute_stakes(best, bankroll=bankroll)
    assert sum(stakes.values()) == pytest.approx(bankroll, rel=1e-9)


# ---------------------------------------------------------------------------
# detect_arbitrage
# ---------------------------------------------------------------------------

def _arb_records() -> list[BookmakerOdds]:
    """Returns two BookmakerOdds records with a clear arb (IP sum < 0.98)."""
    return [
        _make_odds("BookA", "arb_game", "moneyline", {"home": 3.1, "away": 1.6}),
        _make_odds("BookB", "arb_game", "moneyline", {"home": 2.0, "away": 2.5}),
    ]
    # Best: home=3.1 (A), away=2.5 (B)
    # IP sum = 1/3.1 + 1/2.5 = 0.3226 + 0.4000 = 0.7226  << clear arb


def _no_arb_records() -> list[BookmakerOdds]:
    """Returns records with standard vig – no arbitrage."""
    return [
        _make_odds("BookA", "no_arb_game", "moneyline", {"home": 1.909, "away": 1.909}),
        _make_odds("BookB", "no_arb_game", "moneyline", {"home": 1.870, "away": 1.952}),
    ]
    # Best: home=1.909, away=1.952
    # IP sum ≈ 0.5236 + 0.5123 = 1.036 → no arb


def test_detect_arbitrage_finds_opportunity() -> None:
    opps = detect_arbitrage(_arb_records(), threshold=0.98)
    assert len(opps) >= 1
    assert opps[0].game_id == "arb_game"
    assert opps[0].implied_prob_sum < 0.98
    assert opps[0].edge_pct > 0


def test_detect_arbitrage_no_opportunity() -> None:
    opps = detect_arbitrage(_no_arb_records(), threshold=0.98)
    assert opps == []


def test_detect_arbitrage_threshold() -> None:
    """Lowering the threshold to below the existing arb edge hides it."""
    # IP sum ≈ 0.7226 → edge ≈ 27.7%.  Use a threshold of 0.75 so that
    # 0.7226 < 0.75 still reports it; then use 0.70 so it disappears.
    opps_found = detect_arbitrage(_arb_records(), threshold=0.75)
    assert len(opps_found) >= 1

    # Threshold lower than the IP sum → no opportunities surfaced
    opps_none = detect_arbitrage(_arb_records(), threshold=0.70)
    assert opps_none == []


def test_detect_arbitrage_sorted_by_edge_desc() -> None:
    """Multiple arb opps should come back ordered best-first."""
    small_arb = [
        _make_odds("BookA", "small_arb", "moneyline", {"home": 2.05, "away": 2.05}),
    ]
    # IP sum = 2 * 1/2.05 ≈ 0.9756
    large_arb = _arb_records()

    opps = detect_arbitrage(small_arb + large_arb, threshold=0.98)
    assert len(opps) == 2
    assert opps[0].edge_pct >= opps[1].edge_pct


def test_detect_arbitrage_stake_sum_equals_bankroll() -> None:
    """Stakes returned in an opportunity should sum to the requested bankroll."""
    bankroll = 500.0
    opps = detect_arbitrage(_arb_records(), threshold=0.98, bankroll=bankroll)
    assert opps
    assert sum(opps[0].stakes.values()) == pytest.approx(bankroll, rel=1e-9)


def test_compute_expected_profit_positive_for_arb() -> None:
    best: dict[str, tuple[float, str]] = {
        "home": (3.1, "BookA"),
        "away": (2.5, "BookB"),
    }
    stakes = compute_stakes(best, bankroll=100.0)
    profit, pct = compute_expected_profit(best, stakes)
    assert profit > 0
    assert pct > 0
