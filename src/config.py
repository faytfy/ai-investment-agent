"""Configuration and constants for the AI Investment Agent."""

import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# Model settings
ANALYST_MODEL = os.getenv("ANALYST_MODEL", "claude-sonnet-4-6")
SYNTHESIZER_MODEL = os.getenv("SYNTHESIZER_MODEL", "claude-opus-4-6")

# Watchlist — AI Supply Chain focused portfolio
WATCHLIST = {
    # Tier 1: Structural Bottleneck Owners
    "TSM": {"name": "Taiwan Semiconductor", "layer": "Foundry/Packaging", "tier": 1},
    "AVGO": {"name": "Broadcom", "layer": "Custom ASIC + Networking", "tier": 1},
    "ASML": {"name": "ASML Holdings", "layer": "Equipment (EUV)", "tier": 1},
    "GEV": {"name": "GE Vernova", "layer": "Power/Grid", "tier": 1},
    "ETN": {"name": "Eaton", "layer": "Power/Transformers", "tier": 1},
    # Tier 2: Strong Moat + Demand Visibility
    "VRT": {"name": "Vertiv", "layer": "Cooling", "tier": 2},
    "MU": {"name": "Micron", "layer": "Memory (HBM)", "tier": 2},
    "CEG": {"name": "Constellation Energy", "layer": "Nuclear Power", "tier": 2},
    "ANET": {"name": "Arista Networks", "layer": "Networking", "tier": 2},
}

# Watch-only (not in active portfolio)
WATCH_ONLY = {
    "NVDA": {"name": "NVIDIA", "layer": "GPU", "note": "Priced for perfection; entry on dips"},
    "PLTR": {"name": "Palantir", "layer": "AI Software", "note": "112x P/S too stretched"},
}

# Database
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "investment.db")

# SEC EDGAR
SEC_EDGAR_BASE_URL = "https://efts.sec.gov/LATEST"
SEC_EDGAR_USER_AGENT = "AIInvestmentAgent research@example.com"

# Analysis settings
ANALYSIS_SCHEDULE = "weekly"  # weekly | daily
CONFIDENCE_THRESHOLD = 0.6  # minimum confidence to surface a signal

# Scheduler
SCHEDULE_DAY_OF_WEEK = os.getenv("SCHEDULE_DAY_OF_WEEK", "sun")
SCHEDULE_HOUR = int(os.getenv("SCHEDULE_HOUR", "18"))
SCHEDULE_MINUTE = int(os.getenv("SCHEDULE_MINUTE", "0"))

# Alerts
EARNINGS_ALERT_DAYS = int(os.getenv("EARNINGS_ALERT_DAYS", "7"))
ALERT_LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "alerts.log")

# Email notifications (off by default)
SMTP_ENABLED = os.getenv("SMTP_ENABLED", "false").lower() == "true"
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_TO = os.getenv("SMTP_TO", "")
