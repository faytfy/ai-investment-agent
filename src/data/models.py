"""Pydantic data models for the AI Investment Agent."""

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class StockInfo(BaseModel):
    """A stock in the watchlist."""

    ticker: str
    name: str
    layer: str
    tier: int = Field(ge=0, le=2)  # 0 = watch-only, 1-2 = active tiers


class PriceBar(BaseModel):
    """A single day's OHLCV data."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    adj_close: Optional[float] = None

    @field_validator("open", "high", "low", "close")
    @classmethod
    def price_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"Price must be positive, got {v}")
        return v

    @field_validator("volume")
    @classmethod
    def volume_must_be_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"Volume must be non-negative, got {v}")
        return v

    @field_validator("date")
    @classmethod
    def date_not_in_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError(f"Date cannot be in the future: {v}")
        return v


class PriceHistory(BaseModel):
    """Price history for a ticker."""

    ticker: str
    bars: list[PriceBar]
    period: str = "2y"
    last_updated: datetime = Field(default_factory=datetime.now)

    @property
    def is_empty(self) -> bool:
        return len(self.bars) == 0


class FundamentalsSnapshot(BaseModel):
    """A point-in-time snapshot of a stock's fundamental data.

    All financial fields are Optional because yfinance returns different
    fields for different tickers (e.g., recently IPO'd stocks may lack history).
    """

    ticker: str
    fetched_at: datetime = Field(default_factory=datetime.now)

    # Income statement
    revenue: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    net_income: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None

    # Balance sheet
    total_debt: Optional[float] = None
    total_cash: Optional[float] = None
    debt_to_equity: Optional[float] = None

    # Cash flow
    free_cash_flow: Optional[float] = None
    capital_expenditure: Optional[float] = None

    # Valuation ratios
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    ps_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None
    ev_to_ebitda: Optional[float] = None

    # Market data
    market_cap: Optional[float] = None
    enterprise_value: Optional[float] = None
    beta: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None

    # Analyst data
    analyst_target_mean: Optional[float] = None
    analyst_target_median: Optional[float] = None
    analyst_target_high: Optional[float] = None
    analyst_target_low: Optional[float] = None
    analyst_count: Optional[int] = None
    recommendation: Optional[str] = None

    @field_validator("gross_margin", "operating_margin", "net_margin")
    @classmethod
    def margin_sanity_check(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < -10 or v > 10):
            raise ValueError(f"Margin out of sanity range [-10, 10]: {v}")
        return v

    @field_validator("pe_ratio", "forward_pe")
    @classmethod
    def pe_must_be_positive_if_present(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            return None  # Negative P/E means losses — store as None
        return v

    @property
    def has_financials(self) -> bool:
        """Whether we have at least basic financial data."""
        return self.revenue is not None or self.net_income is not None

    @property
    def has_analyst_data(self) -> bool:
        """Whether we have analyst target data."""
        return self.analyst_target_mean is not None


# --- SEC EDGAR models ---


class FilingType(str, Enum):
    """SEC filing types we track."""

    TEN_K = "10-K"
    TEN_Q = "10-Q"
    EIGHT_K = "8-K"


class FilingInfo(BaseModel):
    """Metadata about a single SEC filing."""

    ticker: str
    cik: str
    accession_number: str
    filing_type: FilingType
    filed_date: date
    report_date: Optional[date] = None
    title: Optional[str] = None
    filing_url: str

    @field_validator("cik")
    @classmethod
    def cik_must_be_numeric(cls, v: str) -> str:
        if not v.strip().isdigit():
            raise ValueError(f"CIK must be numeric, got '{v}'")
        return v.strip().lstrip("0") or "0"


class FilingContent(BaseModel):
    """Parsed content from an SEC filing.

    Stores key sections extracted from 10-K/10-Q filings as plain text.
    Sections may be None if not found or not applicable to the filing type.
    """

    accession_number: str
    filing_type: FilingType
    business: Optional[str] = None  # Item 1 (10-K)
    risk_factors: Optional[str] = None  # Item 1A
    mda: Optional[str] = None  # Management Discussion & Analysis (Item 7 / Item 2)
    financial_summary: Optional[str] = None  # Brief extracted financial highlights
    raw_text_length: int = 0  # Total chars of raw filing, for reference

    @property
    def has_content(self) -> bool:
        return any([self.business, self.risk_factors, self.mda])


# --- News models ---


class NewsArticle(BaseModel):
    """A single news article."""

    ticker: str
    title: str
    source: Optional[str] = None
    url: Optional[str] = None
    published_at: datetime
    summary: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Article title cannot be empty")
        return v


class NewsFeed(BaseModel):
    """Collection of news articles for a ticker."""

    ticker: str
    articles: list[NewsArticle]
    last_updated: datetime = Field(default_factory=datetime.now)

    @property
    def is_empty(self) -> bool:
        return len(self.articles) == 0


# --- Analysis report models ---


class Signal(str, Enum):
    """Investment signal."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class AnalysisReport(BaseModel):
    """Structured buy/sell/hold report from an analyst agent.

    Matches the report schema from DESIGN.md Section 4.2.
    """

    ticker: str
    agent: str = "general_analyst"
    report_date: date = Field(default_factory=date.today)
    signal: Signal
    confidence: float = Field(ge=0.0, le=1.0)
    thesis: str
    key_metrics: dict[str, Optional[float]] = Field(default_factory=dict)
    bull_case: str
    bear_case: str
    risks: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    thesis_change: bool = False
    thesis_change_reason: Optional[str] = None

    @field_validator("thesis", "bull_case", "bear_case")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Text field cannot be empty")
        return v

    @field_validator("risks", "evidence")
    @classmethod
    def list_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Must provide at least one item")
        return v


class SynthesisReport(BaseModel):
    """Unified investment memo produced by the Research Synthesizer.

    Reads all analyst reports for a ticker and produces a single
    recommendation with agreement/disagreement analysis.
    Matches DESIGN.md Section 4.2 unified memo schema.
    """

    ticker: str
    report_date: date = Field(default_factory=date.today)
    overall_signal: Signal
    overall_confidence: float = Field(ge=0.0, le=1.0)
    analyst_agreement: str  # e.g., "2/3 bullish, 1/3 neutral"
    disagreement_flags: list[str] = Field(default_factory=list)
    bull_case_summary: str
    bear_case_summary: str
    recommendation: str  # e.g., "HOLD — thesis intact, no action needed"
    thesis_changed_since_last: bool = False
    key_watch_items: list[str] = Field(default_factory=list)
    analyst_reports_used: list[str] = Field(default_factory=list)  # agent names

    @field_validator("bull_case_summary", "bear_case_summary", "recommendation", "analyst_agreement")
    @classmethod
    def synth_text_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Text field cannot be empty")
        return v

    @field_validator("key_watch_items")
    @classmethod
    def watch_items_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Must provide at least one watch item")
        return [item.strip() for item in v if item.strip()]


# --- Portfolio Risk Report ---


class RiskLevel(str, Enum):
    """Portfolio risk level."""

    LOW = "low"
    MODERATE = "moderate"
    ELEVATED = "elevated"
    HIGH = "high"


class PortfolioRiskReport(BaseModel):
    """Portfolio-level risk assessment produced by the Risk Manager.

    Reads all synthesis reports across the watchlist and evaluates
    sector exposure, concentration, correlation, and position sizing.
    Matches DESIGN.md Section 4.2 risk manager schema.
    """

    report_date: date = Field(default_factory=date.today)
    portfolio_signals: list[dict] = Field(default_factory=list)
    sector_exposure: dict[str, float] = Field(default_factory=dict)
    concentration_warnings: list[str] = Field(default_factory=list)
    correlation_flags: list[str] = Field(default_factory=list)
    position_sizing: dict[str, dict] = Field(default_factory=dict)
    overall_risk_level: RiskLevel
    risk_summary: str
    recommendations: list[str] = Field(default_factory=list)
    tickers_analyzed: list[str] = Field(default_factory=list)

    @field_validator("risk_summary")
    @classmethod
    def risk_summary_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Risk summary cannot be empty")
        return v

    @field_validator("recommendations")
    @classmethod
    def recommendations_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Must provide at least one recommendation")
        return v

    @field_validator("sector_exposure")
    @classmethod
    def exposure_values_valid(cls, v: dict[str, float]) -> dict[str, float]:
        for sector, weight in v.items():
            if weight < 0 or weight > 1:
                raise ValueError(f"Sector weight must be 0-1, got {weight} for {sector}")
        return v


# --- Alerts & Automation ---


class AlertType(str, Enum):
    """Types of alerts the system can generate."""

    SIGNAL_CHANGE = "signal_change"
    THESIS_CHANGE = "thesis_change"
    EARNINGS_APPROACHING = "earnings_approaching"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"


class AlertSeverity(str, Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertRecord(BaseModel):
    """A single alert generated by the automation system."""

    ticker: Optional[str] = None  # None for portfolio-level alerts
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    detail: str
    created_at: datetime = Field(default_factory=datetime.now)
    acknowledged: bool = False

    @field_validator("title", "detail")
    @classmethod
    def alert_text_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Alert text cannot be empty")
        return v


class EarningsEvent(BaseModel):
    """An upcoming earnings event for a ticker."""

    ticker: str
    earnings_date: date
    estimate_eps: Optional[float] = None
    fetched_at: datetime = Field(default_factory=datetime.now)
