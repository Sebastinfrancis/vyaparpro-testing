"""
Minimal SMTP email sending. Uses the SMTP_* / EMAILS_FROM_* settings from
.env. If SMTP_USER is blank (not configured on this install), the message
is logged instead of sent, so the app never crashes a background task —
it just fails to actually deliver until the customer configures SMTP.
"""
from __future__ import annotations
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def _send(to_email: str, subject: str, body: str) -> None:
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning(
            "SMTP is not configured (SMTP_USER/SMTP_PASSWORD blank in .env) — "
            "skipping email send to %s: %s", to_email, subject,
        )
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            if settings.SMTP_TLS:
                server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        logger.info("Email sent to %s: %s", to_email, subject)
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "SMTP auth failed sending to %s — check SMTP_USER/SMTP_PASSWORD "
            "in .env (Gmail requires an App Password, not your login password).",
            to_email,
        )
    except Exception:
        logger.exception("Failed to send email to %s", to_email)


def send_reset_email(to_email: str, token: str) -> None:
    subject = "Reset your VyaparPro password"
    body = (
        "You requested a password reset for your VyaparPro account.\n\n"
        f"Your reset code is:\n\n{token}\n\n"
        "Open VyaparPro, go to Sign In → Forgot password, and paste this code "
        "along with your new password. This code expires shortly for your security.\n\n"
        "If you didn't request this, you can safely ignore this email."
    )
    _send(to_email, subject, body)