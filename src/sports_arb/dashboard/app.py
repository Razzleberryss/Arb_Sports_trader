"""Flask + Flask-SocketIO dashboard for the sports arbitrage scanner.

Run with::

    python -m sports_arb.dashboard.app

The server starts on port 5000 and emits ``new_opportunity`` SocketIO events
whenever :func:`emit_opportunity` is called by the scanner.

Educational use only – no real betting logic.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any

from flask import Flask, jsonify, render_template
from flask_socketio import SocketIO

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------

#: Circular buffer of the last 50 opportunities (newest at index 0 via appendleft).
_opportunity_cache: deque[dict[str, Any]] = deque(maxlen=50)

#: Daily stats – reset whenever the date changes.
_stats: dict[str, Any] = {
    "date": datetime.now(tz=UTC).date().isoformat(),
    "total_today": 0,
    "edge_sum": 0.0,
    "best_edge": 0.0,
    "scanner_running": False,
}

# ---------------------------------------------------------------------------
# Flask / SocketIO setup
# ---------------------------------------------------------------------------

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "arb-dashboard-secret"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _opp_to_dict(opp: Any, opp_type: str) -> dict[str, Any]:
    """Serialise an :class:`~sports_arb.models.ArbitrageOpportunity` to a plain dict."""
    # Compute profit on a $100 stake from best_odds and implied_prob_sum.
    best_home_odds: float | None = None
    best_away_odds: float | None = None
    home_book: str = ""
    away_book: str = ""

    odds = getattr(opp, "best_odds", {})
    books = getattr(opp, "best_odds_books", {})

    if "home" in odds:
        best_home_odds = odds["home"]
        home_book = books.get("home", "")
    if "away" in odds:
        best_away_odds = odds["away"]
        away_book = books.get("away", "")

    profit_on_100 = round(getattr(opp, "expected_profit_pct", 0.0), 2)

    return {
        "type": opp_type.upper(),
        "game": f"{opp.home_team} vs {opp.away_team}",
        "league": opp.league,
        "sport": opp.sport,
        "edge_pct": round(opp.edge_pct, 2),
        "profit_on_100": profit_on_100,
        "book1_odds": best_home_odds,
        "book2_odds": best_away_odds,
        "book1_name": home_book,
        "book2_name": away_book,
        "detected_at": datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


def _reset_stats_if_new_day() -> None:
    """Reset daily counters when the UTC date has rolled over."""
    today = datetime.now(tz=UTC).date().isoformat()
    if _stats["date"] != today:
        _stats["date"] = today
        _stats["total_today"] = 0
        _stats["edge_sum"] = 0.0
        _stats["best_edge"] = 0.0


# ---------------------------------------------------------------------------
# Public API consumed by scanner.py
# ---------------------------------------------------------------------------


def emit_opportunity(opp: Any, opp_type: str) -> None:
    """Add *opp* to the cache and broadcast it to all connected clients.

    Parameters
    ----------
    opp:
        An :class:`~sports_arb.models.ArbitrageOpportunity` instance.
    opp_type:
        ``"live"`` or ``"pregame"``.
    """
    _reset_stats_if_new_day()

    data = _opp_to_dict(opp, opp_type)

    # Update cache (deque enforces maxlen=50 automatically).
    _opportunity_cache.appendleft(data)

    # Update daily stats.
    _stats["total_today"] += 1
    _stats["edge_sum"] += opp.edge_pct
    if opp.edge_pct > _stats["best_edge"]:
        _stats["best_edge"] = opp.edge_pct

    # Emit via SocketIO (no-op if no clients are connected).
    try:
        socketio.emit("new_opportunity", data)
    except Exception as exc:  # noqa: BLE001
        logger.debug("SocketIO emit skipped: %s", exc)


def set_scanner_running(running: bool) -> None:
    """Update the scanner-running status flag shown in the dashboard."""
    _stats["scanner_running"] = running


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.route("/")
def index() -> str:
    """Serve the single-page dashboard."""
    return render_template("index.html")


@app.route("/api/opportunities")
def api_opportunities():
    """Return the latest cached arbitrage opportunities as JSON.

    Returns at most 50 entries (newest first).
    """
    return jsonify(list(_opportunity_cache))


@app.route("/api/stats")
def api_stats():
    """Return daily scanner statistics."""
    _reset_stats_if_new_day()
    total = _stats["total_today"]
    avg_edge = round(_stats["edge_sum"] / total, 2) if total > 0 else 0.0
    return jsonify(
        {
            "total_today": total,
            "avg_edge_pct": avg_edge,
            "best_edge_today": round(_stats["best_edge"], 2),
            "scanner_status": "running" if _stats["scanner_running"] else "stopped",
        }
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
