"""Failure alerting — Slack webhook + SMTP email. Sync (called from scheduler thread)."""
import smtplib
import logging
from email.message import EmailMessage

import httpx

from app.core.config import settings

log = logging.getLogger("sfs.alerts")


def send_slack(text: str) -> bool:
    if not settings.SLACK_WEBHOOK_URL:
        return False
    try:
        httpx.post(settings.SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
        return True
    except Exception as e:
        log.error(f"Slack alert failed: {e}")
        return False


def send_email(to: str, subject: str, body: str) -> bool:
    if not (settings.SMTP_HOST and to):
        return False
    try:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = settings.SMTP_FROM, to, subject
        msg.set_content(body)
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as s:
            s.starttls()
            if settings.SMTP_USER:
                s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as e:
        log.error(f"Email alert failed: {e}")
        return False


def alert_failure(flow_name: str, project_id: str, attempt: int, max_attempts: int, error: str, email_to: str = ""):
    text = (f"🔴 SFS flow *{flow_name}* failed (attempt {attempt}/{max_attempts})\n"
            f"project: {project_id}\n```{(error or '')[-600:]}```")
    send_slack(text)
    if email_to:
        send_email(email_to, f"[SFS] Flow failed: {flow_name}",
                   f"Flow {flow_name} failed (attempt {attempt}/{max_attempts}).\n\n{error}")
