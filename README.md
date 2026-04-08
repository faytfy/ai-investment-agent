# AI Investment Agent

A multi-agent system that analyzes AI supply chain stocks and produces structured buy/sell/hold recommendations. Built with Claude API, LangGraph, and Streamlit.

**Key principle:** Agent recommends, human decides. No auto-trading.

## Architecture

```
  ┌─────────────── DATA LAYER (free APIs) ────────────────┐
  │  Yahoo Finance  |  SEC EDGAR  |  News RSS/APIs        │
  └────────┬──────────────┬──────────────┬────────────────┘
           │              │              │
    Fundamental      Sentiment      Supply Chain
     Analyst          Analyst         Analyst
   (financials,    (news, earnings  (bottlenecks,
    ratios, DCF)    call tone)      capex, tariffs)
           │              │              │
           └──────────┬───┘──────────────┘
                      │
              Research Synthesizer
            (bull vs bear case,
             agreement/disagreement,
             thesis-change detection)
                      │
                Risk Manager
             (position sizing,
              correlation, exposure,
              sector concentration)
                      │
            ┌─────────────────┐
            │   DASHBOARD     │
            │  Portfolio view  │
            │  Stock cards     │
            │  Alerts          │
            │  Action buttons  │
            └─────────────────┘
```

Three analyst agents run in parallel via LangGraph, feed into a synthesizer that produces a unified recommendation, then a risk manager evaluates portfolio-level exposure. Results are displayed in a Streamlit dashboard with automated weekly scheduling and alerting.

## Watchlist

Focused on AI supply chain structural bottlenecks:

| Tier | Ticker | Company | Layer |
|------|--------|---------|-------|
| 1 | TSM | Taiwan Semiconductor | Foundry/Packaging |
| 1 | AVGO | Broadcom | Custom ASIC + Networking |
| 1 | ASML | ASML Holdings | Equipment (EUV) |
| 1 | GEV | GE Vernova | Power/Grid |
| 1 | ETN | Eaton | Power/Transformers |
| 2 | VRT | Vertiv | Cooling |
| 2 | MU | Micron | Memory (HBM) |
| 2 | CEG | Constellation Energy | Nuclear Power |
| 2 | ANET | Arista Networks | Networking |

Watch-only: NVDA, PLTR

## Setup

### Prerequisites

- Python 3.11+
- [Anthropic API key](https://console.anthropic.com/)

### Installation

```bash
git clone https://github.com/faytfy/ai-investment-agent.git
cd ai-investment-agent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### Optional API Keys

- **Alpha Vantage** — Enhanced fundamentals data (free tier: 25 req/day)
- **NewsAPI** — Broader news coverage (free tier: 100 req/day)

The system works with just the Anthropic key; yfinance and SEC EDGAR are free and keyless.

## Usage

### Analyze a Single Stock

```bash
# General analyst
python -m src.agents.runner TSM

# Specific analyst
python -m src.agents.runner TSM --agent fundamental
python -m src.agents.runner TSM --agent sentiment
python -m src.agents.runner TSM --agent supply_chain
```

### Run Full Orchestrated Pipeline

```bash
# Single ticker: 3 analysts in parallel → synthesizer
python -m src.agents.runner TSM --orchestrate

# All watchlist tickers
python -m src.agents.runner --all --orchestrate
```

### Run Portfolio Risk Assessment

```bash
# Reads latest synthesis reports and evaluates portfolio-level risk
python -m src.agents.runner --risk
```

### Launch Dashboard

```bash
streamlit run src/dashboard/app.py
```

### Automated Scheduling

```bash
# Start the weekly scheduler (runs every Sunday at 6 PM by default)
python -m src.automation.scheduler

# Run the full pipeline once immediately
python -m src.automation.scheduler --run-now
```

Schedule timing is configurable via environment variables:

```bash
SCHEDULE_DAY_OF_WEEK=sun  # mon, tue, wed, thu, fri, sat, sun
SCHEDULE_HOUR=18
SCHEDULE_MINUTE=0
```

### Email Notifications (Optional)

```bash
SMTP_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=app-password
SMTP_TO=you@gmail.com
```

Alerts are always written to `data/alerts.log` regardless of email settings.

## Project Structure

```
src/
├── agents/
│   ├── analyst.py          # General analyst agent
│   ├── base.py             # Shared agent utilities
│   ├── fundamental.py      # Fundamental analyst (financials, ratios)
│   ├── sentiment.py        # Sentiment analyst (news, filings tone)
│   ├── supply_chain.py     # Supply chain analyst (bottlenecks, capex)
│   ├── synthesizer.py      # Research synthesizer (unified recommendation)
│   ├── risk_manager.py     # Portfolio risk manager
│   ├── runner.py           # CLI entry point for all agents
│   └── prompts/            # System prompts for each agent
├── automation/
│   ├── alerts.py           # Signal change & earnings alert detection
│   ├── earnings.py         # Earnings calendar from yfinance
│   ├── notifier.py         # Log file + optional email dispatch
│   └── scheduler.py        # APScheduler weekly cron
├── dashboard/
│   ├── app.py              # Streamlit dashboard
│   └── data_loader.py      # Cached DB readers for dashboard
├── data/
│   ├── models.py           # Pydantic data models
│   ├── price.py            # yfinance price data
│   ├── fundamentals.py     # yfinance fundamentals
│   ├── edgar.py            # SEC EDGAR filings
│   └── news.py             # News feed aggregation
├── db/
│   ├── schema.py           # SQLite schema
│   └── operations.py       # DB read/write operations
├── orchestrator/
│   └── graph.py            # LangGraph parallel analyst orchestration
├── utils/
│   └── logger.py           # Structured logging
└── config.py               # Watchlist, API keys, constants
tests/
├── test_integration.py     # Full pipeline E2E tests
├── test_automation.py      # Scheduler, alerts, earnings
├── test_dashboard.py       # Dashboard data loaders
├── test_risk_manager.py    # Risk manager agent
├── test_synthesizer.py     # Synthesizer + orchestrator
├── test_fundamental.py     # Fundamental analyst
├── test_sentiment.py       # Sentiment analyst
├── test_supply_chain.py    # Supply chain analyst
├── test_agent.py           # General analyst
├── test_edgar_news.py      # SEC EDGAR + news
└── test_data.py            # Price + fundamentals data layer
```

## Tech Stack

- **LLM:** Claude (Sonnet for analysts, Opus for synthesizer)
- **Orchestration:** LangGraph (parallel analyst execution)
- **Data:** yfinance, SEC EDGAR, RSS feeds
- **Database:** SQLite
- **Dashboard:** Streamlit + Plotly
- **Scheduling:** APScheduler
- **Models:** Pydantic v2

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test module
python -m pytest tests/test_integration.py -v

# Tests requiring an API key are skipped automatically
```

346 tests across 11 test modules. E2E tests that require a live API key are automatically skipped when `ANTHROPIC_API_KEY` is not set.

## License

Private project. Not for redistribution.
