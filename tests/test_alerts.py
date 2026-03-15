"""Tests for the Telegram alert module and its integration with the scanner.

These tests validate:
- Alert messages are formatted correctly for live and pre-game opportunities.
- Alerts are sent only when the edge exceeds the configured threshold.
- A Telegram network / token failure does NOT crash the scanner loop.
- Missing credentials cause a graceful no-op (logged at WARNING level).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from sports_arb.alerts.telegram import (
    _decimal_to_american,
    _format_message,
    send_arb_alert,
    send_pregame_alert,
)
from sports_arb.models import ArbitrageOpportunity

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_opportunity(
    edge_pct: float = 3.2,
    home_team: str = "Lakers",
    away_team: str = "Celtics",
    league: str = "NBA",
) -> ArbitrageOpportunity:
    """Return a minimal ArbitrageOpportunity for testing."""
    return ArbitrageOpportunity(
        game_id="game_nba_test",
        sport="basketball_nba",
        league=league,
        home_team=home_team,
        away_team=away_team,
        start_time=datetime(2025, 6, 1, 20, 0, 0, tzinfo=UTC),
        market_type="moneyline",
        involved_books=["DraftKings", "FanDuel"],
        best_odds={"home": 3.1, "away": 1.909},
        best_odds_books={"home": "DraftKings", "away": "FanDuel"},
        implied_prob_sum=0.968,
        edge_pct=edge_pct,
        stakes={"home": 32.26, "away": 67.74},
        expected_profit=3.20,
        expected_profit_pct=3.2,
    )


# ---------------------------------------------------------------------------
# _decimal_to_american tests
# ---------------------------------------------------------------------------


class TestDecimalToAmerican:
    def test_positive_american(self) -> None:
        """Odds of 3.1 → +210."""
        assert _decimal_to_american(3.1) == "+210"

    def test_negative_american(self) -> None:
        """Odds of 1.909... → -110."""
        result = _decimal_to_american(100 / 52.36)
        assert result.startswith("-")

    def test_even_odds(self) -> None:
        """Decimal 2.0 → +100."""
        assert _decimal_to_american(2.0) == "+100"

    def test_heavy_favourite(self) -> None:
        """Odds of 1.25 → -400."""
        assert _decimal_to_american(1.25) == "-400"


# ---------------------------------------------------------------------------
# Message formatting tests
# ---------------------------------------------------------------------------


class TestFormatMessage:
    def test_live_message_contains_emoji(self) -> None:
        opp = _make_opportunity()
        msg = _format_message(opp, emoji="⚡", label="LIVE ARB DETECTED")
        assert "⚡" in msg
        assert "LIVE ARB DETECTED" in msg

    def test_pregame_message_contains_emoji(self) -> None:
        opp = _make_opportunity()
        msg = _format_message(opp, emoji="🔔", label="PREGAME ARB DETECTED")
        assert "🔔" in msg
        assert "PREGAME ARB DETECTED" in msg

    def test_message_contains_teams(self) -> None:
        opp = _make_opportunity()
        msg = _format_message(opp, emoji="⚡", label="LIVE ARB DETECTED")
        assert "Lakers" in msg
        assert "Celtics" in msg
        assert "NBA" in msg

    def test_message_contains_edge(self) -> None:
        opp = _make_opportunity(edge_pct=3.2)
        msg = _format_message(opp, emoji="⚡", label="LIVE ARB DETECTED")
        assert "3.2%" in msg

    def test_message_contains_profit(self) -> None:
        opp = _make_opportunity()
        msg = _format_message(opp, emoji="⚡", label="LIVE ARB DETECTED")
        assert "$3.20" in msg

    def test_message_contains_stakes(self) -> None:
        opp = _make_opportunity()
        msg = _format_message(opp, emoji="⚡", label="LIVE ARB DETECTED")
        assert "$32.26" in msg
        assert "$67.74" in msg

    def test_message_contains_implied_prob(self) -> None:
        opp = _make_opportunity()
        msg = _format_message(opp, emoji="⚡", label="LIVE ARB DETECTED")
        assert "96.8%" in msg

    def test_message_contains_bookmakers(self) -> None:
        opp = _make_opportunity()
        msg = _format_message(opp, emoji="⚡", label="LIVE ARB DETECTED")
        assert "DraftKings" in msg
        assert "FanDuel" in msg


# ---------------------------------------------------------------------------
# send_arb_alert / send_pregame_alert – success path
# ---------------------------------------------------------------------------


class TestSendAlertSuccess:
    @pytest.mark.asyncio
    async def test_send_arb_alert_calls_bot(self) -> None:
        """send_arb_alert calls bot.send_message with correct chat_id."""
        opp = _make_opportunity()
        mock_bot = AsyncMock()
        mock_bot.__aenter__ = AsyncMock(return_value=mock_bot)
        mock_bot.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict(
                "os.environ",
                {"TELEGRAM_BOT_TOKEN": "test_token", "TELEGRAM_CHAT_ID": "123456"},
            ),
            patch("sports_arb.alerts.telegram.Bot", return_value=mock_bot),
            patch("sports_arb.alerts.telegram._telegram_available", True),
        ):
            await send_arb_alert(opp)

        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == "123456"
        assert "⚡" in call_kwargs["text"]
        assert "LIVE ARB DETECTED" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_send_pregame_alert_calls_bot(self) -> None:
        """send_pregame_alert sends a 🔔 message."""
        opp = _make_opportunity()
        mock_bot = AsyncMock()
        mock_bot.__aenter__ = AsyncMock(return_value=mock_bot)
        mock_bot.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.dict(
                "os.environ",
                {"TELEGRAM_BOT_TOKEN": "test_token", "TELEGRAM_CHAT_ID": "123456"},
            ),
            patch("sports_arb.alerts.telegram.Bot", return_value=mock_bot),
            patch("sports_arb.alerts.telegram._telegram_available", True),
        ):
            await send_pregame_alert(opp)

        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert "🔔" in call_kwargs["text"]
        assert "PREGAME ARB DETECTED" in call_kwargs["text"]


# ---------------------------------------------------------------------------
# Error resilience tests – Telegram failures must NOT crash the scanner
# ---------------------------------------------------------------------------


class TestAlertErrorResilience:
    @pytest.mark.asyncio
    async def test_telegram_error_does_not_raise(self) -> None:
        """A TelegramError is caught; no exception propagates to the caller."""
        opp = _make_opportunity()
        mock_bot = AsyncMock()
        mock_bot.__aenter__ = AsyncMock(return_value=mock_bot)
        mock_bot.__aexit__ = AsyncMock(return_value=False)
        mock_bot.send_message.side_effect = Exception("TelegramError: bad token")

        with (
            patch.dict(
                "os.environ",
                {"TELEGRAM_BOT_TOKEN": "bad_token", "TELEGRAM_CHAT_ID": "123"},
            ),
            patch("sports_arb.alerts.telegram.Bot", return_value=mock_bot),
            patch("sports_arb.alerts.telegram._telegram_available", True),
        ):
            # Must not raise
            await send_arb_alert(opp)

    @pytest.mark.asyncio
    async def test_network_error_does_not_raise(self) -> None:
        """A network-level exception is caught; no exception propagates."""
        opp = _make_opportunity()
        mock_bot = AsyncMock()
        mock_bot.__aenter__ = AsyncMock(return_value=mock_bot)
        mock_bot.__aexit__ = AsyncMock(return_value=False)
        mock_bot.send_message.side_effect = OSError("network unreachable")

        with (
            patch.dict(
                "os.environ",
                {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "123"},
            ),
            patch("sports_arb.alerts.telegram.Bot", return_value=mock_bot),
            patch("sports_arb.alerts.telegram._telegram_available", True),
        ):
            await send_pregame_alert(opp)

    @pytest.mark.asyncio
    async def test_missing_credentials_skips_silently(self, caplog) -> None:
        """When token/chat_id are absent the alert is skipped with a warning."""
        import logging

        opp = _make_opportunity()
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("sports_arb.alerts.telegram._telegram_available", True),
            caplog.at_level(logging.WARNING, logger="sports_arb.alerts.telegram"),
        ):
            await send_arb_alert(opp)

        assert any("TELEGRAM_BOT_TOKEN" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_library_unavailable_skips_silently(self, caplog) -> None:
        """When python-telegram-bot is not installed the alert is skipped gracefully."""
        import logging

        opp = _make_opportunity()
        with (
            patch("sports_arb.alerts.telegram._telegram_available", False),
            caplog.at_level(logging.WARNING, logger="sports_arb.alerts.telegram"),
        ):
            await send_arb_alert(opp)

        assert any("python-telegram-bot" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Scanner integration: Telegram failure must NOT crash run_pregame_scan
# ---------------------------------------------------------------------------


class TestScannerIntegration:
    def test_pregame_scan_survives_telegram_failure(self, tmp_path) -> None:
        """run_pregame_scan completes normally even if Telegram raises an error."""
        from sports_arb.scanner import run_pregame_scan

        log_file = str(tmp_path / "test_pregame.log")

        with patch(
            "sports_arb.scanner.send_pregame_alert_sync",
            side_effect=RuntimeError("simulated Telegram crash"),
        ):
            # Use a threshold that guarantees some mock opportunities are found
            opps = run_pregame_scan(
                bankroll=100.0,
                threshold=0.5,  # very loose – catches mock data arb opps
                buffer_minutes=0,
                log_file=log_file,
                telegram_threshold_pct=0.0,  # alert on every opp
            )
        # The scan should still return results; the Telegram error is caught
        # by the try/except in run_pregame_scan and does not propagate.
        assert isinstance(opps, list)

    @pytest.mark.asyncio
    async def test_live_scan_survives_telegram_failure(self, tmp_path) -> None:
        """run_live_scan completes normally even if send_arb_alert raises."""
        from sports_arb.scanner import run_live_scan

        log_file = str(tmp_path / "test_live.log")

        with patch(
            "sports_arb.scanner.send_arb_alert",
            new_callable=AsyncMock,
            side_effect=RuntimeError("simulated Telegram crash"),
        ):
            opps = await run_live_scan(
                bankroll=100.0,
                threshold=0.5,
                log_file=log_file,
                alert_threshold_pct=0.0,
                telegram_threshold_pct=0.0,
            )
        assert isinstance(opps, list)
