"""APScheduler-based launcher for the sports arbitrage scanner.

Automatically:
- Starts the **pre-game** scanner 2 hours before the earliest game
  currently listed by the configured odds providers.
- Starts the **live** scanner as soon as the earliest game goes live
  (i.e. its ``start_time`` arrives).

Usage
-----
    python scripts/schedule.py

Requires ``apscheduler>=3.10`` (included in the optional ``[scheduler]``
dependency group or install separately):

    pip install apscheduler

DISCLAIMER: This software is for educational purposes only.  It does not
constitute financial advice and must not be used to place real wagers.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime, timedelta

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.date import DateTrigger
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "APScheduler is required for scripts/schedule.py.\n"
        "Install it with:  pip install apscheduler"
    ) from exc

from sports_arb.config import (
    LIVE_ALERT_THRESHOLD_PCT,
    LIVE_ARB_THRESHOLD,
    LIVE_INTERVAL_SECONDS,
    LIVE_LOG_FILE,
    PREGAME_ARB_THRESHOLD,
    PREGAME_BUFFER_MINUTES,
    PREGAME_INTERVAL_SECONDS,
    PREGAME_LOG_FILE,
)
from sports_arb.odds_providers import PROVIDER_REGISTRY
from sports_arb.scanner import start_live_loop, start_pregame_loop

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _earliest_start_time() -> datetime | None:
    """Return the earliest ``start_time`` across all providers, or *None*."""
    all_odds = []
    for provider_cls in PROVIDER_REGISTRY.values():
        try:
            all_odds.extend(provider_cls().get_current_odds())
        except Exception:  # noqa: BLE001
            pass
    if not all_odds:
        return None
    return min(r.start_time for r in all_odds)


def _start_pregame_thread(bankroll: float = 100.0) -> None:
    """Launch the pre-game scanner loop in a background thread."""
    t = threading.Thread(
        target=start_pregame_loop,
        kwargs={
            "bankroll": bankroll,
            "threshold": PREGAME_ARB_THRESHOLD,
            "buffer_minutes": PREGAME_BUFFER_MINUTES,
            "interval_seconds": PREGAME_INTERVAL_SECONDS,
            "log_file": PREGAME_LOG_FILE,
        },
        daemon=True,
        name="pregame-scanner",
    )
    t.start()
    print(f"[schedule] Pre-game scanner started at {datetime.now(tz=UTC).isoformat()}")


def _start_live_thread(bankroll: float = 100.0) -> None:
    """Launch the live scanner loop in a background thread (with its own event loop)."""

    def _run() -> None:
        asyncio.run(
            start_live_loop(
                bankroll=bankroll,
                threshold=LIVE_ARB_THRESHOLD,
                interval_seconds=LIVE_INTERVAL_SECONDS,
                log_file=LIVE_LOG_FILE,
                alert_threshold_pct=LIVE_ALERT_THRESHOLD_PCT,
            )
        )

    t = threading.Thread(target=_run, daemon=True, name="live-scanner")
    t.start()
    print(f"[schedule] Live scanner started at {datetime.now(tz=UTC).isoformat()}")


# ---------------------------------------------------------------------------
# Main scheduler entry point
# ---------------------------------------------------------------------------


def main(bankroll: float = 100.0) -> None:  # pragma: no cover
    """Determine start times from live provider data and schedule both scanners.

    The pre-game scanner starts 2 hours before the first listed game;
    the live scanner starts exactly when the first game begins.
    """
    now = datetime.now(tz=UTC)
    earliest = _earliest_start_time()

    if earliest is None:
        print("[schedule] No games found from providers – starting pre-game scanner immediately.")
        pregame_start = now
        live_start = now + timedelta(hours=2)  # fallback: 2 h from now
    else:
        pregame_start = earliest - timedelta(hours=2)
        live_start = earliest

        if pregame_start < now:
            print(
                f"[schedule] Pre-game window already started "
                f"(first game: {earliest.isoformat()}). Starting immediately."
            )
            pregame_start = now

        if live_start < now:
            print(
                f"[schedule] First game already live ({earliest.isoformat()}). "
                "Starting live scanner immediately."
            )
            live_start = now

    print(f"[schedule] First game: {earliest.isoformat() if earliest else 'unknown'}")
    print(f"[schedule] Pre-game scanner scheduled for: {pregame_start.isoformat()}")
    print(f"[schedule] Live scanner scheduled for:     {live_start.isoformat()}")

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _start_pregame_thread,
        trigger=DateTrigger(run_date=pregame_start),
        kwargs={"bankroll": bankroll},
        id="pregame",
    )
    scheduler.add_job(
        _start_live_thread,
        trigger=DateTrigger(run_date=live_start),
        kwargs={"bankroll": bankroll},
        id="live",
    )
    scheduler.start()
    print("[schedule] Scheduler running. Press Ctrl-C to exit.")

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("\n[schedule] Scheduler stopped.")


if __name__ == "__main__":
    main()
