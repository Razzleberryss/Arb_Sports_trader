# Arb Sports Trader

> **⚠ Educational use only.** This project does not constitute financial or
> gambling advice. Never use it to place real wagers.

A Python 3.11+ sports-betting **arbitrage scanner** that detects risk-free
profit opportunities across multiple bookmakers by finding combinations of
bets where the sum of the implied probabilities falls below 1.0 (i.e. below
100%).

---

## Table of contents

1. [Quick start](#quick-start)
2. [How arbitrage betting works](#how-arbitrage-betting-works)
3. [Worked example](#worked-example)
4. [Architecture overview](#architecture-overview)
5. [Plugging in real odds data](#plugging-in-real-odds-data)
6. [Telegram alerts](#telegram-alerts)
7. [Web dashboard](#web-dashboard)
8. [CLI reference](#cli-reference)
9. [Running tests](#running-tests)
10. [Legal disclaimer](#legal-disclaimer)

---

## Quick start

```bash
# 1. Clone and enter the repo
git clone https://github.com/Razzleberryss/Arb_Sports_trader.git
cd Arb_Sports_trader

# 2. Create a virtual environment (Python 3.11+)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Optional) install the package in editable mode for the sports-arb command
pip install -e .

# 5. Run the scanner
python -m sports_arb.cli

# or, after pip install -e .
sports-arb
```

### Example output

```
================================================================================
  🏟   Sports Arbitrage Scanner  (educational use only)
================================================================================

  Providers : mock
  Min edge  : 2.00%  (threshold=0.9800)
  Bankroll  : $100.00

  ✓ mock: fetched 9 odds record(s)

  Found 2 arbitrage opportunity/ies.

────────────────────────────────────────────────────────────────────────────────
  [NBA | NBA]  Los Angeles Lakers  vs  Boston Celtics  (MONEYLINE)
  Game ID   : game_nba_001
  Books     : MockBook_B, MockBook_C
  IP Sum    : 0.8464  Edge: 15.36%
  Profit    : $18.15  (18.15%)  on $100.00 bankroll

    Outcome      Book              Dec. Odds  Stake ($)
    ···················································
    home         MockBook_C           3.1000      38.11
    away         MockBook_B           1.9091      61.89
```

---

## How arbitrage betting works

A **two-way arb** example:

| Outcome | Bookmaker | American odds | Decimal odds | Implied prob |
|---------|-----------|:-------------:|:------------:|:------------:|
| Home win | Book A | +210 | 3.10 | 32.26 % |
| Away win | Book B | −110 | 1.91 | 52.36 % |
| **Total** | | | | **84.62 %** |

Because the implied probability sum (84.62 %) is below 100 %, a guaranteed
profit exists regardless of the outcome.  Stake each leg so that the gross
payout is identical:

```
stake_home = bankroll × (1/3.10) / IP_sum = $100 × 0.3226 / 0.8462 ≈ $38.11
stake_away = bankroll × (1/1.91) / IP_sum = $100 × 0.5236 / 0.8462 ≈ $61.89
```

Both legs return **≈ $118.15** regardless of who wins → **$18.15 profit on $100**.

---

## Worked example

```python
from sports_arb.arb_engine import (
    american_to_decimal,
    compute_implied_prob_sum,
    compute_stakes,
    compute_expected_profit,
)

best_odds = {
    "home": (american_to_decimal(210), "MockBook_C"),  # 3.1
    "away": (american_to_decimal(-110), "MockBook_B"),  # ≈1.909
}

ip_sum = compute_implied_prob_sum(best_odds)
print(f"IP sum: {ip_sum:.4f}")   # 0.8464

stakes = compute_stakes(best_odds, bankroll=100.0)
print(stakes)   # {'home': 38.11, 'away': 61.89}

profit, pct = compute_expected_profit(best_odds, stakes)
print(f"Profit: ${profit:.2f} ({pct:.2f}%)")   # $18.15 (18.15%)
```

---

## Architecture overview

```
src/sports_arb/
├── __init__.py            Package marker, exports __version__
├── config.py              Settings (thresholds, supported sports, .env support)
├── models.py              Typed dataclasses: Outcome, Game, BookmakerOdds,
│                              ArbitrageOpportunity
├── arb_engine.py          Pure-function arbitrage math (no I/O)
│                              american_to_decimal, fractional_to_decimal,
│                              decimal_to_implied_prob, find_best_odds,
│                              compute_implied_prob_sum, compute_stakes,
│                              compute_expected_profit, detect_arbitrage
├── cli.py                 argparse CLI entry point
└── odds_providers/
    ├── __init__.py        Provider registry (PROVIDER_REGISTRY dict)
    ├── base.py            Abstract BaseOddsProvider
    └── mock_provider.py   Hard-coded stub data for local testing

tests/
├── test_arb_engine.py     23 pytest tests for arb_engine.py
└── test_models.py         12 pytest tests for models.py
```

| Layer | Responsibility |
|-------|---------------|
| `models.py` | Immutable data contracts between layers |
| `odds_providers/` | Fetch / parse odds from external sources |
| `arb_engine.py` | Pure math – easy to unit-test in isolation |
| `cli.py` | Orchestration, filtering, formatted output |

---

## Plugging in real odds data

1. **Create a new provider** by subclassing `BaseOddsProvider`:

```python
# src/sports_arb/odds_providers/my_api_provider.py
from sports_arb.odds_providers.base import BaseOddsProvider
from sports_arb.models import BookmakerOdds
import httpx

class MyApiProvider(BaseOddsProvider):
    name = "my_api"

    def get_current_odds(self) -> list[BookmakerOdds]:
        resp = httpx.get("https://api.example.com/odds", headers={
            "Authorization": f"Bearer {os.environ['MY_API_KEY']}"
        })
        resp.raise_for_status()
        return _parse(resp.json())   # your parsing logic
```

2. **Register it** in `src/sports_arb/odds_providers/__init__.py`:

```python
from sports_arb.odds_providers.my_api_provider import MyApiProvider

PROVIDER_REGISTRY["my_api"] = MyApiProvider
```

3. **Store secrets** in a `.env` file (never commit it):

```
MY_API_KEY=sk-...
ARB_THRESHOLD=0.97
```

The package reads `.env` automatically via `python-dotenv` when present.

### Popular free / freemium odds APIs

| Provider | URL | Notes |
|----------|-----|-------|
| The Odds API | https://the-odds-api.com | Free tier, 500 req/month |
| OddsJam | https://oddsjam.com/api | Real-time, paid |
| SportRadar | https://sportradar.com | Enterprise |

> Scraping bookmaker websites may violate their terms of service.  Always
> use official APIs where available.

---

## Telegram alerts

The scanner can push real-time notifications to your phone the instant a live
or pre-game arbitrage opportunity is detected.

### Step 1 – Create a Telegram bot

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot` and follow the prompts to choose a name and username.
3. BotFather will reply with your **bot token** (looks like `123456:ABC-DEF…`).
   Keep it secret.

### Step 2 – Find your chat ID

1. Start a conversation with your new bot by sending it any message (e.g. `/start`).
2. Open this URL in a browser (replace `<TOKEN>` with your actual token):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Look for `"chat":{"id":…}` in the JSON response – that number is your
   **chat ID**.  For a private chat it is a positive integer; for a group it
   starts with a minus sign.

### Step 3 – Configure the scanner

Add the following lines to your `.env` file (copy `.env.example` as a starting
point):

```dotenv
TELEGRAM_BOT_TOKEN=123456:ABC-DEF…
TELEGRAM_CHAT_ID=987654321
```

Optionally override the edge thresholds that trigger an alert:

```dotenv
# Send a live alert when edge ≥ 2 % (default)
ALERT_THRESHOLD_LIVE=2.0

# Send a pre-game alert when edge ≥ 3 % (default)
ALERT_THRESHOLD_PREGAME=3.0
```

### Example alert message

```
⚡ LIVE ARB DETECTED
Game: Lakers vs Celtics (NBA)
Edge: 3.2%
Profit on $100: $3.20
DraftKings → Home ML: +210 → Stake $32.26
FanDuel → Away ML: -110 → Stake $67.74
Implied prob sum: 96.8%
Detected: 8:42:03 PM UTC
```

Pre-game alerts use 🔔 instead of ⚡.

### Fault tolerance

If the Telegram API is unreachable, the token is invalid, or either
`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` is missing, the scanner logs a
warning and continues normally – **alerts never crash the scanner**.

---

## Web dashboard

The scanner ships with a real-time web dashboard powered by **Flask** and
**Flask-SocketIO**.  It displays live and pre-game arbitrage opportunities
as they are detected, updates in real-time via WebSocket, and shows daily
statistics.

> **⚠ Educational use only.** The dashboard is a monitoring tool only.
> No betting logic is included.

### Starting the dashboard

```bash
# Ensure flask and flask-socketio are installed
pip install -r requirements.txt

# Start the dashboard server (port 5000)
python -m sports_arb.dashboard.app
```

Open your browser at **http://localhost:5000**.

### How it works

1. The **scanner** (`scanner.py`) calls `emit_opportunity(opp, type)` after
   each Telegram alert fires.  This is non-blocking – if the dashboard is not
   running the scanner continues normally.
2. The dashboard server caches the last 50 opportunities in memory and
   broadcasts each new one to all connected browsers via a `new_opportunity`
   SocketIO event.
3. The browser receives the event and animates a new row into the table
   without a page reload.

### Dashboard REST endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Single-page dashboard HTML |
| `GET /api/opportunities` | Latest ≤ 50 opportunities as JSON (newest first) |
| `GET /api/stats` | Daily totals: total opps, avg edge %, best edge, scanner status |

### Dashboard features

- **Dark theme** (`#0d1117` background, `#161b22` cards)
- Live scanner **status badge** (green = running, red = stopped)
- **Stats bar**: total opps today, avg edge %, best edge today
- **Opportunities table**: Type badge (LIVE amber / PREGAME blue), Game,
  League, Edge %, Profit on $100, Book 1 home odds, Book 2 away odds,
  Detected At
- **Real-time updates**: new rows flash green briefly when they arrive
- **Mobile responsive**

---

## CLI reference

```
usage: sports-arb [-h] [--min-edge FLOAT] [--sport SPORT] [--book BOOK]
                  [--bankroll FLOAT] [--providers]

options:
  -h, --help          show this help message and exit
  --min-edge FLOAT    Minimum edge % to surface an opportunity (default: 2.0)
  --sport SPORT       Filter by sport: NBA | NFL | soccer
  --book BOOK         Only show opps involving this bookmaker
  --bankroll FLOAT    Total stake for calculations (default: 100.0)
  --providers         List available providers and exit
```

### Examples

```bash
# NBA only, minimum 3 % edge
sports-arb --sport NBA --min-edge 3.0

# $500 bankroll, filter to FanDuel opportunities
sports-arb --bankroll 500 --book FanDuel

# List registered providers
sports-arb --providers
```

---

## Running tests

```bash
pytest               # run all tests
pytest -v            # verbose
pytest tests/test_arb_engine.py   # engine tests only
```

Lint with [Ruff](https://docs.astral.sh/ruff/):

```bash
ruff check src/ tests/
```

---

## Legal disclaimer

This software is provided **for educational and research purposes only**.

- It does not constitute financial, investment, or gambling advice.
- Arbitrage betting may violate the terms and conditions of bookmakers and
  result in account restrictions or closures.
- Gambling laws vary by jurisdiction.  Ensure compliance with all applicable
  laws before engaging in any form of sports wagering.
- The authors accept no liability for any losses incurred as a result of
  using this software.

Always gamble responsibly.  If you have a gambling problem, contact the
[National Problem Gambling Helpline](https://www.ncpgambling.org) at
1-800-522-4700.
