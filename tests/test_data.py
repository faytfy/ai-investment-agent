"""Tests for the data pipeline — Phase 1a.

These are integration tests that hit the real yfinance API.
They verify that our data models, DB operations, and fetchers
work correctly with real-world data.
"""

import json
import os
import sqlite3
import tempfile
from datetime import date, datetime

import pandas as pd
import pytest

from src.data.models import FundamentalsSnapshot, PriceBar, PriceHistory, StockInfo
from src.db.operations import (
    get_connection,
    get_latest_fundamentals,
    get_prices,
    get_prices_df,
    get_reports,
    get_stocks,
    init_db,
    save_report,
    upsert_fundamentals,
    upsert_prices,
)


# --- Fixtures ---


@pytest.fixture
def tmp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    os.unlink(db_path)


# --- Model validation tests ---


class TestPriceBar:
    def test_valid_price_bar(self):
        bar = PriceBar(
            date=date(2026, 1, 2),
            open=150.0, high=155.0, low=149.0, close=153.0,
            volume=1000000,
        )
        assert bar.close == 153.0

    def test_rejects_negative_price(self):
        with pytest.raises(ValueError, match="positive"):
            PriceBar(
                date=date(2026, 1, 2),
                open=-10.0, high=155.0, low=149.0, close=153.0,
                volume=1000000,
            )

    def test_rejects_negative_volume(self):
        with pytest.raises(ValueError, match="non-negative"):
            PriceBar(
                date=date(2026, 1, 2),
                open=150.0, high=155.0, low=149.0, close=153.0,
                volume=-1,
            )

    def test_rejects_future_date(self):
        with pytest.raises(ValueError, match="future"):
            PriceBar(
                date=date(2099, 1, 1),
                open=150.0, high=155.0, low=149.0, close=153.0,
                volume=1000000,
            )

    def test_zero_volume_is_valid(self):
        bar = PriceBar(
            date=date(2026, 1, 2),
            open=150.0, high=155.0, low=149.0, close=153.0,
            volume=0,
        )
        assert bar.volume == 0

    def test_none_adj_close(self):
        bar = PriceBar(
            date=date(2026, 1, 2),
            open=150.0, high=155.0, low=149.0, close=153.0,
            volume=1000000, adj_close=None,
        )
        assert bar.adj_close is None


class TestFundamentalsSnapshot:
    def test_all_optional_fields(self):
        """Minimal snapshot with only ticker — all financials None."""
        snapshot = FundamentalsSnapshot(ticker="TSM")
        assert snapshot.ticker == "TSM"
        assert snapshot.revenue is None
        assert not snapshot.has_financials

    def test_with_financials(self):
        snapshot = FundamentalsSnapshot(ticker="TSM", revenue=50e9, net_income=20e9)
        assert snapshot.has_financials
        assert snapshot.revenue == 50e9

    def test_margin_sanity_rejects_wild_values(self):
        with pytest.raises(ValueError, match="sanity range"):
            FundamentalsSnapshot(ticker="TSM", gross_margin=50.0)

    def test_margin_boundary_values(self):
        """Margins at exact boundaries should be accepted."""
        snap = FundamentalsSnapshot(ticker="TSM", gross_margin=-10.0, operating_margin=10.0)
        assert snap.gross_margin == -10.0
        assert snap.operating_margin == 10.0

        with pytest.raises(ValueError):
            FundamentalsSnapshot(ticker="TSM", gross_margin=-10.1)
        with pytest.raises(ValueError):
            FundamentalsSnapshot(ticker="TSM", net_margin=10.1)

    def test_negative_pe_becomes_none(self):
        snapshot = FundamentalsSnapshot(ticker="TSM", pe_ratio=-15.0)
        assert snapshot.pe_ratio is None

    def test_serialization_roundtrip(self):
        """Serialize to JSON and back — no data loss."""
        original = FundamentalsSnapshot(
            ticker="TSM",
            revenue=50e9,
            gross_margin=0.57,
            pe_ratio=22.4,
            analyst_target_mean=200.0,
        )
        json_str = original.model_dump_json()
        restored = FundamentalsSnapshot.model_validate_json(json_str)
        assert restored.ticker == original.ticker
        assert restored.revenue == original.revenue
        assert restored.gross_margin == original.gross_margin


# --- Database tests ---


