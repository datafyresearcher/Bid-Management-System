"""Outbound email over SMTP.

The dashboard inbox is only seen by someone who opens it. The daily digest
and the screening alerts are the parts of the system that reach a person who
has not opened the dashboard today, so they go out by email when the
deployment has been given an SMTP account — and stay in the dashboard inbox
when it has not. Nothing here ever blocks the pipeline on a mail server: a
failure to send is logged and reported, never raised.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger("bms.email")


def configured() -> bool:
    """Whether an SMTP account has been given to this deployment."""
    return bool(settings.smtp_host and settings.smtp_from)


def send_email(to_addresses: list[str], subject: str, body: str) -> bool:
    """Send one plain-text email. Returns whether it was sent.

    Recipients are deduplicated and filtered, so a role group that resolves
    to the same person twice still produces one copy.
    """
    recipients = sorted({addr.strip() for addr in to_addresses if addr and "@" in addr})
    if not configured() or not recipients:
        return False
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    try:
        if settings.smtp_use_tls:
            # STARTTLS on the submission port. Port 465 deployments set
            # smtp_use_tls=false and get implicit SSL below.
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(message)
        logger.info("Email sent to %s: %s", ", ".join(recipients), subject)
        return True
    except Exception:
        # A mail server that is down must not take a scan or a digest with it.
        logger.exception("Email send failed (%s)", subject)
        return False
