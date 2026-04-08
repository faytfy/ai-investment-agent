"""Tests for the automation & alerts module (Phase 6)."""

import json
import logging
import os
import tempfile
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.data.models import (
    AlertRecord,
    AlertSeverity,
    AlertType,
    EarningsEvent,
)
from src.db.operations import (
    alert_exists_today,
    get_alerts,
    get_upcoming_earnings,
    init_db,
    save_alert,
    save_report,
    upsert_earnings,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def db_path():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(db_path=path)
    yield path
    os.unlink(path)


SYNTHESIZER_AGENT = "research_synthesizer"


def _save_synthesis(ticker, signal, confidence, db_path, report_date=None, **extra):
    """Helper to save a synthesis report."""
    report = {
        "ticker": ticker,
        "overall_signal": signal,
        "overall_confidence": confidence,
        "analyst_agreement": "3/3",
        "disagreement_flags": [],
        "bull_case_summary": "Strong growth",
        "bear_case_summary": "Valuation risk",
        "recommendation": "HOLD",
        "thesis_changed_since_last": extra.get("thesis_changed_since_last", False),
        "key_watch_items": ["Next earnings"],
        "analyst_reports_used": [],
    }
    save_report(
        ticker=ticker,
        agent_name=SYNTHESIZER_AGENT,
        report_date=report_date or date.today(),
        report=report,
        signal=signal,
        confidence=confidence,
        db_path=db_path,
    )


# ============================================================
# Alert Model Tests
# ============================================================


class TestAlertModels:
    def test_alert_record_valid(self):
        alert = AlertRecord(
            ticker="TSM",
            alert_type=AlertType.SIGNAL_CHANGE,
            severity=AlertSeverity.CRITICAL,
            title="TSM signal changed",
            detail="Changed from bullish to bearish",
        )
        assert alert.ticker == "TSM"
        assert alert.acknowledged is False

    def test_alert_record_no_ticker(self):
        alert = AlertRecord(
            alert_type=AlertType.RUN_COMPLETED,
            severity=AlertSeverity.INFO,
            title="Run completed",
            detail="Pipeline done",
        )
        assert alert.ticker is None

    def test_alert_record_empty_title_fails(self):
        with pytest.raises(ValueError):
            AlertRecord(
                alert_type=AlertType.SIGNAL_CHANGE,
                severity=AlertSeverity.INFO,
                title="  ",
                detail="Some detail",
            )

    def test_alert_record_empty_detail_fails(self):
        with pytest.raises(ValueError):
            AlertRecord(
                alert_type=AlertType.SIGNAL_CHANGE,
                severity=AlertSeverity.INFO,
                title="Some title",
                detail="",
            )

    def test_earnings_event_valid(self):
        event = EarningsEvent(
            ticker="TSM",
            earnings_date=date(2026, 4, 17),
            estimate_eps=1.50,
        )
        assert event.ticker == "TSM"
        assert event.estimate_eps == 1.50

    def test_earnings_event_no_eps(self):
        event = EarningsEvent(
            ticker="AVGO",
            earnings_date=date(2026, 5, 1),
        )
        assert event.estimate_eps is None


# ============================================================
# Alert DB Operations Tests
# ============================================================


class TestAlertDBOps:
    def test_save_and_get_alerts(self, db_path):
        alert = AlertRecord(
            ticker="TSM",
            alert_type=AlertType.SIGNAL_CHANGE,
            severity=AlertSeverity.WARNING,
            title="TSM signal changed",
            detail="bullish to neutral",
        )
        save_alert(alert, db_path=db_path)

        alerts = get_alerts(limit=10, db_path=db_path)
        assert len(alerts) == 1
        assert alerts[0]["ticker"] == "TSM"
        assert alerts[0]["alert_type"] == "signal_change"
        assert alerts[0]["severity"] == "warning"

    def test_get_alerts_newest_first(self, db_path):
        for i, severity in enumerate(["info", "warning", "critical"]):
            alert = AlertRecord(
                ticker="TSM",
                alert_type=AlertType.SIGNAL_CHANGE,
                severity=AlertSeverity(severity),
                title=f"Alert {i}",
                detail=f"Detail {i}",
                created_at=datetime(2026, 4, 1 + i),
            )
            save_alert(alert, db_path=db_path)

        alerts = get_alerts(limit=10, db_path=db_path)
        assert len(alerts) == 3
        # Newest first
        assert alerts[0]["title"] == "Alert 2"
        assert alerts[2]["title"] == "Alert 0"

    def test_get_alerts_unacknowledged_only(self, db_path):
        save_alert(AlertRecord(
            ticker="TSM", alert_type=AlertType.SIGNAL_CHANGE,
            severity=AlertSeverity.INFO, title="Acked", detail="d",
            acknowledged=True,
        ), db_path=db_path)
        save_alert(AlertRecord(
            ticker="AVGO", alert_type=AlertType.THESIS_CHANGE,
            severity=AlertSeverity.WARNING, title="Not acked", detail="d",
        ), db_path=db_path)

        all_alerts = get_alerts(limit=10, db_path=db_path)
        assert len(all_alerts) == 2

        unacked = get_alerts(limit=10, unacknowledged_only=True, db_path=db_path)
        assert len(unacked) == 1
        assert unacked[0]["ticker"] == "AVGO"

    def test_alert_exists_today(self, db_path):
        alert = AlertRecord(
            ticker="TSM",
            alert_type=AlertType.SIGNAL_CHANGE,
            severity=AlertSeverity.WARNING,
            title="TSM signal changed",
            detail="bullish to neutral",
        )
        save_alert(alert, db_path=db_path)

        assert alert_exists_today("TSM", "signal_change", "TSM signal changed", db_path=db_path)
        assert not alert_exists_today("TSM", "thesis_change", "TSM signal changed", db_path=db_path)
        assert not alert_exists_today("AVGO", "signal_change", "TSM signal changed", db_path=db_path)

    def test_alert_exists_today_null_ticker(self, db_path):
        alert = AlertRecord(
            alert_type=AlertType.RUN_COMPLETED,
            severity=AlertSeverity.INFO,
            title="Run completed",
            detail="Pipeline done",
        )
        save_alert(alert, db_path=db_path)

        assert alert_exists_today(None, "run_completed", "Run completed", db_path=db_path)


# ============================================================
# Earnings DB Operations Tests
# ============================================================


class TestEarningsDBOps:
    def test_upsert_and_get_earnings(self, db_path):
        upsert_earnings("TSM", date(2026, 4, 15), estimate_eps=1.50, db_path=db_path)

        upcoming = get_upcoming_earnings(within_days=30, db_path=db_path)
        assert len(upcoming) == 1
        assert upcoming[0]["ticker"] == "TSM"
        assert upcoming[0]["earnings_date"] == "2026-04-15"
        assert upcoming[0]["estimate_eps"] == 1.50

    def test_upcoming_earnings_filters_past(self, db_path):
        past = date.today() - timedelta(days=5)
        upsert_earnings("TSM", past, db_path=db_path)

        upcoming = get_upcoming_earnings(within_days=14, db_path=db_path)
        assert len(upcoming) == 0

    def test_upcoming_earnings_filters_far_future(self, db_path):
        far_future = date.today() + timedelta(days=60)
        upsert_earnings("TSM", far_future, db_path=db_path)

        upcoming = get_upcoming_earnings(within_days=14, db_path=db_path)
        assert len(upcoming) == 0

    def test_upsert_earnings_dedup(self, db_path):
        upsert_earnings("TSM", date(2026, 4, 15), estimate_eps=1.50, db_path=db_path)
        upsert_earnings("TSM", date(2026, 4, 15), estimate_eps=1.60, db_path=db_path)

        upcoming = get_upcoming_earnings(within_days=30, db_path=db_path)
        assert len(upcoming) == 1
        assert upcoming[0]["estimate_eps"] == 1.60  # Updated


# ============================================================
# Signal Change Detection Tests
# ============================================================


MOCK_WATCHLIST = {"TSM": {"name": "Taiwan Semiconductor", "layer": "Foundry", "tier": 1}}
MOCK_WATCH_ONLY = {}


class TestSignalChangeDetection:
    def test_signal_change_detected(self, db_path):
        from src.automation.alerts import detect_signal_changes

        _save_synthesis("TSM", "bullish", 0.8, db_path, report_date=date(2026, 4, 1))
        _save_synthesis("TSM", "neutral", 0.6, db_path, report_date=date(2026, 4, 8))

        with patch("src.automation.alerts.WATCHLIST", MOCK_WATCHLIST), \
             patch("src.automation.alerts.WATCH_ONLY", MOCK_WATCH_ONLY):
            alerts = detect_signal_changes(db_path=db_path)
        assert len(alerts) == 1
        assert alerts[0].ticker == "TSM"
        assert alerts[0].alert_type == AlertType.SIGNAL_CHANGE
        assert "bullish" in alerts[0].title
        assert "neutral" in alerts[0].title

    def test_no_signal_change_no_alert(self, db_path):
        from src.automation.alerts import detect_signal_changes

        _save_synthesis("TSM", "bullish", 0.8, db_path, report_date=date(2026, 4, 1))
        _save_synthesis("TSM", "bullish", 0.9, db_path, report_date=date(2026, 4, 8))

        with patch("src.automation.alerts.WATCHLIST", MOCK_WATCHLIST), \
             patch("src.automation.alerts.WATCH_ONLY", MOCK_WATCH_ONLY):
            alerts = detect_signal_changes(db_path=db_path)
        assert len(alerts) == 0

    def test_single_report_no_alert(self, db_path):
        from src.automation.alerts import detect_signal_changes

        _save_synthesis("TSM", "bullish", 0.8, db_path)

        with patch("src.automation.alerts.WATCHLIST", MOCK_WATCHLIST), \
             patch("src.automation.alerts.WATCH_ONLY", MOCK_WATCH_ONLY):
            alerts = detect_signal_changes(db_path=db_path)
        assert len(alerts) == 0

    def test_bearish_flip_is_critical(self, db_path):
        from src.automation.alerts import detect_signal_changes

        _save_synthesis("TSM", "bullish", 0.8, db_path, report_date=date(2026, 4, 1))
        _save_synthesis("TSM", "bearish", 0.7, db_path, report_date=date(2026, 4, 8))

        with patch("src.automation.alerts.WATCHLIST", MOCK_WATCHLIST), \
             patch("src.automation.alerts.WATCH_ONLY", MOCK_WATCH_ONLY):
            alerts = detect_signal_changes(db_path=db_path)
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.CRITICAL

    def test_neutral_transition_is_warning(self, db_path):
        from src.automation.alerts import detect_signal_changes

        _save_synthesis("TSM", "bullish", 0.8, db_path, report_date=date(2026, 4, 1))
        _save_synthesis("TSM", "neutral", 0.5, db_path, report_date=date(2026, 4, 8))

        with patch("src.automation.alerts.WATCHLIST", MOCK_WATCHLIST), \
             patch("src.automation.alerts.WATCH_ONLY", MOCK_WATCH_ONLY):
            alerts = detect_signal_changes(db_path=db_path)
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.WARNING


# ============================================================
# Thesis Change Detection Tests
# ============================================================


class TestThesisChangeDetection:
    def test_thesis_change_detected(self, db_path):
        from src.automation.alerts import detect_thesis_changes

        _save_synthesis("TSM", "bullish", 0.8, db_path, thesis_changed_since_last=True)

        with patch("src.automation.alerts.WATCHLIST", MOCK_WATCHLIST), \
             patch("src.automation.alerts.WATCH_ONLY", MOCK_WATCH_ONLY):
            alerts = detect_thesis_changes(db_path=db_path)
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.THESIS_CHANGE
        assert alerts[0].severity == AlertSeverity.WARNING

    def test_no_thesis_change_no_alert(self, db_path):
        from src.automation.alerts import detect_thesis_changes

        _save_synthesis("TSM", "bullish", 0.8, db_path, thesis_changed_since_last=False)

        with patch("src.automation.alerts.WATCHLIST", MOCK_WATCHLIST), \
             patch("src.automation.alerts.WATCH_ONLY", MOCK_WATCH_ONLY):
            alerts = detect_thesis_changes(db_path=db_path)
        assert len(alerts) == 0

    def test_no_reports_no_alert(self, db_path):
        from src.automation.alerts import detect_thesis_changes

        with patch("src.automation.alerts.WATCHLIST", MOCK_WATCHLIST), \
             patch("src.automation.alerts.WATCH_ONLY", MOCK_WATCH_ONLY):
            alerts = detect_thesis_changes(db_path=db_path)
        assert len(alerts) == 0


# ============================================================
# Earnings Alert Detection Tests
# ============================================================


class TestEarningsAlerts:
    def test_upcoming_earnings_creates_alert(self, db_path):
        from src.automation.alerts import detect_earnings_alerts

        upcoming_date = date.today() + timedelta(days=3)
        upsert_earnings("TSM", upcoming_date, estimate_eps=1.50, db_path=db_path)

        alerts = detect_earnings_alerts(db_path=db_path)
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.EARNINGS_APPROACHING
        assert alerts[0].severity == AlertSeverity.INFO
        assert "TSM" in alerts[0].title

    def test_no_upcoming_earnings_no_alert(self, db_path):
        from src.automation.alerts import detect_earnings_alerts

        alerts = detect_earnings_alerts(db_path=db_path)
        assert len(alerts) == 0


# ============================================================
# Alert Dedup Tests
# ============================================================


class TestAlertDedup:
    def test_detect_and_fire_deduplicates(self, db_path):
        from src.automation.alerts import detect_and_fire_alerts

        _save_synthesis("TSM", "bullish", 0.8, db_path, report_date=date(2026, 4, 1))
        _save_synthesis("TSM", "bearish", 0.7, db_path, report_date=date(2026, 4, 8))

        with patch("src.automation.alerts.WATCHLIST", MOCK_WATCHLIST), \
             patch("src.automation.alerts.WATCH_ONLY", MOCK_WATCH_ONLY):
            # First run — should save
            alerts1 = detect_and_fire_alerts(db_path=db_path)
            assert len(alerts1) >= 1

            # Second run same day — should skip duplicates
            alerts2 = detect_and_fire_alerts(db_path=db_path)
            assert len(alerts2) == 0

        # DB should only have alerts from first run (plus no duplicates)
        all_db_alerts = get_alerts(limit=100, db_path=db_path)
        signal_change_alerts = [a for a in all_db_alerts if a["alert_type"] == "signal_change"]
        assert len(signal_change_alerts) == 1


# ============================================================
# Earnings Fetcher Tests
# ============================================================


class TestEarningsFetcher:
    def test_fetch_earnings_date_dict_format(self):
        from src.automation.earnings import _fetch_earnings_date

        mock_ticker = MagicMock()
        mock_ticker.calendar = {"Earnings Date": [date(2026, 5, 15)]}

        with patch("src.automation.earnings.yf.Ticker", return_value=mock_ticker):
            result = _fetch_earnings_date("TSM")

        assert result == date(2026, 5, 15)

    def test_fetch_earnings_date_empty_calendar(self):
        from src.automation.earnings import _fetch_earnings_date

        mock_ticker = MagicMock()
        mock_ticker.calendar = {}

        with patch("src.automation.earnings.yf.Ticker", return_value=mock_ticker):
            result = _fetch_earnings_date("TSM")

        assert result is None

    def test_fetch_earnings_date_exception(self):
        from src.automation.earnings import _fetch_earnings_date

        with patch("src.automation.earnings.yf.Ticker", side_effect=Exception("network error")):
            result = _fetch_earnings_date("TSM")

        assert result is None

    def test_refresh_earnings_calendar(self, db_path):
        from src.automation.earnings import refresh_earnings_calendar

        mock_ticker = MagicMock()
        mock_ticker.calendar = {"Earnings Date": [date(2026, 5, 15)]}

        with patch("src.automation.earnings.yf.Ticker", return_value=mock_ticker), \
             patch("src.automation.earnings.WATCHLIST", MOCK_WATCHLIST), \
             patch("src.automation.earnings.WATCH_ONLY", MOCK_WATCH_ONLY), \
             patch("src.automation.earnings.time.sleep"):
            results = refresh_earnings_calendar(db_path=db_path)

        assert results["TSM"] == date(2026, 5, 15)
        # Verify stored in DB
        upcoming = get_upcoming_earnings(within_days=60, db_path=db_path)
        assert len(upcoming) == 1
        assert upcoming[0]["ticker"] == "TSM"

    def test_refresh_earnings_skips_failed_tickers(self, db_path):
        from src.automation.earnings import refresh_earnings_calendar

        with patch("src.automation.earnings.yf.Ticker", side_effect=Exception("fail")), \
             patch("src.automation.earnings.WATCHLIST", MOCK_WATCHLIST), \
             patch("src.automation.earnings.WATCH_ONLY", MOCK_WATCH_ONLY), \
             patch("src.automation.earnings.time.sleep"):
            results = refresh_earnings_calendar(db_path=db_path)

        assert results["TSM"] is None
        upcoming = get_upcoming_earnings(within_days=60, db_path=db_path)
        assert len(upcoming) == 0


# ============================================================
# Notifier Tests
# ============================================================


class TestNotifier:
    def test_log_alerts_writes_to_file(self, tmp_path):
        from src.automation.notifier import _log_alerts, _alert_logger

        # Reset the cached logger so we can redirect it
        import src.automation.notifier as notifier_mod
        notifier_mod._alert_logger = None

        log_file = str(tmp_path / "test_alerts.log")
        with patch("src.automation.notifier.ALERT_LOG_PATH", log_file):
            alerts = [
                AlertRecord(
                    ticker="TSM",
                    alert_type=AlertType.SIGNAL_CHANGE,
                    severity=AlertSeverity.CRITICAL,
                    title="TSM signal changed",
                    detail="bullish to bearish",
                ),
            ]
            _log_alerts(alerts)

        # Reset again for isolation
        notifier_mod._alert_logger = None

        content = open(log_file).read()
        assert "signal_change" in content
        assert "TSM" in content

    def test_empty_alerts_no_op(self):
        from src.automation.notifier import notify

        # Should not raise
        notify([])

    def test_email_not_sent_when_disabled(self):
        from src.automation.notifier import notify

        alerts = [
            AlertRecord(
                alert_type=AlertType.RUN_COMPLETED,
                severity=AlertSeverity.INFO,
                title="Run completed",
                detail="Done",
            ),
        ]

        with patch("src.automation.notifier.SMTP_ENABLED", False), \
             patch("src.automation.notifier.smtplib") as mock_smtp:
            notify(alerts)
            mock_smtp.SMTP.assert_not_called()

    def test_email_failure_does_not_raise(self):
        from src.automation.notifier import _send_email

        alerts = [
            AlertRecord(
                alert_type=AlertType.RUN_COMPLETED,
                severity=AlertSeverity.INFO,
                title="Run completed",
                detail="Done",
            ),
        ]

        with patch("src.automation.notifier.SMTP_HOST", "bad.host"), \
             patch("src.automation.notifier.SMTP_TO", "test@example.com"), \
             patch("src.automation.notifier.smtplib.SMTP", side_effect=Exception("conn refused")):
            # Should not raise
            _send_email(alerts)


# ============================================================
# Scheduler Pipeline Tests
# ============================================================


class TestSchedulerPipeline:
    def test_scheduled_run_calls_pipeline(self, db_path):
        from src.automation.scheduler import scheduled_run

        with patch("src.agents.runner.run_all_orchestrated") as mock_orch, \
             patch("src.agents.runner.run_risk") as mock_risk, \
             patch("src.automation.earnings.refresh_earnings_calendar") as mock_earn, \
             patch("src.automation.alerts.detect_and_fire_alerts", return_value=[]) as mock_alerts, \
             patch("src.automation.notifier.notify") as mock_notify:

            scheduled_run(db_path=db_path)

            mock_orch.assert_called_once_with(save=True)
            mock_risk.assert_called_once_with(save=True)
            mock_earn.assert_called_once()
            mock_alerts.assert_called_once()
            mock_notify.assert_called_once()

        # Should have saved a run_completed alert
        alerts = get_alerts(limit=10, db_path=db_path)
        run_alerts = [a for a in alerts if a["alert_type"] == "run_completed"]
        assert len(run_alerts) == 1

    def test_step_failure_continues_pipeline(self, db_path):
        """When orchestration fails, the pipeline continues to risk/earnings/alerts."""
        from src.automation.scheduler import scheduled_run

        with patch("src.agents.runner.run_all_orchestrated", side_effect=Exception("API down")), \
             patch("src.agents.runner.run_risk") as mock_risk, \
             patch("src.automation.earnings.refresh_earnings_calendar") as mock_earn, \
             patch("src.automation.alerts.detect_and_fire_alerts", return_value=[]) as mock_alerts, \
             patch("src.automation.notifier.notify") as mock_notify:

            scheduled_run(db_path=db_path)

            # Pipeline should have continued past step 1 failure
            mock_risk.assert_called_once()
            mock_earn.assert_called_once()
            mock_alerts.assert_called_once()

        # Should have saved a run_completed alert (not run_failed)
        alerts = get_alerts(limit=10, db_path=db_path)
        completed = [a for a in alerts if a["alert_type"] == "run_completed"]
        assert len(completed) == 1

    def test_run_failed_alert_on_fatal_exception(self, db_path):
        """When init_db itself fails, the entire pipeline fails with run_failed alert."""
        from src.automation.scheduler import scheduled_run

        with patch("src.automation.scheduler.init_db", side_effect=Exception("DB corrupted")), \
             patch("src.automation.notifier.notify") as mock_notify:

            scheduled_run(db_path=db_path)

        # Should have notified about the failure
        mock_notify.assert_called_once()
        fail_alerts = mock_notify.call_args[0][0]
        assert any(a.alert_type.value == "run_failed" for a in fail_alerts)

    def test_run_now_flag_parses(self):
        from src.automation.scheduler import main
        import argparse

        with patch("src.automation.scheduler.scheduled_run") as mock_run, \
             patch("sys.argv", ["scheduler", "--run-now"]):
            main()
            mock_run.assert_called_once()