class TestDatabaseInit:
    def test_creates_tables(self, tmp_db):
        conn = get_connection(tmp_db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = {r["name"] for r in tables}
        assert "stocks" in table_names
        assert "prices" in table_names
        assert "fundamentals" in table_names
        assert "analysis_reports" in table_names
        conn.close()

    def test_seeds_watchlist(self, tmp_db):
        stocks = get_stocks(tmp_db)
        tickers = {s.ticker for s in stocks}
        assert "TSM" in tickers
        assert "AVGO" in tickers
        assert len(stocks) == 9  # 9 active watchlist stocks

    def test_idempotent_init(self, tmp_db):
        """Calling init_db twice doesn't duplicate stocks."""
        init_db(tmp_db)
        stocks = get_stocks(tmp_db)
        assert len(stocks) == 9

    def test_get_stocks_include_watch_only(self, tmp_db):
        """Should return active + watch-only stocks."""
        stocks = get_stocks(tmp_db, include_watch_only=True)
        tickers = {s.ticker for s in stocks}
        assert "TSM" in tickers
        assert "NVDA" in tickers
        assert len(stocks) == 11  # 9 active + 2 watch-only


class TestPriceOperations:
    def test_upsert_and_read_prices(self, tmp_db):
        """Write prices, read them back, verify match."""
        bars = [
            PriceBar(date=date(2026, 1, 2), open=150.0, high=155.0, low=149.0, close=153.0, volume=1000000),
            PriceBar(date=date(2026, 1, 3), open=153.0, high=158.0, low=152.0, close=157.0, volume=1200000),
        ]
        history = PriceHistory(ticker="TSM", bars=bars)
        count = upsert_prices("TSM", history, db_path=tmp_db)
        assert count == 2

        result = get_prices("TSM", db_path=tmp_db)
        assert len(result.bars) == 2
        assert result.bars[0].close == 153.0
        assert result.bars[1].close == 157.0

    def test_upsert_is_idempotent(self, tmp_db):
        """Upserting the same data twice doesn't create duplicates."""
        bars = [
            PriceBar(date=date(2026, 1, 2), open=150.0, high=155.0, low=149.0, close=153.0, volume=1000000),
        ]
        history = PriceHistory(ticker="TSM", bars=bars)
        upsert_prices("TSM", history, db_path=tmp_db)
        upsert_prices("TSM", history, db_path=tmp_db)

        result = get_prices("TSM", db_path=tmp_db)
        assert len(result.bars) == 1

    def test_date_range_filter(self, tmp_db):
        bars = [
            PriceBar(date=date(2026, 1, 2), open=150.0, high=155.0, low=149.0, close=153.0, volume=1000000),
            PriceBar(date=date(2026, 1, 3), open=153.0, high=158.0, low=152.0, close=157.0, volume=1200000),
            PriceBar(date=date(2026, 1, 6), open=157.0, high=160.0, low=155.0, close=159.0, volume=900000),
        ]
        history = PriceHistory(ticker="TSM", bars=bars)
        upsert_prices("TSM", history, db_path=tmp_db)

        result = get_prices("TSM", start=date(2026, 1, 3), end=date(2026, 1, 3), db_path=tmp_db)
        assert len(result.bars) == 1
        assert result.bars[0].date == date(2026, 1, 3)

    def test_empty_history_returns_zero(self, tmp_db):
        history = PriceHistory(ticker="TSM", bars=[])
        count = upsert_prices("TSM", history, db_path=tmp_db)
        assert count == 0

    def test_get_prices_df_returns_dataframe(self, tmp_db):
        bars = [
            PriceBar(date=date(2026, 1, 2), open=150.0, high=155.0, low=149.0, close=153.0, volume=1000000),
        ]
        upsert_prices("TSM", PriceHistory(ticker="TSM", bars=bars), db_path=tmp_db)
        df = get_prices_df("TSM", db_path=tmp_db)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert df.iloc[0]["close"] == 153.0

    def test_get_prices_df_empty(self, tmp_db):
        df = get_prices_df("TSM", db_path=tmp_db)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_none_adj_close_roundtrip(self, tmp_db):
        """adj_close=None should survive write→read."""
        bars = [
            PriceBar(date=date(2026, 1, 2), open=150.0, high=155.0, low=149.0, close=153.0, volume=1000000, adj_close=None),
        ]
        upsert_prices("TSM", PriceHistory(ticker="TSM", bars=bars), db_path=tmp_db)
        result = get_prices("TSM", db_path=tmp_db)
        assert result.bars[0].adj_close is None


class TestFundamentalsOperations:
    def test_upsert_and_read_fundamentals(self, tmp_db):
        snapshot = FundamentalsSnapshot(
            ticker="TSM",
            revenue=50e9,
            gross_margin=0.57,
            pe_ratio=22.4,
            analyst_target_mean=200.0,
        )
        upsert_fundamentals(snapshot, db_path=tmp_db)

        result = get_latest_fundamentals("TSM", db_path=tmp_db)
        assert result is not None
        assert result.ticker == "TSM"
        assert result.revenue == 50e9
        assert result.gross_margin == 0.57

    def test_returns_none_for_missing_ticker(self, tmp_db):
        result = get_latest_fundamentals("DOESNOTEXIST", db_path=tmp_db)
        assert result is None

    def test_returns_latest_snapshot(self, tmp_db):
        """When multiple snapshots exist, returns the most recent."""
        old = FundamentalsSnapshot(
            ticker="TSM", revenue=40e9,
            fetched_at=datetime(2026, 1, 1),
        )
        new = FundamentalsSnapshot(
            ticker="TSM", revenue=50e9,
            fetched_at=datetime(2026, 4, 1),
        )
        upsert_fundamentals(old, db_path=tmp_db)
        upsert_fundamentals(new, db_path=tmp_db)

        result = get_latest_fundamentals("TSM", db_path=tmp_db)
        assert result is not None
        assert result.revenue == 50e9


class TestReportOperations:
    def test_save_and_retrieve_report(self, tmp_db):
        report = {"signal": "bullish", "thesis": "Strong demand"}
        save_report("TSM", "fundamental_analyst", date(2026, 4, 1), report, "bullish", 0.85, db_path=tmp_db)

        reports = get_reports("TSM", db_path=tmp_db)
        assert len(reports) == 1
        assert reports[0]["signal"] == "bullish"
        assert reports[0]["confidence"] == 0.85
        assert reports[0]["report"]["thesis"] == "Strong demand"

    def test_filter_by_agent(self, tmp_db):
        save_report("TSM", "fundamental_analyst", date(2026, 4, 1), {}, "bullish", 0.8, db_path=tmp_db)
        save_report("TSM", "sentiment_analyst", date(2026, 4, 1), {}, "neutral", 0.5, db_path=tmp_db)

        fundamental = get_reports("TSM", agent_name="fundamental_analyst", db_path=tmp_db)
        assert len(fundamental) == 1
        assert fundamental[0]["agent_name"] == "fundamental_analyst"

    def test_reports_ordered_by_date_desc(self, tmp_db):
        save_report("TSM", "fundamental_analyst", date(2026, 3, 1), {}, "neutral", 0.5, db_path=tmp_db)
        save_report("TSM", "fundamental_analyst", date(2026, 4, 1), {}, "bullish", 0.8, db_path=tmp_db)

        reports = get_reports("TSM", db_path=tmp_db)
        assert reports[0]["date"] == "2026-04-01"
        assert reports[1]["date"] == "2026-03-01"


# --- yfinance integration tests ---
# These hit the real API — they verify our code works with actual data.


class TestYfinancePriceFetch:
    def test_fetch_tsm_prices(self):
        """Fetch real price data for TSM and validate structure."""
        from src.data.price import fetch_price_history

        history = fetch_price_history("TSM", period="1mo")
        assert history is not None
        assert history.ticker == "TSM"
        assert not history.is_empty
        assert len(history.bars) > 10  # ~20 trading days in a month

        bar = history.bars[0]
        assert bar.open > 0
        assert bar.high >= bar.low
        assert bar.volume >= 0

    def test_bad_ticker_returns_empty(self):
        """A nonsense ticker should return empty, not crash."""
        from src.data.price import fetch_price_history

        history = fetch_price_history("ZZZZNOTREAL123", period="1mo")
        assert history is not None
        assert history.is_empty

    def test_prices_are_chronologically_ordered(self):
        """Bars should come back in date order."""
        from src.data.price import fetch_price_history

        history = fetch_price_history("TSM", period="1mo")
        assert history is not None
        assert len(history.bars) > 1
        for i in range(len(history.bars) - 1):
            assert history.bars[i].date <= history.bars[i + 1].date


class TestYfinanceCurrentQuote:
    def test_fetch_current_quote(self):
        from src.data.price import fetch_current_quote

        quote = fetch_current_quote("TSM")
        assert quote is not None
        assert quote["ticker"] == "TSM"
        assert quote["price"] is not None
        assert quote["price"] > 0

    def test_bad_ticker_quote(self):
        from src.data.price import fetch_current_quote

        quote = fetch_current_quote("ZZZZNOTREAL123")
        # Should either return None or a quote with None price
        if quote is not None:
            assert quote["price"] is None


class TestYfinanceFundamentalsFetch:
    def test_fetch_tsm_fundamentals(self):
        """Fetch real fundamentals for TSM and validate key fields."""
        from src.data.fundamentals import fetch_fundamentals

        snapshot = fetch_fundamentals("TSM")
        assert snapshot is not None
        assert snapshot.ticker == "TSM"
        assert snapshot.has_financials
        assert snapshot.market_cap is not None
        assert snapshot.market_cap > 0

    def test_fundamentals_have_analyst_data(self):
        """TSM should have analyst coverage."""
        from src.data.fundamentals import fetch_fundamentals

        snapshot = fetch_fundamentals("TSM")
        assert snapshot is not None
        assert snapshot.has_analyst_data
        assert snapshot.analyst_target_mean is not None
        assert snapshot.analyst_target_mean > 0
