"""Pydantic data models for the AI Investment Agent."""

from datetime import date, datetime
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
