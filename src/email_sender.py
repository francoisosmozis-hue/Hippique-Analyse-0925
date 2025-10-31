import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

def send_email(subject: str, html_content: str, to_address: str):
    """Sends an email with HTML content."""
    smtp_server = os.environ.get("SMTP_SERVER")
    smtp_port_str = os.environ.get("SMTP_PORT", "587")
    smtp_username = os.environ.get("SMTP_USERNAME")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    from_address = os.environ.get("EMAIL_FROM")

    if not all([smtp_server, smtp_port_str, smtp_username, smtp_password, from_address, to_address]):
        logger.warning("Email configuration is incomplete. Skipping email notification.")
        return False

    try:
        smtp_port = int(smtp_port_str)
    except ValueError:
        logger.error(f"Invalid SMTP_PORT: {smtp_port_str}. Must be an integer.")
        return False

    msg = MIMEMultipart()
    msg["From"] = from_address
    msg["To"] = to_address
    msg["Subject"] = subject

    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
            logger.info(f"Email sent successfully to {to_address}")
            return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}", exc_info=True)
        return False
