"""Tests for src/sports_arb/trade_executor.py."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from sports_arb.models import ArbitrageOpportunity
from sports_arb.trade_executor import (
    PaperLeg,
    PaperPositionBook,
    _size_from_opportunity,
    execute_arb,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_arb_opp(game_id: str = "game_test_001") -> ArbitrageOpportunity:
    return ArbitrageOpportunity(
        game_id=game_id,
        sport="NBA",
        league="NBA",
        home_team="Lakers",
        away_team="Celtics",
        start_time=datetime.now(tz=UTC),
        market_type="moneyline",
        involved_books=["BookA", "BookB"],
        best_odds={"home": 3.1, "away": 1.909},
        best_odds_books={"home": "BookA", "away": "BookB"},
        implied_prob_sum=0.8462,
        edge_pct=15.38,
        stakes={"home": 38.11, "away": 61.89},
        expected_profit=18.15,
        expected_profit_pct=18.15,
    )


# ---------------------------------------------------------------------------
# PaperLeg
# ---------------------------------------------------------------------------


def test_paper_leg_fields() -> None:
    leg = PaperLeg(
        venue="BookA",
        market_id="game_001",
        outcome="home",
        side="BUY",
        price=3.1,
        size=10.0,
    )
    assert leg.venue == "BookA"
    assert leg.market_id == "game_001"
    assert leg.outcome == "home"
    assert leg.side == "BUY"
    assert leg.price == pytest.approx(3.1)
    assert leg.size == pytest.approx(10.0)


def test_paper_leg_sell_side() -> None:
    leg = PaperLeg(
        venue="BookB",
        market_id="game_002",
        outcome="away",
        side="SELL",
        price=1.909,
        size=5.0,
    )
    assert leg.side == "SELL"


# ---------------------------------------------------------------------------
# PaperPositionBook
# ---------------------------------------------------------------------------


def test_position_book_empty_summary() -> None:
    b = PaperPositionBook()
    assert b.summary() == "0 paper legs open"


def test_position_book_add_legs() -> None:
    b = PaperPositionBook()
    legs = [
        PaperLeg("BookA", "g1", "home", "BUY", 3.1, 10.0),
        PaperLeg("BookB", "g1", "away", "BUY", 1.909, 10.0),
    ]
    b.add_legs(legs)
    assert len(b.legs) == 2
    assert b.summary() == "2 paper legs open"


def test_position_book_add_legs_accumulates() -> None:
    b = PaperPositionBook()
    b.add_legs([PaperLeg("BookA", "g1", "home", "BUY", 3.1, 10.0)])
    b.add_legs([PaperLeg("BookB", "g1", "away", "BUY", 1.909, 10.0)])
    assert len(b.legs) == 2
    assert b.summary() == "2 paper legs open"


def test_position_book_summary_plural() -> None:
    b = PaperPositionBook()
    b.add_legs([PaperLeg("BookA", "g1", "home", "BUY", 3.1, 10.0)])
    assert b.summary() == "1 paper leg open"


# ---------------------------------------------------------------------------
# _size_from_opportunity
# ---------------------------------------------------------------------------


def test_size_from_opportunity_returns_fixed_stake() -> None:
    opp = _make_arb_opp()
    assert _size_from_opportunity(opp) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# execute_arb – AUTO_TRADE_ENABLED=false (default)
# ---------------------------------------------------------------------------


def test_execute_arb_disabled_logs_skip(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When AUTO_TRADE_ENABLED is false the book must not be modified."""
    import sports_arb.trade_executor as te

    fresh_book = PaperPositionBook()
    monkeypatch.setattr(te, "book", fresh_book)
    monkeypatch.setenv("AUTO_TRADE_ENABLED", "false")

    opp = _make_arb_opp()
    with caplog.at_level(logging.DEBUG, logger="sports_arb.trade_executor"):
        execute_arb(opp)

    assert len(fresh_book.legs) == 0
    assert "AUTO_TRADE_ENABLED is false" in caplog.text


