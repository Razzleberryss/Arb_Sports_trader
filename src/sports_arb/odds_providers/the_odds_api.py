"""Live odds provider backed by The Odds API (https://the-odds-api.com).

Pre-game endpoint::

    GET https://api.the-odds-api.com/v4/sports/{sport}/odds
        ?apiKey=...&regions=us&markets=h2h&oddsFormat=american

Live endpoint::

    GET https://api.the-odds-api.com/v4/sports/{sport}/odds
        ?apiKey=...&regions=us&markets=h2h&oddsFormat=american
        &commenceTimeTo=<ISO8601 now>

After every successful HTTP call the remaining API quota is written to the
``sports_arb.odds_providers.the_odds_api`` logger so operators can track
usage against The Odds API free-tier limits.

Responses are normalised into :class:`~sports_arb.models.BookmakerOdds`
records (one per bookmaker × game × market).  American odds are converted
to decimal odds before being stored.

A **class-level in-memory cache** (shared across all instances) prevents
redundant API calls when the scanner loops faster than the configured minimum
fetch intervals:

* Pre-game mode  → ``min_fetch_interval_pregame`` seconds  (default 300)
* Live mode      → ``min_fetch_interval_live``     seconds  (default 20)

Because the cache is class-level, it survives across scan cycles even when the
scanner creates a new provider instance on every cycle.  A :class:`threading.Lock`
protects cache reads and writes so the provider is safe to call from multiple
threads concurrently.

DISCLAIMER: This module is for educational purposes only.  Output does not
constitute financial advice and must not be used to place real wagers.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime

import httpx

from sports_arb.models import BookmakerOdds
from sports_arb.odds_providers.base import BaseOddsProvider

_log = logging.getLogger(__name__)

_BASE_URL = "https://api.the-odds-api.com/v4/sports"

# Maps The Odds API sport key → short display name stored on BookmakerOdds.
_SPORT_DISPLAY: dict[str, str] = {
    "americanfootball_nfl": "NFL",
    "basketball_nba": "NBA",
    "soccer_usa_mls": "MLS",
    "baseball_mlb": "MLB",
    "icehockey_nhl": "NHL",
}

# Short aliases accepted by the --sport CLI flag → The Odds API sport key.
SPORT_ALIASES: dict[str, str] = {
    "nfl": "americanfootball_nfl",
    "nba": "basketball_nba",
    "mls": "soccer_usa_mls",
    "mlb": "baseball_mlb",
    "nhl": "icehockey_nhl",
}


def _american_to_decimal(american_odds: float) -> float:
    """Convert American moneyline odds to decimal odds."""
    if american_odds >= 0:
        return (american_odds / 100.0) + 1.0
    return (100.0 / abs(american_odds)) + 1.0


class TheOddsApiProvider(BaseOddsProvider):
    """Fetches real odds from The Odds API and caches them per sport.

    The cache is **class-level** so it is shared across all provider instances.
    This ensures the TTL is honoured even when the scanner creates a fresh
    instance on every scan cycle.  A :class:`threading.Lock` serialises cache
    access so the provider is safe to call from multiple threads.

    Parameters
    ----------
    api_key:
        The Odds API key.  Defaults to ``config.ODDS_API_KEY``.
    sports:
        List of The Odds API sport keys to fetch.
        Defaults to ``config.SPORTS``.
    bookmakers:
        List of bookmaker keys to include in the query
        (e.g. ``["draftkings", "fanduel"]``).
        Defaults to ``config.BOOKMAKERS``.
    min_fetch_interval_pregame:
        Minimum seconds between pre-game API fetches per sport.
        Defaults to ``config.MIN_FETCH_INTERVAL_PREGAME``.
    min_fetch_interval_live:
        Minimum seconds between live API fetches per sport.
        Defaults to ``config.MIN_FETCH_INTERVAL_LIVE``.
    """

    name: str = "the_odds_api"

    # Class-level caches shared across all instances: sport_key → (timestamp, records)
    _pregame_cache: dict[str, tuple[float, list[BookmakerOdds]]] = {}
    _live_cache: dict[str, tuple[float, list[BookmakerOdds]]] = {}
    _cache_lock: threading.Lock = threading.Lock()

    def __init__(
        self,
        api_key: str | None = None,
        sports: list[str] | None = None,
        bookmakers: list[str] | None = None,
        min_fetch_interval_pregame: int | None = None,
        min_fetch_interval_live: int | None = None,
    ) -> None:
        # Import config lazily so that tests can patch config values before
        # instantiating the provider.
        from sports_arb import config as cfg

        self._api_key: str = api_key if api_key is not None else cfg.ODDS_API_KEY
        self._sports: list[str] = sports if sports is not None else list(cfg.SPORTS)
        self._bookmakers: list[str] = bookmakers if bookmakers is not None else list(cfg.BOOKMAKERS)
        self._min_fetch_interval_pregame: int = (
            min_fetch_interval_pregame
            if min_fetch_interval_pregame is not None
            else cfg.MIN_FETCH_INTERVAL_PREGAME
        )
        self._min_fetch_interval_live: int = (
            min_fetch_interval_live
            if min_fetch_interval_live is not None
            else cfg.MIN_FETCH_INTERVAL_LIVE
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_params(self, live: bool) -> dict[str, str]:
        """Build common query parameters for the API call."""
        params: dict[str, str] = {
            "apiKey": self._api_key,
            "regions": "us",
            "markets": "h2h",
            "oddsFormat": "american",
        }
        if self._bookmakers:
            params["bookmakers"] = ",".join(self._bookmakers)
        if live:
            now = datetime.now(tz=UTC)
            # Fetch games that have already commenced (start_time <= now).
            params["commenceTimeTo"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        return params

    def _log_quota(self, headers: httpx.Headers) -> None:
        """Log remaining API quota from response headers."""
        remaining = headers.get("x-requests-remaining", "unknown")
        used = headers.get("x-requests-used", "unknown")
        _log.info("The Odds API quota – remaining: %s, used: %s", remaining, used)

    def _normalize(self, data: list[dict], sport_key: str) -> list[BookmakerOdds]:
        """Normalise a raw Odds API JSON response into BookmakerOdds objects."""
        display_sport = _SPORT_DISPLAY.get(sport_key, sport_key)
        result: list[BookmakerOdds] = []

        for game in data:
            game_id: str = game["id"]
            home_team: str = game["home_team"]
            away_team: str = game["away_team"]
            # The API returns ISO-8601 with a trailing "Z" for UTC.
            commence_time = datetime.fromisoformat(
                game["commence_time"].replace("Z", "+00:00")
            )

            for bookmaker in game.get("bookmakers", []):
                book_key: str = bookmaker.get("key", "")
                book_title: str = bookmaker.get("title", book_key)

                for market in bookmaker.get("markets", []):
                    if market.get("key") != "h2h":
                        continue

                    outcomes_dict: dict[str, float] = {}
                    for outcome in market.get("outcomes", []):
                        team_name: str = outcome["name"]
                        american_price: float = float(outcome["price"])
                        decimal_odds = _american_to_decimal(american_price)

                        # Normalise team name → "home" / "away" / "draw".
                        if team_name == home_team:
                            key = "home"
                        elif team_name == away_team:
                            key = "away"
                        else:
                            key = "draw"

                        outcomes_dict[key] = decimal_odds

                    if outcomes_dict:
                        result.append(
                            BookmakerOdds(
                                bookmaker=book_title,
                                game_id=game_id,
                                sport=display_sport,
                                league=display_sport,
                                home_team=home_team,
                                away_team=away_team,
                                start_time=commence_time,
                                market_type="moneyline",
                                outcomes=outcomes_dict,
                            )
                        )

        return result

    def _fetch_sport(self, sport_key: str, *, live: bool) -> list[BookmakerOdds]:
        """Fetch odds for one sport, honouring the in-memory cache.

        Parameters
        ----------
        sport_key:
            The Odds API sport identifier (e.g. ``"basketball_nba"``).
        live:
            When *True*, target in-progress games via ``commenceTimeTo``.

        Returns
        -------
        list[BookmakerOdds]
            Normalised odds records (may be from cache).
        """
        cache = TheOddsApiProvider._live_cache if live else TheOddsApiProvider._pregame_cache
        min_interval = (
            self._min_fetch_interval_live if live else self._min_fetch_interval_pregame
        )

        # Check cache under lock (fast path – no I/O).
        with TheOddsApiProvider._cache_lock:
            if sport_key in cache:
                cached_at, cached_data = cache[sport_key]
                if time.monotonic() - cached_at < min_interval:
                    _log.debug(
                        "Cache hit for sport=%s live=%s (age=%.1fs < %ds)",
                        sport_key,
                        live,
                        time.monotonic() - cached_at,
                        min_interval,
                    )
                    return cached_data

        # Cache miss or expired – fetch from API (outside the lock so other
        # threads are not blocked during network I/O).
        url = f"{_BASE_URL}/{sport_key}/odds"
        params = self._build_params(live=live)

        with httpx.Client(timeout=30.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()

        self._log_quota(response.headers)
        data: list[dict] = response.json()
        result = self._normalize(data, sport_key)

        # Write back to cache under lock.
        with TheOddsApiProvider._cache_lock:
            cache[sport_key] = (time.monotonic(), result)
        return result

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_current_odds(self) -> list[BookmakerOdds]:
        """Return pre-game odds for all configured sports.

        Results are cached per sport for ``min_fetch_interval_pregame``
        seconds (default 300 s) to avoid burning API quota.

        Returns
        -------
        list[BookmakerOdds]
            One record per (bookmaker, game, market) combination.
        """
        all_odds: list[BookmakerOdds] = []
        for sport_key in self._sports:
            try:
                all_odds.extend(self._fetch_sport(sport_key, live=False))
            except Exception as exc:  # noqa: BLE001
                _log.warning("Pre-game fetch failed for sport=%s: %s", sport_key, exc)
        return all_odds

    def get_live_odds(self) -> list[BookmakerOdds]:
        """Return live (in-progress) odds for all configured sports.

        Results are cached per sport for ``min_fetch_interval_live``
        seconds (default 20 s) so that the live scanner (running every 30 s)
        does not blast through free-tier quota.

        Returns
        -------
        list[BookmakerOdds]
            One record per (bookmaker, game, market) combination.
        """
        all_odds: list[BookmakerOdds] = []
        for sport_key in self._sports:
            try:
                all_odds.extend(self._fetch_sport(sport_key, live=True))
            except Exception as exc:  # noqa: BLE001
                _log.warning("Live fetch failed for sport=%s: %s", sport_key, exc)
        return all_odds
