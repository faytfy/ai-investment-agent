"""Alert detection for signal changes, thesis flips, and upcoming earnings.

Runs after each scheduled analysis to detect actionable changes and save alerts.
"""

from typing import Optional

from src.config import EARNINGS_ALERT_DAYS, WATCH_ONLY, WATCHLIST
from src.data.models import AlertRecord, AlertSeverity, AlertType
from src.db.operations import (
    alert_exists_today,
    get_reports,
    get_upcoming_earnings,
    save_alert,
)
from src.utils.logger import get_logger

logger = get_logger("automation.alerts")

SYNTHESIZER_AGENT = "research_synthesizer"


def detect_signal_changes(db_path: Optional[str] = None) -> list[AlertRecord]:
    """Detect signal flips by comparing the two most recent synthesis reports per ticker."""
    kwargs = {"db_path": db_path} if db_path else {}
    alerts = []
    all_tickers = {**WATCHLIST, **WATCH_ONLY}

    for ticker in all_tickers:
        reports = get_reports(ticker, agent_name=SYNTHESIZER_AGENT, limit=2, **kwargs)
        if len(reports) < 2:
            continue

        current_signal = reports[0]["signal"]
        previous_signal = reports[1]["signal"]

        if current_signal == previous_signal:
            continue

        # Bearish involvement = critical
        involves_bearish = "bearish" in (current_signal, previous_signal)
        severity = AlertSeverity.CRITICAL if involves_bearish else AlertSeverity.WARNING

        title = f"{ticker} signal changed: {previous_signal} -> {current_signal}"
        detail = (
            f"{ticker} synthesis signal changed from {previous_signal} to {current_signal}. "
            f"Previous report: {reports[1]['date']}. Current report: {reports[0]['date']}."
        )

        alerts.append(AlertRecord(
            ticker=ticker,
            alert_type=AlertType.SIGNAL_CHANGE,
            severity=severity,
            title=title,
            detail=detail,
        ))

    return alerts


def detect_thesis_changes(db_path: Optional[str] = None) -> list[AlertRecord]:
    """Detect tickers where the latest synthesis report flagged a thesis change."""
    kwargs = {"db_path": db_path} if db_path else {}
    alerts = []
    all_tickers = {**WATCHLIST, **WATCH_ONLY}

    for ticker in all_tickers:
        reports = get_reports(ticker, agent_name=SYNTHESIZER_AGENT, limit=1, **kwargs)
        if not reports:
            continue

        report_data = reports[0]["report"]
        if not report_data.get("thesis_changed_since_last", False):
            continue

        title = f"{ticker} thesis change detected"
        detail = (
            f"The research synthesizer flagged a thesis change for {ticker} "
            f"in the {reports[0]['date']} report."
        )

        alerts.append(AlertRecord(
            ticker=ticker,
            alert_type=AlertType.THESIS_CHANGE,
            severity=AlertSeverity.WARNING,
            title=title,
            detail=detail,
        ))

    return alerts


def detect_earnings_alerts(db_path: Optional[str] = None) -> list[AlertRecord]:
    """Create alerts for earnings events within the configured alert window."""
    kwargs = {"db_path": db_path} if db_path else {}
    upcoming = get_upcoming_earnings(within_days=EARNINGS_ALERT_DAYS, **kwargs)
    alerts = []

    for event in upcoming:
        ticker = event["ticker"]
        earnings_date = event["earnings_date"]
        title = f"{ticker} earnings on {earnings_date}"
        detail = f"{ticker} has earnings scheduled for {earnings_date}."
        if event.get("estimate_eps") is not None:
            detail += f" EPS estimate: ${event['estimate_eps']:.2f}."

        alerts.append(AlertRecord(
            ticker=ticker,
            alert_type=AlertType.EARNINGS_APPROACHING,
            severity=AlertSeverity.INFO,
            title=title,
            detail=detail,
        ))

    return alerts


def detect_and_fire_alerts(db_path: Optional[str] = None) -> list[AlertRecord]:
    """Run all alert detectors, deduplicate, save, and return alerts."""
    kwargs = {"db_path": db_path} if db_path else {}

    all_alerts = []
    all_alerts.extend(detect_signal_changes(**kwargs))
    all_alerts.extend(detect_thesis_changes(**kwargs))
    all_alerts.extend(detect_earnings_alerts(**kwargs))

    saved = []
    for alert in all_alerts:
        # Skip if already alerted today (dedup)
        if alert_exists_today(alert.ticker, alert.alert_type.value, alert.title, **kwargs):
            logger.debug(f"Skipping duplicate alert: {alert.title}")
            continue

        save_alert(alert, **kwargs)
        saved.append(alert)

    logger.info(f"Alert detection complete: {len(saved)} new alerts ({len(all_alerts)} total detected)")
    return saved
