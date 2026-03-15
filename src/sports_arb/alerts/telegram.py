"""Telegram bot alerts for arbitrage opportunities.

Sends real-time push notifications via a Telegram bot when a live or pre-game
arbitrage opportunity is detected.

Configuration (loaded from .env or environment variables):

``TELEGRAM_BOT_TOKEN``
    Bot API token obtained from `@BotFather <https://t.me/BotFather>`_.

``TELEGRAM_CHAT_ID``
    The numeric chat / channel ID where alerts will be sent.
    Run ``/start`` with your bot, then fetch
    ``https://api.telegram.org/bot<TOKEN>/getUpdates`` to find your chat ID.

If either variable is absent, alerts are silently skipped (logged at WARNING
level).  Network errors or bad tokens are caught and logged so that the
scanner loop is never interrupted.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sports_arb.models import ArbitrageOpportunity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports so that missing python-telegram-bot does not crash the module.
# ---------------------------------------------------------------------------

_telegram_available: bool = True
try:
    from telegram import Bot
    from telegram.error import TelegramError
except ImportError:  # pragma: no cover
    _telegram_available = False
    Bot = None  # type: ignore[assignment,misc]
    TelegramError = Exception  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_credentials() -> tuple[str, str] | tuple[None, None]:
    """Return (bot_token, chat_id) from the environment, or (None, None)."""
    import os

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return None, None
    return token, chat_id


def _decimal_to_american(decimal_odds: float) -> str:
    """Convert decimal odds to American odds string (e.g. +210 or -110)."""
    if decimal_odds >= 2.0:
        american = (decimal_odds - 1) * 100
        return f"+{int(round(american))}"
    else:
        american = -100 / (decimal_odds - 1)
        return str(int(round(american)))


def _format_message(opp: ArbitrageOpportunity, emoji: str, label: str) -> str:
    """Build the Telegram message text for *opp*."""
    now_str = datetime.now(tz=UTC).strftime("%-I:%M:%S %p UTC")

    lines: list[str] = [
        f"{emoji} {label}",
        f"Game: {opp.home_team} vs {opp.away_team} ({opp.league})",
        f"Edge: {opp.edge_pct:.1f}%",
        f"Profit on $100: ${opp.expected_profit:.2f}",
    ]

    for outcome, stake in opp.stakes.items():
        book = opp.best_odds_books.get(outcome, "?")
        dec_odds = opp.best_odds.get(outcome, 0.0)
        am_odds = _decimal_to_american(dec_odds)
        lines.append(f"{book} → {outcome.title()} ML: {am_odds} → Stake ${stake:.2f}")

    lines.append(f"Implied prob sum: {opp.implied_prob_sum * 100:.1f}%")
    lines.append(f"Detected: {now_str}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public send functions
# ---------------------------------------------------------------------------


async def send_arb_alert(opp: ArbitrageOpportunity) -> None:
    """Send a ⚡ LIVE ARB DETECTED alert for *opp* via Telegram.

    Failures (network errors, invalid token, missing credentials) are logged
    and swallowed so the scanner loop is never interrupted.
    """
    await _send(opp, emoji="⚡", label="LIVE ARB DETECTED")


async def send_pregame_alert(opp: ArbitrageOpportunity) -> None:
    """Send a 🔔 PREGAME ARB DETECTED alert for *opp* via Telegram.

    Failures are logged and swallowed so the scanner loop is never interrupted.
    """
    await _send(opp, emoji="🔔", label="PREGAME ARB DETECTED")


async def _send(opp: ArbitrageOpportunity, emoji: str, label: str) -> None:
    """Internal coroutine that builds and dispatches the Telegram message."""
    if not _telegram_available:
        logger.warning("python-telegram-bot is not installed; Telegram alerts are disabled.")
        return

    token, chat_id = _load_credentials()
    if token is None:
        logger.warning(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set; skipping Telegram alert."
        )
        return

    text = _format_message(opp, emoji, label)
    try:
        async with Bot(token=token) as bot:
            await bot.send_message(chat_id=chat_id, text=text)
    except TelegramError as exc:
        logger.error("Telegram alert failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error sending Telegram alert: %s", exc)


# ---------------------------------------------------------------------------
# Sync convenience wrapper (used by the synchronous pregame scanner)
# ---------------------------------------------------------------------------


def send_pregame_alert_sync(opp: ArbitrageOpportunity) -> None:
    """Synchronous wrapper around :func:`send_pregame_alert`.

    Uses :func:`asyncio.run` to create a fresh event loop (safe to call from
    synchronous code such as the pregame scanner thread).  If an event loop is
    already running (e.g. inside an async context) the alert is scheduled as a
    fire-and-forget task instead.
    """
    try:
        asyncio.get_running_loop()
        # Already inside a running loop – schedule as a fire-and-forget task.
        asyncio.ensure_future(send_pregame_alert(opp))
    except RuntimeError:
        # No running loop – create a new one via asyncio.run().
        try:
            asyncio.run(send_pregame_alert(opp))
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error in send_pregame_alert_sync: %s", exc)
