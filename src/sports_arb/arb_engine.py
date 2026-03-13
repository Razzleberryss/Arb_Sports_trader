"""Arbitrage detection engine – pure functions, no I/O.

All calculations operate on :class:`~sports_arb.models.BookmakerOdds` records
and return plain Python objects.  No network calls, file reads, or side-effects
occur in this module.

DISCLAIMER: This software is for educational purposes only.  It does not
constitute financial advice and must not be used to place real wagers.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from sports_arb.models import ArbitrageOpportunity, BookmakerOdds

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Odds conversion helpers
# ---------------------------------------------------------------------------

def american_to_decimal(american_odds: int) -> float:
    """Convert American (moneyline) odds to decimal odds.

    Parameters
    ----------
    american_odds:
        Positive → profit on a $100 wager (underdog).
        Negative → amount needed to wager to win $100 (favourite).

    Returns
    -------
    float
        Equivalent decimal odds (stake included in return).

    Examples
    --------
    >>> american_to_decimal(150)
    2.5
    >>> american_to_decimal(-110)
    1.9090909090909092
    >>> american_to_decimal(100)
    2.0
    """
    if american_odds >= 0:
        return (american_odds / 100) + 1.0
    return (100 / abs(american_odds)) + 1.0


def fractional_to_decimal(numerator: int, denominator: int) -> float:
    """Convert fractional odds to decimal odds.

    Parameters
    ----------
    numerator:
        Profit portion of the fraction (e.g. 3 in "3/1").
    denominator:
        Stake portion of the fraction (e.g. 1 in "3/1").

    Returns
    -------
    float
        Equivalent decimal odds.

    Examples
    --------
    >>> fractional_to_decimal(3, 1)
    4.0
    >>> fractional_to_decimal(1, 2)
    1.5
    """
    if denominator == 0:
        raise ValueError("denominator must not be zero")
    return (numerator / denominator) + 1.0


# ---------------------------------------------------------------------------
# Probability helper
# ---------------------------------------------------------------------------

def decimal_to_implied_prob(decimal_odds: float) -> float:
    """Convert decimal odds to their implied probability.

    Parameters
    ----------
    decimal_odds:
        Must be > 0.

    Returns
    -------
    float
        Value in the range (0, 1].

    Examples
    --------
    >>> decimal_to_implied_prob(2.0)
    0.5
    >>> decimal_to_implied_prob(4.0)
    0.25
    """
    if decimal_odds <= 0:
        raise ValueError(f"decimal_odds must be positive, got {decimal_odds}")
    return 1.0 / decimal_odds


# ---------------------------------------------------------------------------
# Best-odds aggregation
# ---------------------------------------------------------------------------

def find_best_odds(
    odds_list: list[BookmakerOdds],
    game_id: str,
    market_type: str,
) -> dict[str, tuple[float, str]]:
    """Find the best (highest) decimal odds per outcome for a given game/market.

    Parameters
    ----------
    odds_list:
        All available :class:`~sports_arb.models.BookmakerOdds` records (may
        include records for other games).
    game_id:
        Only records matching this game ID are considered.
    market_type:
        Only records matching this market type are considered.

    Returns
    -------
    dict[str, tuple[float, str]]
        Maps each outcome name to ``(best_decimal_odds, bookmaker_name)``.
        Returns an empty dict when no matching records are found.
    """
    best: dict[str, tuple[float, str]] = {}

    for record in odds_list:
        if record.game_id != game_id or record.market_type != market_type:
            continue
        for outcome_name, decimal_odds in record.outcomes.items():
            if outcome_name not in best or decimal_odds > best[outcome_name][0]:
                best[outcome_name] = (decimal_odds, record.bookmaker)

    return best


# ---------------------------------------------------------------------------
# Arbitrage mathematics
# ---------------------------------------------------------------------------

def compute_implied_prob_sum(
    best_odds: dict[str, tuple[float, str]],
) -> float:
    """Sum of implied probabilities across all outcomes.

    A value **below 1.0** indicates a theoretical arbitrage opportunity.

    Parameters
    ----------
    best_odds:
        Mapping returned by :func:`find_best_odds`.

    Returns
    -------
    float
        Sum of 1/odds_i for all outcomes.
    """
    return sum(decimal_to_implied_prob(odds) for odds, _ in best_odds.values())


def compute_stakes(
    best_odds: dict[str, tuple[float, str]],
    bankroll: float = 100.0,
) -> dict[str, float]:
    """Compute stakes that guarantee an equal total payout regardless of outcome.

    The equal-profit formula distributes the bankroll so that
    ``stake_i * decimal_odds_i`` is the same for every outcome *i*.

    Parameters
    ----------
    best_odds:
        Mapping returned by :func:`find_best_odds`.
    bankroll:
        Total amount to distribute across all outcomes (default $100).

    Returns
    -------
    dict[str, float]
        Maps outcome name to the recommended stake in the same currency as
        *bankroll*.
    """
    if not best_odds:
        return {}

    # Sum of implied probabilities (denominators cancel out elegantly)
    ip_sum = compute_implied_prob_sum(best_odds)
    if ip_sum <= 0:
        raise ValueError("implied probability sum must be positive")

    return {
        outcome: bankroll * decimal_to_implied_prob(odds) / ip_sum
        for outcome, (odds, _) in best_odds.items()
    }


def compute_expected_profit(
    best_odds: dict[str, tuple[float, str]],
    stakes: dict[str, float],
) -> tuple[float, float]:
    """Compute expected profit for the given stakes and odds.

    Under the equal-profit staking scheme every outcome yields the same gross
    return, so we can evaluate profit using any single outcome.

    Parameters
    ----------
    best_odds:
        Mapping returned by :func:`find_best_odds`.
    stakes:
        Mapping returned by :func:`compute_stakes`.

    Returns
    -------
    tuple[float, float]
        ``(profit_dollars, profit_pct)`` where *profit_pct* is expressed as a
        percentage of the total bankroll staked.
    """
    if not best_odds or not stakes:
        return 0.0, 0.0

    bankroll = sum(stakes.values())
    if bankroll <= 0:
        return 0.0, 0.0

    # Pick any outcome – they all return the same payout under equal-profit.
    first_outcome = next(iter(best_odds))
    best_decimal_odds = best_odds[first_outcome][0]
    first_stake = stakes[first_outcome]

    gross_return = first_stake * best_decimal_odds
    profit_dollars = gross_return - bankroll
    profit_pct = (profit_dollars / bankroll) * 100.0

    return profit_dollars, profit_pct


# ---------------------------------------------------------------------------
# Main detection function
# ---------------------------------------------------------------------------

def detect_arbitrage(
    odds_list: list[BookmakerOdds],
    threshold: float = 0.98,
    bankroll: float = 100.0,
) -> list[ArbitrageOpportunity]:
    """Scan all provided odds records and return confirmed arbitrage opportunities.

    Parameters
    ----------
    odds_list:
        Raw odds from one or more providers.
    threshold:
        An opportunity is only surfaced when ``implied_prob_sum < threshold``.
        The default value of 0.98 corresponds to a 2 % edge.
    bankroll:
        Used for stake and profit calculations (default $100).

    Returns
    -------
    list[ArbitrageOpportunity]
        Confirmed opportunities sorted by ``edge_pct`` descending (best first).
    """
    # Group records by (game_id, market_type)
    groups: dict[tuple[str, str], list[BookmakerOdds]] = defaultdict(list)
    for record in odds_list:
        groups[(record.game_id, record.market_type)].append(record)

    opportunities: list[ArbitrageOpportunity] = []

    for (game_id, market_type), records in groups.items():
        best_odds_raw = find_best_odds(records, game_id, market_type)
        if not best_odds_raw:
            continue

        ip_sum = compute_implied_prob_sum(best_odds_raw)
        if ip_sum >= threshold:
            continue  # No arb under the requested threshold

        # Metadata comes from the first record in the group (all share the same
        # game metadata; bookmaker-specific data is captured separately).
        ref = records[0]
        edge_pct = (1.0 - ip_sum) * 100.0

        stakes = compute_stakes(best_odds_raw, bankroll=bankroll)
        profit_dollars, profit_pct = compute_expected_profit(best_odds_raw, stakes)

        involved_books = sorted(
            {book for _, book in best_odds_raw.values()}
        )

        opportunities.append(
            ArbitrageOpportunity(
                game_id=game_id,
                sport=ref.sport,
                league=ref.league,
                home_team=ref.home_team,
                away_team=ref.away_team,
                start_time=ref.start_time,
                market_type=market_type,
                involved_books=involved_books,
                best_odds={o: odds for o, (odds, _) in best_odds_raw.items()},
                best_odds_books={o: book for o, (_, book) in best_odds_raw.items()},
                implied_prob_sum=ip_sum,
                edge_pct=edge_pct,
                stakes=stakes,
                expected_profit=profit_dollars,
                expected_profit_pct=profit_pct,
            )
        )

    # Sort best opportunities first
    opportunities.sort(key=lambda o: o.edge_pct, reverse=True)
    return opportunities
