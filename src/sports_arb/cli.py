"""CLI entry point for the sports arbitrage scanner.

Usage
-----
    python -m sports_arb.cli [options]
    sports-arb [options]          # after 'pip install -e .'

Run modes
---------
    --mode pregame   Pre-game scanner (default) – polls on a slow interval and
                     targets games that have not started yet.
    --mode live      Live / in-play scanner – polls on a fast interval using
                     async I/O and applies a tighter arb threshold.
    --mode both      Run both scanners concurrently via asyncio.

DISCLAIMER: This tool is for educational purposes only.  Output does not
constitute financial advice and must not be used to place real wagers.
"""

from __future__ import annotations

import argparse
import sys

from sports_arb.config import (
    DEFAULT_MIN_EDGE,
    LIVE_ALERT_THRESHOLD_PCT,
    LIVE_ARB_THRESHOLD,
    LIVE_INTERVAL_SECONDS,
    LIVE_LOG_FILE,
    PREGAME_ARB_THRESHOLD,
    PREGAME_BUFFER_MINUTES,
    PREGAME_INTERVAL_SECONDS,
    PREGAME_LOG_FILE,
    SUPPORTED_SPORTS,
)
from sports_arb.models import ArbitrageOpportunity
from sports_arb.odds_providers import PROVIDER_REGISTRY

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_SEP = "─" * 80


def _fmt_opportunity(opp: ArbitrageOpportunity, bankroll: float) -> str:
    """Return a multi-line human-readable summary for one opportunity."""
    lines: list[str] = []

    lines.append(_SEP)
    lines.append(
        f"  [{opp.sport} | {opp.league}]  "
        f"{opp.home_team}  vs  {opp.away_team}  "
        f"({opp.market_type.upper()})"
    )
    lines.append(
        f"  Game ID   : {opp.game_id}"
    )
    start_local = opp.start_time.astimezone(tz=None)
    lines.append(
        f"  Starts    : {start_local.strftime('%Y-%m-%d %H:%M %Z')}"
    )
    lines.append(
        f"  Books     : {', '.join(opp.involved_books)}"
    )
    lines.append(
        f"  IP Sum    : {opp.implied_prob_sum:.4f}  "
        f"Edge: {opp.edge_pct:.2f}%"
    )
    lines.append(
        f"  Profit    : ${opp.expected_profit:.2f}  "
        f"({opp.expected_profit_pct:.2f}%)  on ${bankroll:.2f} bankroll"
    )

    # Outcome table
    lines.append("")
    header = f"    {'Outcome':<12} {'Book':<16} {'Dec. Odds':>10} {'Stake ($)':>10}"
    lines.append(header)
    lines.append("    " + "·" * (len(header) - 4))
    for outcome, odds in opp.best_odds.items():
        book = opp.best_odds_books.get(outcome, "—")
        stake = opp.stakes.get(outcome, 0.0)
        lines.append(
            f"    {outcome:<12} {book:<16} {odds:>10.4f} {stake:>10.2f}"
        )

    return "\n".join(lines)


