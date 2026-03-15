"""Pre-game and live/in-play arbitrage scanner logic.

Two distinct run modes are supported:

``pregame``
    Polls on a slow interval (default 5 min).  Only considers games whose
    :attr:`~sports_arb.models.BookmakerOdds.start_time` is *in the future*
    by more than a configurable buffer (default 5 min).

``live``
    Polls on a fast interval (default 30 s).  Only considers games whose
    :attr:`~sports_arb.models.BookmakerOdds.start_time` is *in the past*
    (i.e. already started).  Uses ``asyncio``/``httpx`` for concurrent
    provider fetches.  Applies a tighter arb threshold (default 0.96).

DISCLAIMER: This software is for educational purposes only.  It does not
constitute financial advice and must not be used to place real wagers.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import UTC, datetime, timedelta

from sports_arb.alerts.telegram import send_arb_alert, send_pregame_alert_sync
from sports_arb.arb_engine import detect_arbitrage
from sports_arb.config import (
    ALERT_THRESHOLD_LIVE,
    ALERT_THRESHOLD_PREGAME,
    LIVE_ALERT_THRESHOLD_PCT,
    LIVE_ARB_THRESHOLD,
    LIVE_INTERVAL_SECONDS,
    LIVE_LOG_FILE,
    PREGAME_ARB_THRESHOLD,
    PREGAME_BUFFER_MINUTES,
    PREGAME_INTERVAL_SECONDS,
    PREGAME_LOG_FILE,
)
from sports_arb.models import ArbitrageOpportunity, BookmakerOdds
from sports_arb.odds_providers import PROVIDER_REGISTRY

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


def _get_logger(log_file: str, logger_name: str) -> logging.Logger:
    """Return a logger that writes to *log_file* (creating directories as needed).

    A unique logger is created per ``log_file`` path so that callers passing
    different file paths always get independent loggers even when they share
    the same conceptual ``logger_name``.
    """
    # Guard: only call makedirs when the log_file contains a directory component.
    dirname = os.path.dirname(log_file)
    if dirname:
        os.makedirs(dirname, exist_ok=True)

    # Incorporate the log_file into the logger name so that different file paths
    # produce independent loggers rather than re-using the first handler.
    unique_name = f"{logger_name}.{log_file}"
    logger = logging.getLogger(unique_name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(handler)
    return logger


# ---------------------------------------------------------------------------
# Game filtering helpers
# ---------------------------------------------------------------------------


def filter_pregame(
    odds_list: list[BookmakerOdds],
    buffer_minutes: int = PREGAME_BUFFER_MINUTES,
) -> list[BookmakerOdds]:
    """Keep only records whose game has **not yet started** (with a safety buffer).

    Parameters
    ----------
    odds_list:
        Raw odds records from one or more providers.
    buffer_minutes:
        Exclude games starting within this many minutes from now (default 5).
        This prevents placing bets on games about to tip off.

    Returns
    -------
    list[BookmakerOdds]
        Records for games that start more than *buffer_minutes* from now.
    """
    cutoff = datetime.now(tz=UTC) + timedelta(minutes=buffer_minutes)
    return [r for r in odds_list if r.start_time > cutoff]


def filter_live(odds_list: list[BookmakerOdds]) -> list[BookmakerOdds]:
    """Keep only records whose game has **already started**.

    Parameters
    ----------
    odds_list:
        Raw odds records from one or more providers.

    Returns
    -------
    list[BookmakerOdds]
        Records for games whose ``start_time`` is in the past.
    """
    now = datetime.now(tz=UTC)
    return [r for r in odds_list if r.start_time <= now]


# ---------------------------------------------------------------------------
# Log formatting
# ---------------------------------------------------------------------------


def _log_opportunities(
    opps: list[ArbitrageOpportunity],
    logger: logging.Logger,
    mode: str,
    alert_threshold_pct: float | None = None,
) -> None:
    """Write *opps* to *logger* and optionally print console alerts."""
    for opp in opps:
        stakes_str = ", ".join(
            f"{outcome}=${stake:.2f}" for outcome, stake in opp.stakes.items()
        )
        msg = (
            f"[{mode.upper()}] {opp.sport} | {opp.home_team} vs {opp.away_team} | "
            f"edge={opp.edge_pct:.2f}% | "
            f"books={','.join(opp.involved_books)} | "
            f"stakes: {stakes_str}"
        )
        logger.info(msg)

        if alert_threshold_pct is not None and opp.edge_pct >= alert_threshold_pct:
            print(
                f"⚡ LIVE ARB  {opp.sport} | {opp.home_team} vs {opp.away_team} | "
                f"edge={opp.edge_pct:.2f}%"
            )


# ---------------------------------------------------------------------------
# Synchronous provider fetch
# ---------------------------------------------------------------------------


def _fetch_all_odds_sync() -> list[BookmakerOdds]:
    """Collect odds from all registered providers synchronously.

    Provider errors are caught and logged so that one failing provider does
    not abort the entire scan cycle.
    """
    _err_logger = logging.getLogger("sports_arb.scanner")
    all_odds: list[BookmakerOdds] = []
    for name, provider_cls in PROVIDER_REGISTRY.items():
        try:
            provider = provider_cls()
            all_odds.extend(provider.get_current_odds())
        except Exception as exc:  # noqa: BLE001
            _err_logger.warning("Provider %s failed in sync fetch: %s", name, exc)
    return all_odds


# ---------------------------------------------------------------------------
# Pre-game scanner – synchronous single-shot and loop
# ---------------------------------------------------------------------------


def run_pregame_scan(
    bankroll: float = 100.0,
    threshold: float = PREGAME_ARB_THRESHOLD,
    buffer_minutes: int = PREGAME_BUFFER_MINUTES,
    log_file: str = PREGAME_LOG_FILE,
    telegram_threshold_pct: float = ALERT_THRESHOLD_PREGAME,
) -> list[ArbitrageOpportunity]:
    """Execute one pre-game scan cycle and log results.

    Parameters
    ----------
    bankroll:
        Bankroll used for stake calculations.
    threshold:
        Implied-probability threshold; opportunities with a sum below this
        value are surfaced.
    buffer_minutes:
        Exclude games starting within this many minutes.
    log_file:
        Path to the log file for pre-game opportunities.
    telegram_threshold_pct:
        Edge % above which a Telegram alert is sent (default 3 %).

    Returns
    -------
    list[ArbitrageOpportunity]
        Opportunities found in this scan cycle.
    """
    logger = _get_logger(log_file, "pregame")

    all_odds = _fetch_all_odds_sync()
    pregame_odds = filter_pregame(all_odds, buffer_minutes=buffer_minutes)
    opps = detect_arbitrage(pregame_odds, threshold=threshold, bankroll=bankroll)

    _log_opportunities(opps, logger, mode="pregame")
    for opp in opps:
        if opp.edge_pct >= telegram_threshold_pct:
            try:
                send_pregame_alert_sync(opp)
            except Exception as exc:  # noqa: BLE001
                logging.getLogger("sports_arb.scanner").error(
                    "Telegram pregame alert error: %s", exc
                )
    return opps


def start_pregame_loop(
    bankroll: float = 100.0,
    threshold: float = PREGAME_ARB_THRESHOLD,
    buffer_minutes: int = PREGAME_BUFFER_MINUTES,
    interval_seconds: int = PREGAME_INTERVAL_SECONDS,
    log_file: str = PREGAME_LOG_FILE,
    telegram_threshold_pct: float = ALERT_THRESHOLD_PREGAME,
) -> None:
    """Run the pre-game scanner on a repeating interval (blocking).

    Press Ctrl-C to stop.

    Parameters
    ----------
    bankroll:
        Bankroll used for stake calculations.
    threshold:
        Arb threshold for pre-game mode.
    buffer_minutes:
        Exclude games starting within this many minutes.
    interval_seconds:
        Seconds between scan cycles.
    log_file:
        Path to the pre-game log file.
    telegram_threshold_pct:
        Edge % above which a Telegram alert is sent (default 3 %).
    """
    print(
        f"[pregame] Starting pre-game scanner "
        f"(interval={interval_seconds}s, threshold={threshold}, "
        f"buffer={buffer_minutes}min, log={log_file})"
    )
    try:
        while True:
            opps = run_pregame_scan(
                bankroll=bankroll,
                threshold=threshold,
                buffer_minutes=buffer_minutes,
                log_file=log_file,
                telegram_threshold_pct=telegram_threshold_pct,
            )
            print(
                f"[pregame] {datetime.now(tz=UTC).strftime('%H:%M:%S')} – "
                f"{len(opps)} opportunity/ies found."
            )
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\n[pregame] Scanner stopped.")


# ---------------------------------------------------------------------------
# Live scanner – async single-shot and loop
# ---------------------------------------------------------------------------


async def _fetch_all_odds_async() -> list[BookmakerOdds]:
    """Collect live odds from all registered providers concurrently.

    Each provider's :meth:`~sports_arb.odds_providers.base.BaseOddsProvider.async_get_live_odds`
    is called so that providers with a dedicated live endpoint (e.g.
    :class:`~sports_arb.odds_providers.the_odds_api.TheOddsApiProvider`) use
    it instead of the pre-game endpoint.  Providers that don't override
    ``get_live_odds`` fall back to ``get_current_odds`` automatically.

    Provider errors are logged individually so that one failing provider does
    not prevent odds from being collected from the remaining providers.
    """
    _err_logger = logging.getLogger("sports_arb.scanner")
    providers = list(PROVIDER_REGISTRY.items())
    results = await asyncio.gather(
        *[cls().async_get_live_odds() for _, cls in providers],
        return_exceptions=True,
    )
    all_odds: list[BookmakerOdds] = []
    # asyncio.gather() preserves input order, so zip() correctly pairs each
    # result with its originating (name, cls) tuple.
    for (name, _), batch in zip(providers, results):
        if isinstance(batch, BaseException):
            _err_logger.warning("Provider %s failed in async fetch: %s", name, batch)
            continue
        all_odds.extend(batch)
    return all_odds


async def run_live_scan(
    bankroll: float = 100.0,
    threshold: float = LIVE_ARB_THRESHOLD,
    log_file: str = LIVE_LOG_FILE,
    alert_threshold_pct: float = LIVE_ALERT_THRESHOLD_PCT,
    telegram_threshold_pct: float = ALERT_THRESHOLD_LIVE,
) -> list[ArbitrageOpportunity]:
    """Execute one live scan cycle asynchronously and log results.

    Parameters
    ----------
    bankroll:
        Bankroll used for stake calculations.
    threshold:
        Tighter implied-probability threshold for live mode.
    log_file:
        Path to the log file for live opportunities.
    alert_threshold_pct:
        Edge % above which ⚡ LIVE ARB is printed to the console.
    telegram_threshold_pct:
        Edge % above which a Telegram alert is sent (default 2 %).

    Returns
    -------
    list[ArbitrageOpportunity]
        Live opportunities found in this scan cycle.
    """
    logger = _get_logger(log_file, "live")

    all_odds = await _fetch_all_odds_async()
    live_odds = filter_live(all_odds)
    opps = detect_arbitrage(live_odds, threshold=threshold, bankroll=bankroll)

    _log_opportunities(opps, logger, mode="live", alert_threshold_pct=alert_threshold_pct)
    for opp in opps:
        if opp.edge_pct >= telegram_threshold_pct:
            try:
                await send_arb_alert(opp)
            except Exception as exc:  # noqa: BLE001
                logging.getLogger("sports_arb.scanner").error(
                    "Telegram live alert error: %s", exc
                )
    return opps


async def start_live_loop(
    bankroll: float = 100.0,
    threshold: float = LIVE_ARB_THRESHOLD,
    interval_seconds: int = LIVE_INTERVAL_SECONDS,
    log_file: str = LIVE_LOG_FILE,
    alert_threshold_pct: float = LIVE_ALERT_THRESHOLD_PCT,
    telegram_threshold_pct: float = ALERT_THRESHOLD_LIVE,
) -> None:
    """Run the live scanner on a repeating async interval.

    Parameters
    ----------
    bankroll:
        Bankroll used for stake calculations.
    threshold:
        Arb threshold for live mode.
    interval_seconds:
        Seconds between scan cycles.
    log_file:
        Path to the live log file.
    alert_threshold_pct:
        Edge % above which ⚡ LIVE ARB is printed to the console.
    telegram_threshold_pct:
        Edge % above which a Telegram alert is sent (default 2 %).
    """
    print(
        f"[live] Starting live scanner "
        f"(interval={interval_seconds}s, threshold={threshold}, log={log_file})"
    )
    try:
        while True:
            opps = await run_live_scan(
                bankroll=bankroll,
                threshold=threshold,
                log_file=log_file,
                alert_threshold_pct=alert_threshold_pct,
                telegram_threshold_pct=telegram_threshold_pct,
            )
            print(
                f"[live] {datetime.now(tz=UTC).strftime('%H:%M:%S')} – "
                f"{len(opps)} opportunity/ies found."
            )
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        print("\n[live] Scanner stopped.")


# ---------------------------------------------------------------------------
# Combined (both) runner
# ---------------------------------------------------------------------------


async def _run_both(
    bankroll: float = 100.0,
    pregame_threshold: float = PREGAME_ARB_THRESHOLD,
    pregame_interval: int = PREGAME_INTERVAL_SECONDS,
    pregame_buffer: int = PREGAME_BUFFER_MINUTES,
    pregame_log: str = PREGAME_LOG_FILE,
    pregame_telegram_pct: float = ALERT_THRESHOLD_PREGAME,
    live_threshold: float = LIVE_ARB_THRESHOLD,
    live_interval: int = LIVE_INTERVAL_SECONDS,
    live_log: str = LIVE_LOG_FILE,
    live_alert_pct: float = LIVE_ALERT_THRESHOLD_PCT,
    live_telegram_pct: float = ALERT_THRESHOLD_LIVE,
) -> None:
    """Run pregame and live scanners concurrently via asyncio tasks."""

    async def _pregame_loop_async() -> None:
        """Async wrapper around the sync pregame loop so it can run as a task."""
        try:
            while True:
                opps = await asyncio.to_thread(
                    run_pregame_scan,
                    bankroll,
                    pregame_threshold,
                    pregame_buffer,
                    pregame_log,
                    pregame_telegram_pct,
                )
                print(
                    f"[pregame] {datetime.now(tz=UTC).strftime('%H:%M:%S')} – "
                    f"{len(opps)} opportunity/ies found."
                )
                await asyncio.sleep(pregame_interval)
        except asyncio.CancelledError:
            print("\n[pregame] Scanner stopped.")

    print("[both] Launching pregame and live scanners concurrently.")
    async with asyncio.TaskGroup() as tg:
        tg.create_task(_pregame_loop_async())
        tg.create_task(
            start_live_loop(
                bankroll=bankroll,
                threshold=live_threshold,
                interval_seconds=live_interval,
                log_file=live_log,
                alert_threshold_pct=live_alert_pct,
                telegram_threshold_pct=live_telegram_pct,
            )
        )


def start_both(
    bankroll: float = 100.0,
    pregame_threshold: float = PREGAME_ARB_THRESHOLD,
    pregame_interval: int = PREGAME_INTERVAL_SECONDS,
    pregame_buffer: int = PREGAME_BUFFER_MINUTES,
    pregame_log: str = PREGAME_LOG_FILE,
    pregame_telegram_pct: float = ALERT_THRESHOLD_PREGAME,
    live_threshold: float = LIVE_ARB_THRESHOLD,
    live_interval: int = LIVE_INTERVAL_SECONDS,
    live_log: str = LIVE_LOG_FILE,
    live_alert_pct: float = LIVE_ALERT_THRESHOLD_PCT,
    live_telegram_pct: float = ALERT_THRESHOLD_LIVE,
) -> None:
    """Run both scanners concurrently (blocking entry point for CLI use)."""
    try:
        asyncio.run(
            _run_both(
                bankroll=bankroll,
                pregame_threshold=pregame_threshold,
                pregame_interval=pregame_interval,
                pregame_buffer=pregame_buffer,
                pregame_log=pregame_log,
                pregame_telegram_pct=pregame_telegram_pct,
                live_threshold=live_threshold,
                live_interval=live_interval,
                live_log=live_log,
                live_alert_pct=live_alert_pct,
                live_telegram_pct=live_telegram_pct,
            )
        )
    except KeyboardInterrupt:
        print("\n[both] Scanners stopped.")
