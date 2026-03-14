"""Tests for TheOddsApiProvider.

Covers:
- Correct normalisation of The Odds API JSON response into BookmakerOdds objects
- In-memory cache returns stale data within the interval and refreshes on expiry
- Fallback to MockOddsProvider when ODDS_API_KEY is absent
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from sports_arb.models import BookmakerOdds
from sports_arb.odds_providers.the_odds_api import TheOddsApiProvider, _american_to_decimal

# ---------------------------------------------------------------------------
# Module-level autouse fixture: reset the class-level cache before/after every
# test in this file so tests don't bleed state into each other.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_provider_cache():
    """Clear TheOddsApiProvider class-level caches around each test."""
    TheOddsApiProvider._pregame_cache.clear()
    TheOddsApiProvider._live_cache.clear()
    yield
    TheOddsApiProvider._pregame_cache.clear()
    TheOddsApiProvider._live_cache.clear()

# ---------------------------------------------------------------------------
# Sample The Odds API JSON response (single game, two bookmakers)
# ---------------------------------------------------------------------------

_COMMENCE_TIME = "2026-03-20T19:00:00Z"

_SAMPLE_RESPONSE: list[dict] = [
    {
        "id": "test_game_001",
        "sport_key": "basketball_nba",
        "sport_title": "NBA",
        "commence_time": _COMMENCE_TIME,
        "home_team": "Los Angeles Lakers",
        "away_team": "Boston Celtics",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": 150},
                            {"name": "Boston Celtics", "price": -175},
                        ],
                    }
                ],
            },
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Los Angeles Lakers", "price": 145},
                            {"name": "Boston Celtics", "price": -170},
                        ],
                    }
                ],
            },
        ],
    }
]

# Soccer with a draw market
_SOCCER_RESPONSE: list[dict] = [
    {
        "id": "test_soccer_001",
        "sport_key": "soccer_usa_mls",
        "sport_title": "MLS",
        "commence_time": _COMMENCE_TIME,
        "home_team": "LA Galaxy",
        "away_team": "NYCFC",
        "bookmakers": [
            {
                "key": "betmgm",
                "title": "BetMGM",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "LA Galaxy", "price": 190},
                            {"name": "Draw", "price": 230},
                            {"name": "NYCFC", "price": 150},
                        ],
                    }
                ],
            },
        ],
    }
]


# ---------------------------------------------------------------------------
# Helper to build a mock httpx response
# ---------------------------------------------------------------------------

def _mock_response(json_data: list[dict], remaining: str = "498", used: str = "2") -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.headers = {
        "x-requests-remaining": remaining,
        "x-requests-used": used,
    }
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Normalisation tests
# ---------------------------------------------------------------------------


class TestNormalization:
    def test_two_way_market_produces_correct_records(self):
        provider = TheOddsApiProvider(api_key="test-key", sports=["basketball_nba"])
        records = provider._normalize(_SAMPLE_RESPONSE, "basketball_nba")

        assert len(records) == 2  # one per bookmaker
        by_book = {r.bookmaker: r for r in records}

        dk = by_book["DraftKings"]
        assert dk.game_id == "test_game_001"
        assert dk.sport == "NBA"
        assert dk.league == "NBA"
        assert dk.home_team == "Los Angeles Lakers"
        assert dk.away_team == "Boston Celtics"
        assert dk.market_type == "moneyline"
        assert isinstance(dk.start_time, datetime)
        assert dk.start_time.tzinfo is not None
        # American +150 → decimal 2.5
        assert abs(dk.outcomes["home"] - _american_to_decimal(150)) < 1e-9
        # American -175 → decimal ≈ 1.5714
        assert abs(dk.outcomes["away"] - _american_to_decimal(-175)) < 1e-9

    def test_away_outcome_key_correct(self):
        provider = TheOddsApiProvider(api_key="test-key", sports=["basketball_nba"])
        records = provider._normalize(_SAMPLE_RESPONSE, "basketball_nba")
        for r in records:
            assert "home" in r.outcomes
            assert "away" in r.outcomes
            assert "draw" not in r.outcomes  # 2-way market

    def test_three_way_soccer_market(self):
        provider = TheOddsApiProvider(api_key="test-key", sports=["soccer_usa_mls"])
        records = provider._normalize(_SOCCER_RESPONSE, "soccer_usa_mls")

        assert len(records) == 1
        r = records[0]
        assert r.sport == "MLS"
        assert "home" in r.outcomes
        assert "away" in r.outcomes
        assert "draw" in r.outcomes
        assert abs(r.outcomes["draw"] - _american_to_decimal(230)) < 1e-9

    def test_sport_display_name_mapping(self):
        provider = TheOddsApiProvider(api_key="test-key")
        records = provider._normalize(_SAMPLE_RESPONSE, "americanfootball_nfl")
        # Unknown key in _SAMPLE_RESPONSE but uses the supplied sport_key for display name.
        # For "americanfootball_nfl" → "NFL"
        for r in records:
            assert r.sport == "NFL"

    def test_unknown_sport_key_falls_back_to_raw_key(self):
        provider = TheOddsApiProvider(api_key="test-key")
        records = provider._normalize(_SAMPLE_RESPONSE, "some_unknown_sport")
        for r in records:
            assert r.sport == "some_unknown_sport"

    def test_empty_bookmakers_list(self):
        no_books = [{**_SAMPLE_RESPONSE[0], "bookmakers": []}]
        provider = TheOddsApiProvider(api_key="test-key")
        records = provider._normalize(no_books, "basketball_nba")
        assert records == []

    def test_non_h2h_market_is_skipped(self):
        data = [
            {
                **_SAMPLE_RESPONSE[0],
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "title": "DraftKings",
                        "markets": [
                            {
                                "key": "spreads",  # not h2h
                                "outcomes": [
                                    {"name": "Los Angeles Lakers", "price": -110},
                                    {"name": "Boston Celtics", "price": -110},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
        provider = TheOddsApiProvider(api_key="test-key")
        records = provider._normalize(data, "basketball_nba")
        assert records == []

    def test_american_to_decimal_positive(self):
        assert abs(_american_to_decimal(100) - 2.0) < 1e-9
        assert abs(_american_to_decimal(150) - 2.5) < 1e-9

    def test_american_to_decimal_negative(self):
        assert abs(_american_to_decimal(-100) - 2.0) < 1e-9
        assert abs(_american_to_decimal(-110) - (100 / 110 + 1.0)) < 1e-9


# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------


class TestCache:
    def _make_provider(self, interval: int = 300) -> TheOddsApiProvider:
        return TheOddsApiProvider(
            api_key="test-key",
            sports=["basketball_nba"],
            min_fetch_interval_pregame=interval,
            min_fetch_interval_live=interval,
        )

    def test_cache_hit_within_interval_does_not_call_api(self):
        provider = self._make_provider(interval=300)
        mock_resp = _mock_response(_SAMPLE_RESPONSE)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            # First call – cache miss, API is hit.
            result1 = provider._fetch_sport("basketball_nba", live=False)
            assert mock_client.get.call_count == 1

            # Second call within interval – cache hit, no additional API call.
            result2 = provider._fetch_sport("basketball_nba", live=False)
            assert mock_client.get.call_count == 1  # unchanged

        assert result1 == result2

    def test_cache_miss_after_interval_refreshes_data(self):
        provider = self._make_provider(interval=1)  # 1-second TTL
        mock_resp = _mock_response(_SAMPLE_RESPONSE)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            # First call – cache miss.
            provider._fetch_sport("basketball_nba", live=False)
            assert mock_client.get.call_count == 1

            # Expire the cache by backdating the stored timestamp.
            TheOddsApiProvider._pregame_cache["basketball_nba"] = (
                time.monotonic() - 2,  # 2 seconds ago, past the 1-second TTL
                TheOddsApiProvider._pregame_cache["basketball_nba"][1],
            )

            # Second call – cache expired, API hit again.
            provider._fetch_sport("basketball_nba", live=False)
            assert mock_client.get.call_count == 2

    def test_live_cache_is_separate_from_pregame_cache(self):
        provider = self._make_provider(interval=300)
        mock_resp = _mock_response(_SAMPLE_RESPONSE)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            provider._fetch_sport("basketball_nba", live=False)
            provider._fetch_sport("basketball_nba", live=True)

            # Two distinct API calls (one pre-game, one live).
            assert mock_client.get.call_count == 2

    def test_get_current_odds_returns_records(self):
        provider = self._make_provider()
        mock_resp = _mock_response(_SAMPLE_RESPONSE)

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            records = provider.get_current_odds()

        assert len(records) == 2  # two bookmakers in sample
        assert all(isinstance(r, BookmakerOdds) for r in records)

    def test_provider_error_is_caught_returns_empty(self):
        provider = self._make_provider()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = Exception("network error")
            mock_client_cls.return_value = mock_client

            records = provider.get_current_odds()

        assert records == []


# ---------------------------------------------------------------------------
# Fallback / registry tests
# ---------------------------------------------------------------------------


class TestFallback:
    def test_mock_provider_used_when_no_api_key(self, monkeypatch):
        """PROVIDER_REGISTRY should contain only the mock provider when ODDS_API_KEY is unset."""
        monkeypatch.delenv("ODDS_API_KEY", raising=False)
        # Remove the cached module so the fresh import uses the patched env.
        # monkeypatch restores sys.modules automatically after the test.
        monkeypatch.delitem(sys.modules, "sports_arb.odds_providers", raising=False)

        import sports_arb.odds_providers as fresh_pkg

        assert "mock" in fresh_pkg.PROVIDER_REGISTRY
        assert "the_odds_api" not in fresh_pkg.PROVIDER_REGISTRY

    def test_real_provider_registered_when_api_key_set(self, monkeypatch):
        """PROVIDER_REGISTRY should include the_odds_api when ODDS_API_KEY is set."""
        monkeypatch.setenv("ODDS_API_KEY", "fake-key-12345")
        monkeypatch.delitem(sys.modules, "sports_arb.odds_providers", raising=False)

        import sports_arb.odds_providers as fresh_pkg

        assert "mock" in fresh_pkg.PROVIDER_REGISTRY
        assert "the_odds_api" in fresh_pkg.PROVIDER_REGISTRY

    def test_mock_provider_still_works_independently(self):
        """MockOddsProvider must remain fully functional regardless of env vars."""
        from sports_arb.odds_providers.mock_provider import MockOddsProvider

        provider = MockOddsProvider()
        records = provider.get_current_odds()

        assert len(records) > 0
        assert all(isinstance(r, BookmakerOdds) for r in records)


# ---------------------------------------------------------------------------
# Quota logging test
# ---------------------------------------------------------------------------


class TestQuotaLogging:
    def test_quota_headers_are_logged(self, caplog):
        import logging

        provider = TheOddsApiProvider(api_key="test-key", sports=["basketball_nba"])
        mock_resp = _mock_response(_SAMPLE_RESPONSE, remaining="450", used="50")

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            with caplog.at_level(logging.INFO, logger="sports_arb.odds_providers.the_odds_api"):
                provider._fetch_sport("basketball_nba", live=False)

        assert any("remaining: 450" in r.message for r in caplog.records)
        assert any("used: 50" in r.message for r in caplog.records)
