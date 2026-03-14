"""Tests for the pregame / live scanner filtering logic and mode-specific thresholds.

These tests validate:
- :func:`~sports_arb.scanner.filter_pregame` correctly excludes games that have
  already started or are starting within the buffer window.
- :func:`~sports_arb.scanner.filter_live` correctly selects only games that have
  already started.
- The pregame and live modes use different arb thresholds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sports_arb.config import (
    LIVE_ARB_THRESHOLD,
    PREGAME_ARB_THRESHOLD,
    PREGAME_BUFFER_MINUTES,
)
from sports_arb.models import BookmakerOdds
from sports_arb.scanner import filter_live, filter_pregame

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_odds(start_time: datetime, game_id: str = "test_game") -> BookmakerOdds:
    """Create a minimal :class:`BookmakerOdds` record with the given start_time."""
    return BookmakerOdds(
        bookmaker="TestBook",
        game_id=game_id,
        sport="NBA",
        league="NBA",
        home_team="Team A",
        away_team="Team B",
        start_time=start_time,
        market_type="moneyline",
        outcomes={"home": 2.0, "away": 2.0},
    )


def _now() -> datetime:
    return datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# filter_pregame tests
# ---------------------------------------------------------------------------


class TestFilterPregame:
    """Tests for filter_pregame() – selects upcoming games only."""

    def test_future_game_included(self) -> None:
        """A game starting well in the future should be included."""
        record = _make_odds(start_time=_now() + timedelta(hours=3))
        result = filter_pregame([record])
        assert result == [record]

    def test_past_game_excluded(self) -> None:
        """A game that has already started should be excluded."""
        record = _make_odds(start_time=_now() - timedelta(minutes=10))
        result = filter_pregame([record])
        assert result == []

    def test_game_within_buffer_excluded(self) -> None:
        """A game starting within the default buffer window should be excluded."""
        record = _make_odds(start_time=_now() + timedelta(minutes=PREGAME_BUFFER_MINUTES - 1))
        result = filter_pregame([record], buffer_minutes=PREGAME_BUFFER_MINUTES)
        assert result == []

    def test_game_just_outside_buffer_included(self) -> None:
        """A game starting slightly beyond the buffer window should be included."""
        record = _make_odds(start_time=_now() + timedelta(minutes=PREGAME_BUFFER_MINUTES + 2))
        result = filter_pregame([record], buffer_minutes=PREGAME_BUFFER_MINUTES)
        assert result == [record]

    def test_custom_buffer(self) -> None:
        """Custom buffer_minutes is respected."""
        record = _make_odds(start_time=_now() + timedelta(minutes=15))
        # With a 20-minute buffer the game should be excluded
        assert filter_pregame([record], buffer_minutes=20) == []
        # With a 10-minute buffer the same game should be included
        assert filter_pregame([record], buffer_minutes=10) == [record]

    def test_empty_list(self) -> None:
        """An empty input list returns an empty list."""
        assert filter_pregame([]) == []

    def test_mixed_list_only_future_returned(self) -> None:
        """Only future games (beyond buffer) appear in the output."""
        future = _make_odds(start_time=_now() + timedelta(hours=2), game_id="future")
        past = _make_odds(start_time=_now() - timedelta(hours=1), game_id="past")
        soon = _make_odds(
            start_time=_now() + timedelta(minutes=2), game_id="soon"
        )  # within default buffer
        result = filter_pregame([future, past, soon])
        assert result == [future]


# ---------------------------------------------------------------------------
# filter_live tests
# ---------------------------------------------------------------------------


class TestFilterLive:
    """Tests for filter_live() – selects in-progress games only."""

    def test_started_game_included(self) -> None:
        """A game that has already started should be included."""
        record = _make_odds(start_time=_now() - timedelta(minutes=30))
        result = filter_live([record])
        assert result == [record]

    def test_future_game_excluded(self) -> None:
        """A game that has not started yet should be excluded."""
        record = _make_odds(start_time=_now() + timedelta(hours=1))
        result = filter_live([record])
        assert result == []

    def test_game_starting_now_included(self) -> None:
        """A game whose start_time equals *now* (within a millisecond) is included."""
        record = _make_odds(start_time=_now() - timedelta(milliseconds=1))
        result = filter_live([record])
        assert result == [record]

    def test_empty_list(self) -> None:
        """An empty input list returns an empty list."""
        assert filter_live([]) == []

    def test_mixed_list_only_live_returned(self) -> None:
        """Only games that have started appear in the output."""
        live = _make_odds(start_time=_now() - timedelta(minutes=10), game_id="live")
        upcoming = _make_odds(start_time=_now() + timedelta(hours=1), game_id="upcoming")
        result = filter_live([live, upcoming])
        assert result == [live]


# ---------------------------------------------------------------------------
# Mode threshold differentiation tests
# ---------------------------------------------------------------------------


class TestModeThresholds:
    """Tests confirming pregame and live modes use different arb thresholds."""

    def test_pregame_threshold_less_strict(self) -> None:
        """Pre-game threshold is less strict (higher) than live threshold."""
        assert PREGAME_ARB_THRESHOLD > LIVE_ARB_THRESHOLD, (
            f"Expected PREGAME_ARB_THRESHOLD ({PREGAME_ARB_THRESHOLD}) "
            f"> LIVE_ARB_THRESHOLD ({LIVE_ARB_THRESHOLD})"
        )

    def test_pregame_threshold_value(self) -> None:
        """Pre-game threshold defaults to 0.98 (2% edge)."""
        assert PREGAME_ARB_THRESHOLD == pytest.approx(0.98)

    def test_live_threshold_value(self) -> None:
        """Live threshold defaults to 0.96 (4% edge, tighter than pregame)."""
        assert LIVE_ARB_THRESHOLD == pytest.approx(0.96)

    def test_pregame_and_live_thresholds_differ(self) -> None:
        """The two thresholds must not be equal."""
        assert PREGAME_ARB_THRESHOLD != LIVE_ARB_THRESHOLD