def _list_providers() -> None:
    """Print registered provider names and exit."""
    print("Available odds providers:")
    for name in PROVIDER_REGISTRY:
        cls = PROVIDER_REGISTRY[name]
        print(f"  {name:<20}  {cls.__name__}")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sports-arb",
        description=(
            "Sports betting arbitrage scanner (educational use only).\n\n"
            "Scans configured odds providers, identifies cross-book arbitrage\n"
            "opportunities, and prints a formatted summary table."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["pregame", "live", "both"],
        default="pregame",
        metavar="MODE",
        help=(
            "Run mode: 'pregame' (default), 'live', or 'both'. "
            "pregame runs on a slow interval targeting upcoming games; "
            "live runs on a fast async interval targeting in-progress games; "
            "both runs pregame and live concurrently."
        ),
    )
    parser.add_argument(
        "--min-edge",
        type=float,
        default=DEFAULT_MIN_EDGE * 100,
        metavar="FLOAT",
        help=(
            "Minimum edge percentage to surface an opportunity "
            f"(default: {DEFAULT_MIN_EDGE * 100:.1f})"
        ),
    )
    parser.add_argument(
        "--sport",
        type=str,
        default=None,
        metavar="SPORT",
        help=f"Filter by sport name (choices: {', '.join(SUPPORTED_SPORTS)})",
    )
    parser.add_argument(
        "--book",
        type=str,
        default=None,
        metavar="BOOK",
        help="Only show opportunities that involve this bookmaker",
    )
    parser.add_argument(
        "--bankroll",
        type=float,
        default=100.0,
        metavar="FLOAT",
        help="Bankroll to use for stake calculations (default: 100.0)",
    )
    parser.add_argument(
        "--providers",
        action="store_true",
        help="List available odds providers and exit",
    )
    # --- mode-specific overrides ---
    parser.add_argument(
        "--pregame-interval",
        type=int,
        default=PREGAME_INTERVAL_SECONDS,
        metavar="SECONDS",
        help=f"Pre-game scan interval in seconds (default: {PREGAME_INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--pregame-threshold",
        type=float,
        default=PREGAME_ARB_THRESHOLD,
        metavar="FLOAT",
        help=f"Arb threshold for pre-game mode (default: {PREGAME_ARB_THRESHOLD})",
    )
    parser.add_argument(
        "--pregame-buffer",
        type=int,
        default=PREGAME_BUFFER_MINUTES,
        metavar="MINUTES",
        help=f"Exclude games starting within this many minutes (default: {PREGAME_BUFFER_MINUTES})",
    )
    parser.add_argument(
        "--pregame-log",
        type=str,
        default=PREGAME_LOG_FILE,
        metavar="FILE",
        help=f"Pre-game log file path (default: {PREGAME_LOG_FILE})",
    )
    parser.add_argument(
        "--live-interval",
        type=int,
        default=LIVE_INTERVAL_SECONDS,
        metavar="SECONDS",
        help=f"Live scan interval in seconds (default: {LIVE_INTERVAL_SECONDS})",
    )
    parser.add_argument(
        "--live-threshold",
        type=float,
        default=LIVE_ARB_THRESHOLD,
        metavar="FLOAT",
        help=f"Arb threshold for live mode (default: {LIVE_ARB_THRESHOLD})",
    )
    parser.add_argument(
        "--live-log",
        type=str,
        default=LIVE_LOG_FILE,
        metavar="FILE",
        help=f"Live log file path (default: {LIVE_LOG_FILE})",
    )
    parser.add_argument(
        "--live-alert-threshold",
        type=float,
        default=LIVE_ALERT_THRESHOLD_PCT,
        metavar="FLOAT",
        help=(
            f"Edge %% above which ⚡ LIVE ARB is printed to console "
            f"(default: {LIVE_ALERT_THRESHOLD_PCT})"
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI entry point.  Returns an exit code (0 on success)."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.providers:
        _list_providers()
        return 0

    # ------------------------------------------------------------------
    # Dispatch to scanner loops when a run mode is requested
    # ------------------------------------------------------------------
    from sports_arb.scanner import start_both, start_live_loop, start_pregame_loop

    if args.mode == "pregame":
        start_pregame_loop(
            bankroll=args.bankroll,
            threshold=args.pregame_threshold,
            buffer_minutes=args.pregame_buffer,
            interval_seconds=args.pregame_interval,
            log_file=args.pregame_log,
        )
        return 0

    if args.mode == "live":
        import asyncio

        asyncio.run(
            start_live_loop(
                bankroll=args.bankroll,
                threshold=args.live_threshold,
                interval_seconds=args.live_interval,
                log_file=args.live_log,
                alert_threshold_pct=args.live_alert_threshold,
            )
        )
        return 0

    if args.mode == "both":
        start_both(
            bankroll=args.bankroll,
            pregame_threshold=args.pregame_threshold,
            pregame_interval=args.pregame_interval,
            pregame_buffer=args.pregame_buffer,
            pregame_log=args.pregame_log,
            live_threshold=args.live_threshold,
            live_interval=args.live_interval,
            live_log=args.live_log,
            live_alert_pct=args.live_alert_threshold,
        )
        return 0

    # Should not be reached given the choices= constraint on --mode.
    print(f"Unknown mode: {args.mode!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
