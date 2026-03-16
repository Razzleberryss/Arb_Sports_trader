"""Tests for the sports_arb dashboard (app.py).

Covers:
- GET /api/opportunities returns correct JSON structure
- GET /api/stats returns correct structure and values
- emit_opportunity adds to cache and updates stats
- SocketIO 'new_opportunity' event is emitted when emit_opportunity is called
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

# Import the module under test *after* any patches so the module-level state
# is clean for each test class / function that resets it.
from sports_arb.dashboard.app import (
    _opportunity_cache,
    _stats,
    app,
    emit_opportunity,
    set_scanner_running,
    socketio,
)
from sports_arb.models import ArbitrageOpportunity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_opp(
    edge_pct: float = 3.5,
    home_team: str = "Team A",
    away_team: str = "Team B",
    league: str = "NBA",
    sport: str = "NBA",
    profit_pct: float = 3.5,
) -> ArbitrageOpportunity:
    """Return a minimal ArbitrageOpportunity for testing."""
    return ArbitrageOpportunity(
        game_id="test_game_001",
        sport=sport,
        league=league,
        home_team=home_team,
        away_team=away_team,
        start_time=datetime.now(tz=UTC),
        market_type="moneyline",
        involved_books=["BookA", "BookB"],
        best_odds={"home": 2.1, "away": 2.05},
        best_odds_books={"home": "BookA", "away": "BookB"},
        implied_prob_sum=0.965,
        edge_pct=edge_pct,
        stakes={"home": 48.0, "away": 52.0},
        expected_profit=3.50,
        expected_profit_pct=profit_pct,
    )


@pytest.fixture(autouse=True)
def reset_dashboard_state():
    """Clear in-memory cache and reset stats before every test."""
    _opportunity_cache.clear()
    _stats["date"] = datetime.now(tz=UTC).date().isoformat()
    _stats["total_today"] = 0
    _stats["edge_sum"] = 0.0
    _stats["best_edge"] = 0.0
    _stats["scanner_running"] = False
    yield


@pytest.fixture()
def client():
    """Return a Flask test client with testing mode enabled."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# /api/opportunities
# ---------------------------------------------------------------------------


class TestApiOpportunities:
    """Tests for GET /api/opportunities."""

    def test_empty_cache_returns_empty_list(self, client) -> None:
        resp = client.get("/api/opportunities")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == []

    def test_returns_list_type(self, client) -> None:
        emit_opportunity(_make_opp(), "pregame")
        resp = client.get("/api/opportunities")
        assert resp.status_code == 200
        assert isinstance(resp.get_json(), list)

    def test_opportunity_structure(self, client) -> None:
        opp = _make_opp(edge_pct=4.2, home_team="Lakers", away_team="Celtics")
        emit_opportunity(opp, "live")
        resp = client.get("/api/opportunities")
        data = resp.get_json()
        assert len(data) == 1
        item = data[0]
        assert item["type"] == "LIVE"
        assert item["game"] == "Lakers vs Celtics"
        assert item["league"] == "NBA"
        assert item["edge_pct"] == pytest.approx(4.2, abs=0.01)
        assert "profit_on_100" in item
        assert "book1_odds" in item
        assert "book2_odds" in item
        assert "detected_at" in item

    def test_newest_first_ordering(self, client) -> None:
        emit_opportunity(_make_opp(edge_pct=1.0, home_team="Alpha", away_team="Beta"), "pregame")
        emit_opportunity(_make_opp(edge_pct=2.0, home_team="Gamma", away_team="Delta"), "live")
        resp = client.get("/api/opportunities")
        data = resp.get_json()
        assert len(data) == 2
        # Most recently added (edge=2.0 / Gamma) should appear first
        assert data[0]["edge_pct"] == pytest.approx(2.0, abs=0.01)
        assert data[1]["edge_pct"] == pytest.approx(1.0, abs=0.01)

    def test_max_50_entries(self, client) -> None:
        for i in range(60):
            emit_opportunity(_make_opp(edge_pct=float(i)), "pregame")
        resp = client.get("/api/opportunities")
        data = resp.get_json()
        assert len(data) <= 50

    def test_pregame_type_badge(self, client) -> None:
        emit_opportunity(_make_opp(), "pregame")
        resp = client.get("/api/opportunities")
        data = resp.get_json()
        assert data[0]["type"] == "PREGAME"


# ---------------------------------------------------------------------------
# /api/stats
# ---------------------------------------------------------------------------


