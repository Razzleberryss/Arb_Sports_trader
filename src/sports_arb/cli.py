"""CLI entry point for the sports arbitrage scanner.

Usage
-----
    python -m sports_arb.cli [options]
    sports-arb [options]          # after 'pip install -e .'

DISCLAIMER: This tool is for educational purposes only.  Output does not
constitute financial advice and must not be used to place real wagers.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timezone

from sports_arb.arb_engine import detect_arbitrage
from sports_arb.config import ARB_THRESHOLD, DEFAULT_MIN_EDGE, SUPPORTED_SPORTS
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

    # Derive the threshold from the CLI edge value (which is a percentage).
    threshold = 1.0 - (args.min_edge / 100.0)

    # ------------------------------------------------------------------
    # Collect odds from all registered providers
    # ------------------------------------------------------------------
    all_odds = []
    print(f"\n{'='*80}")
    print("  🏟   Sports Arbitrage Scanner  (educational use only)")
    print(f"{'='*80}\n")
    print(f"  Providers : {', '.join(PROVIDER_REGISTRY.keys())}")
    print(f"  Min edge  : {args.min_edge:.2f}%  (threshold={threshold:.4f})")
    print(f"  Bankroll  : ${args.bankroll:.2f}")
    if args.sport:
        print(f"  Sport     : {args.sport}")
    if args.book:
        print(f"  Book      : {args.book}")
    print()

    for provider_name, provider_cls in PROVIDER_REGISTRY.items():
        provider = provider_cls()
        try:
            odds = provider.get_current_odds()
            print(f"  ✓ {provider_name}: fetched {len(odds)} odds record(s)")
            all_odds.extend(odds)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {provider_name}: error – {exc}", file=sys.stderr)

    if not all_odds:
        print("\n  No odds data available. Exiting.\n")
        return 1

    # ------------------------------------------------------------------
    # Run arbitrage detection
    # ------------------------------------------------------------------
    opportunities = detect_arbitrage(all_odds, threshold=threshold, bankroll=args.bankroll)

    # ------------------------------------------------------------------
    # Apply CLI filters
    # ------------------------------------------------------------------
    if args.sport:
        sport_filter = args.sport.lower()
        opportunities = [
            o for o in opportunities if o.sport.lower() == sport_filter
        ]

    if args.book:
        book_filter = args.book.lower()
        opportunities = [
            o for o in opportunities
            if any(b.lower() == book_filter for b in o.involved_books)
        ]

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    print(f"\n  Found {len(opportunities)} arbitrage opportunity/ies.\n")

    if not opportunities:
        print("  No opportunities match the current filters.\n")
        print(_SEP)
        return 0

    for opp in opportunities:
        print(_fmt_opportunity(opp, bankroll=args.bankroll))

    print(_SEP)
    print(
        "\n  ⚠  DISCLAIMER: Output is for educational purposes only.\n"
        "     Do not use this tool to place real wagers.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