@pytest.mark.parametrize("value", ["0", "no", "off", "FALSE", ""])
def test_execute_arb_disabled_various_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """Various falsy env strings must all skip execution."""
    import sports_arb.trade_executor as te

    fresh_book = PaperPositionBook()
    monkeypatch.setattr(te, "book", fresh_book)
    monkeypatch.setenv("AUTO_TRADE_ENABLED", value)

    execute_arb(_make_arb_opp())
    assert len(fresh_book.legs) == 0


# ---------------------------------------------------------------------------
# execute_arb – AUTO_TRADE_ENABLED=true
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "YES"])
def test_execute_arb_enabled_adds_legs(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """When enabled, one PaperLeg per outcome must be added to the book."""
    import sports_arb.trade_executor as te

    fresh_book = PaperPositionBook()
    monkeypatch.setattr(te, "book", fresh_book)
    monkeypatch.setenv("AUTO_TRADE_ENABLED", value)

    opp = _make_arb_opp()
    execute_arb(opp)

    # ArbitrageOpportunity has two outcomes: "home" and "away"
    assert len(fresh_book.legs) == 2


def test_execute_arb_enabled_leg_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Legs must be built from the ArbitrageOpportunity's real fields."""
    import sports_arb.trade_executor as te

    fresh_book = PaperPositionBook()
    monkeypatch.setattr(te, "book", fresh_book)
    monkeypatch.setenv("AUTO_TRADE_ENABLED", "true")

    opp = _make_arb_opp(game_id="game_test_042")
    execute_arb(opp)

    venues = {leg.venue for leg in fresh_book.legs}
    market_ids = {leg.market_id for leg in fresh_book.legs}
    sides = {leg.side for leg in fresh_book.legs}
    outcomes = {leg.outcome for leg in fresh_book.legs}

    assert venues == {"BookA", "BookB"}
    assert market_ids == {"game_test_042"}
    assert sides == {"BUY"}
    assert outcomes == {"home", "away"}


def test_execute_arb_enabled_logs_summary(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """After enabled execution, a summary line and per-leg lines must be logged."""
    import sports_arb.trade_executor as te

    fresh_book = PaperPositionBook()
    monkeypatch.setattr(te, "book", fresh_book)
    monkeypatch.setenv("AUTO_TRADE_ENABLED", "true")

    opp = _make_arb_opp()
    with caplog.at_level(logging.INFO, logger="sports_arb.trade_executor"):
        execute_arb(opp)

    assert "Executed PAPER arb" in caplog.text
    assert "PAPER" in caplog.text
    assert "BUY" in caplog.text


def test_execute_arb_enabled_size_is_fixed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each paper leg size must equal _size_from_opportunity (10.0)."""
    import sports_arb.trade_executor as te

    fresh_book = PaperPositionBook()
    monkeypatch.setattr(te, "book", fresh_book)
    monkeypatch.setenv("AUTO_TRADE_ENABLED", "true")

    execute_arb(_make_arb_opp())

    for leg in fresh_book.legs:
        assert leg.size == pytest.approx(10.0)


def test_execute_arb_enabled_price_matches_best_odds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each leg's price must match the corresponding best_odds entry."""
    import sports_arb.trade_executor as te

    fresh_book = PaperPositionBook()
    monkeypatch.setattr(te, "book", fresh_book)
    monkeypatch.setenv("AUTO_TRADE_ENABLED", "true")

    opp = _make_arb_opp()
    execute_arb(opp)

    prices = {leg.outcome: leg.price for leg in fresh_book.legs}
    assert prices["home"] == pytest.approx(opp.best_odds["home"])
    assert prices["away"] == pytest.approx(opp.best_odds["away"])


# ---------------------------------------------------------------------------
# PaperLeg – new pnl / closed fields
# ---------------------------------------------------------------------------


def test_paper_leg_defaults_pnl_and_closed() -> None:
    leg = PaperLeg("BookA", "g1", "home", "BUY", 3.1, 10.0)
    assert leg.pnl == pytest.approx(0.0)
    assert leg.closed is False


# ---------------------------------------------------------------------------
# PaperPositionBook – close_arb
# ---------------------------------------------------------------------------


def test_close_arb_marks_legs_closed() -> None:
    b = PaperPositionBook()
    legs = [
        PaperLeg("BookA", "g1", "home", "BUY", 3.1, 10.0),
        PaperLeg("BookB", "g1", "away", "BUY", 1.909, 10.0),
    ]
    b.add_legs(legs)
    b.close_arb(legs, profit=20.0)
    assert all(leg.closed for leg in legs)


def test_close_arb_splits_pnl_equally() -> None:
    b = PaperPositionBook()
    legs = [
        PaperLeg("BookA", "g1", "home", "BUY", 3.1, 10.0),
        PaperLeg("BookB", "g1", "away", "BUY", 1.909, 10.0),
    ]
    b.add_legs(legs)
    b.close_arb(legs, profit=20.0)
    for leg in legs:
        assert leg.pnl == pytest.approx(10.0)


def test_close_arb_updates_realized_pnl() -> None:
    b = PaperPositionBook()
    legs = [
        PaperLeg("BookA", "g1", "home", "BUY", 3.1, 10.0),
        PaperLeg("BookB", "g1", "away", "BUY", 1.909, 10.0),
    ]
    b.add_legs(legs)
    b.close_arb(legs, profit=18.15)
    assert b.realized_pnl == pytest.approx(18.15)


def test_close_arb_accumulates_realized_pnl() -> None:
    b = PaperPositionBook()
    legs1 = [PaperLeg("BookA", "g1", "home", "BUY", 3.1, 10.0)]
    legs2 = [PaperLeg("BookB", "g2", "away", "BUY", 1.909, 10.0)]
    b.add_legs(legs1)
    b.add_legs(legs2)
    b.close_arb(legs1, profit=10.0)
    b.close_arb(legs2, profit=5.0)
    assert b.realized_pnl == pytest.approx(15.0)


def test_close_arb_empty_legs_is_noop() -> None:
    b = PaperPositionBook()
    b.close_arb([], profit=10.0)
    assert b.realized_pnl == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# PaperPositionBook – stats
# ---------------------------------------------------------------------------


def test_stats_empty_book() -> None:
    b = PaperPositionBook()
    s = b.stats()
    assert s["open_legs"] == 0
    assert s["closed_legs"] == 0
    assert s["realized_pnl"] == pytest.approx(0.0)
    assert s["unrealized_pnl"] == pytest.approx(0.0)


def test_stats_open_and_closed_counts() -> None:
    b = PaperPositionBook()
    legs = [
        PaperLeg("BookA", "g1", "home", "BUY", 3.1, 10.0),
        PaperLeg("BookB", "g1", "away", "BUY", 1.909, 10.0),
    ]
    b.add_legs(legs)
    # Close only the first leg
    b.close_arb([legs[0]], profit=5.0)
    s = b.stats()
    assert s["open_legs"] == 1
    assert s["closed_legs"] == 1


def test_stats_realized_pnl_after_close() -> None:
    b = PaperPositionBook()
    legs = [PaperLeg("BookA", "g1", "home", "BUY", 3.1, 10.0)]
    b.add_legs(legs)
    b.close_arb(legs, profit=18.15)
    assert b.stats()["realized_pnl"] == pytest.approx(18.15)


# ---------------------------------------------------------------------------
# execute_arb – PnL tracking when enabled
# ---------------------------------------------------------------------------


def test_execute_arb_closes_legs_after_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    """All legs must be closed immediately after execute_arb."""
    import sports_arb.trade_executor as te

    fresh_book = PaperPositionBook()
    monkeypatch.setattr(te, "book", fresh_book)
    monkeypatch.setenv("AUTO_TRADE_ENABLED", "true")

    execute_arb(_make_arb_opp())

    assert all(leg.closed for leg in fresh_book.legs)


def test_execute_arb_records_realized_pnl(monkeypatch: pytest.MonkeyPatch) -> None:
    """execute_arb must add opp.expected_profit to realized_pnl."""
    import sports_arb.trade_executor as te

    fresh_book = PaperPositionBook()
    monkeypatch.setattr(te, "book", fresh_book)
    monkeypatch.setenv("AUTO_TRADE_ENABLED", "true")

    opp = _make_arb_opp()
    execute_arb(opp)

    assert fresh_book.realized_pnl == pytest.approx(opp.expected_profit)