class TestApiStats:
    """Tests for GET /api/stats."""

    def test_empty_stats_structure(self, client) -> None:
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_today" in data
        assert "avg_edge_pct" in data
        assert "best_edge_today" in data
        assert "scanner_status" in data

    def test_initial_stats_values(self, client) -> None:
        resp = client.get("/api/stats")
        data = resp.get_json()
        assert data["total_today"] == 0
        assert data["avg_edge_pct"] == 0.0
        assert data["best_edge_today"] == 0.0
        assert data["scanner_status"] == "stopped"

    def test_total_increments(self, client) -> None:
        emit_opportunity(_make_opp(edge_pct=3.0), "live")
        emit_opportunity(_make_opp(edge_pct=5.0), "pregame")
        resp = client.get("/api/stats")
        data = resp.get_json()
        assert data["total_today"] == 2

    def test_avg_edge_accuracy(self, client) -> None:
        emit_opportunity(_make_opp(edge_pct=2.0), "live")
        emit_opportunity(_make_opp(edge_pct=4.0), "live")
        resp = client.get("/api/stats")
        data = resp.get_json()
        assert data["avg_edge_pct"] == pytest.approx(3.0, abs=0.01)

    def test_best_edge_tracked(self, client) -> None:
        emit_opportunity(_make_opp(edge_pct=1.5), "live")
        emit_opportunity(_make_opp(edge_pct=7.8), "live")
        emit_opportunity(_make_opp(edge_pct=3.2), "pregame")
        resp = client.get("/api/stats")
        data = resp.get_json()
        assert data["best_edge_today"] == pytest.approx(7.8, abs=0.01)

    def test_scanner_running_flag(self, client) -> None:
        set_scanner_running(True)
        resp = client.get("/api/stats")
        assert resp.get_json()["scanner_status"] == "running"

    def test_scanner_stopped_flag(self, client) -> None:
        set_scanner_running(False)
        resp = client.get("/api/stats")
        assert resp.get_json()["scanner_status"] == "stopped"


# ---------------------------------------------------------------------------
# emit_opportunity
# ---------------------------------------------------------------------------


class TestEmitOpportunity:
    """Tests for the emit_opportunity() helper."""

    def test_adds_to_cache(self) -> None:
        assert len(_opportunity_cache) == 0
        emit_opportunity(_make_opp(), "live")
        assert len(_opportunity_cache) == 1

    def test_updates_total(self) -> None:
        emit_opportunity(_make_opp(edge_pct=2.5), "live")
        assert _stats["total_today"] == 1

    def test_updates_best_edge(self) -> None:
        emit_opportunity(_make_opp(edge_pct=2.0), "pregame")
        emit_opportunity(_make_opp(edge_pct=6.0), "live")
        assert _stats["best_edge"] == pytest.approx(6.0, abs=0.01)

    def test_socketio_emit_called(self) -> None:
        """Verify that socketio.emit is invoked once per opportunity."""
        with patch.object(socketio, "emit") as mock_emit:
            opp = _make_opp(edge_pct=3.0, home_team="X", away_team="Y")
            emit_opportunity(opp, "live")
            mock_emit.assert_called_once()
            event_name, payload = mock_emit.call_args[0]
            assert event_name == "new_opportunity"
            assert payload["type"] == "LIVE"
            assert payload["game"] == "X vs Y"

    def test_socketio_emit_failure_is_non_blocking(self) -> None:
        """If socketio.emit raises, emit_opportunity must not propagate the error."""
        with patch.object(socketio, "emit", side_effect=RuntimeError("socket down")):
            # Should not raise
            emit_opportunity(_make_opp(), "pregame")
        # Cache and stats should still be updated despite the emit error
        assert len(_opportunity_cache) == 1
        assert _stats["total_today"] == 1

    def test_opp_type_normalised_to_upper(self) -> None:
        emit_opportunity(_make_opp(), "pregame")
        assert _opportunity_cache[0]["type"] == "PREGAME"

    def test_profit_on_100_present(self) -> None:
        opp = _make_opp(profit_pct=3.5)
        emit_opportunity(opp, "live")
        assert _opportunity_cache[0]["profit_on_100"] == pytest.approx(3.5, abs=0.01)


# ---------------------------------------------------------------------------
# Index page
# ---------------------------------------------------------------------------


class TestIndexPage:
    """Smoke test for the HTML dashboard page."""

    def test_index_returns_200(self, client) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Arb Sports Trader" in resp.data


# ---------------------------------------------------------------------------
# /api/paper_stats
# ---------------------------------------------------------------------------


class TestApiPaperStats:
    """Tests for GET /api/paper_stats."""

    def test_returns_200(self, client) -> None:
        resp = client.get("/api/paper_stats")
        assert resp.status_code == 200

    def test_initial_structure(self, client) -> None:
        resp = client.get("/api/paper_stats")
        data = resp.get_json()
        assert "open_legs" in data
        assert "closed_legs" in data
        assert "realized_pnl" in data
        assert "unrealized_pnl" in data

    def test_reflects_paper_book_state(self, client) -> None:
        """Verify the endpoint reflects live paper_book stats."""
        from sports_arb.trade_executor import book as paper_book

        # Stats should be consistent (may be non-zero if other tests ran,
        # but structure must always be present and numeric).
        resp = client.get("/api/paper_stats")
        data = resp.get_json()
        expected = paper_book.stats()
        assert data["realized_pnl"] == pytest.approx(expected["realized_pnl"])
        assert data["open_legs"] == expected["open_legs"]
        assert data["closed_legs"] == expected["closed_legs"]
