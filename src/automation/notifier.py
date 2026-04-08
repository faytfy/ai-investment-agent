"""Notification dispatch for alerts: structured log file + optional SMTP email.

The log file is always written. Email is only sent when SMTP_ENABLED=true.
Email failure never crashes the caller.
"""

import logging
import smtplib
from datetime import date
from email.mime.text import MIMEText

from src.config import (
    ALERT_LOG_PATH,
    SMTP_ENABLED,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_TO,
    SMTP_USER,
)
from src.data.models import AlertRecord
from src.utils.logger import get_logger

logger = get_logger("automation.notifier")

# Dedicated file logger for alerts
_alert_logger: logging.Logger | None = None


def _get_alert_logger() -> logging.Logger:
    """Get or create the dedicated alert file logger."""
    global _alert_logger
    if _alert_logger is None:
        _alert_logger = logging.getLogger("investment.alerts")
        _alert_logger.setLevel(logging.INFO)
        _alert_logger.propagate = False
        if not _alert_logger.handlers:
            handler = logging.FileHandler(ALERT_LOG_PATH)
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
            _alert_logger.addHandler(handler)
    return _alert_logger


def _severity_to_log_level(severity: str) -> int:
    """Map alert severity to Python logging level."""
    return {
        "info": logging.INFO,
        "warning": logging.WARNING,
        "critical": logging.CRITICAL,
    }.get(severity, logging.INFO)


def _log_alerts(alerts: list[AlertRecord]) -> None:
    """Write alerts to the structured log file."""
    alert_log = _get_alert_logger()
    for alert in alerts:
        level = _severity_to_log_level(alert.severity.value)
        ticker_str = alert.ticker or "PORTFOLIO"
        alert_log.log(level, "%s | %s | %s", alert.alert_type.value, ticker_str, alert.title)


def _format_email_body(alerts: list[AlertRecord]) -> str:
    """Format alerts as a plain-text email body."""
    lines = [f"AI Investment Agent — {len(alerts)} Alert(s) — {date.today()}\n"]
    for alert in alerts:
        ticker_str = alert.ticker or "PORTFOLIO"
        lines.append(f"[{alert.severity.value.upper()}] {alert.alert_type.value}")
        lines.append(f"  Ticker: {ticker_str}")
        lines.append(f"  {alert.title}")
        lines.append(f"  {alert.detail}")
        lines.append("")
    return "\n".join(lines)


def _send_email(alerts: list[AlertRecord]) -> None:
    """Send a batch email with all alerts. Fails silently on error."""
    if not SMTP_HOST or not SMTP_TO:
        logger.warning("SMTP enabled but SMTP_HOST or SMTP_TO not configured, skipping email")
        return

    try:
        body = _format_email_body(alerts)
        msg = MIMEText(body)
        msg["Subject"] = f"[AI Investment Agent] {len(alerts)} alert(s) — {date.today()}"
        msg["From"] = SMTP_USER or "ai-investment-agent@localhost"
        msg["To"] = SMTP_TO

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(msg["From"], [SMTP_TO], msg.as_string())

        logger.info(f"Alert email sent to {SMTP_TO} ({len(alerts)} alerts)")
    except Exception as e:
        logger.error(f"Failed to send alert email: {e}")


def notify(alerts: list[AlertRecord]) -> None:
    """Dispatch alerts to all configured channels."""
    if not alerts:
        return

    _log_alerts(alerts)

    if SMTP_ENABLED:
        _send_email(alerts)
