
import smtplib

import pytest

from src import email_sender


@pytest.fixture
def mock_env(mocker):
    """Provides a clean environment with required email variables."""
    env_vars = {
        "SMTP_SERVER": "smtp.test.com",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "user",
        "SMTP_PASSWORD": "password",
        "EMAIL_FROM": "from@test.com",
    }
    mocker.patch.dict(email_sender.os.environ, env_vars)

def test_send_email_incomplete_config(mocker):
    """Tests that email sending is skipped if config is incomplete."""
    mocker.patch.dict(email_sender.os.environ, {}, clear=True)
    logger_mock = mocker.patch("src.email_sender.logger")

    result = email_sender.send_email("subject", "content", "to@test.com")

    assert result is False
    logger_mock.warning.assert_called_with("Email configuration is incomplete. Skipping email notification.")

def test_send_email_success(mock_env, mocker):
    """Tests a successful email sending flow."""
    mock_smtp = mocker.patch("smtplib.SMTP")

    result = email_sender.send_email("Test Subject", "<h1>Hello</h1>", "to@test.com")

    assert result is True
    mock_smtp.assert_called_with("smtp.test.com", 587)

    server_instance = mock_smtp.return_value.__enter__.return_value
    server_instance.starttls.assert_called_once()
    server_instance.login.assert_called_once_with("user", "password")
    server_instance.send_message.assert_called_once()

    sent_msg = server_instance.send_message.call_args[0][0]
    assert sent_msg["Subject"] == "Test Subject"
    assert sent_msg["From"] == "from@test.com"
    assert sent_msg["To"] == "to@test.com"

def test_send_email_smtp_failure(mock_env, mocker):
    """Tests the behavior when the SMTP server fails."""
    mock_smtp_class = mocker.patch("smtplib.SMTP")
    mock_server = mock_smtp_class.return_value.__enter__.return_value
    mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")
    logger_mock = mocker.patch("src.email_sender.logger")

    result = email_sender.send_email("subject", "content", "to@test.com")

    assert result is False
    logger_mock.error.assert_called_once()
    call_args, call_kwargs = logger_mock.error.call_args
    assert "Failed to send email" in call_args[0]

def test_send_email_invalid_port(mocker):
    """Tests that an invalid port number is handled correctly."""
    env_vars = {
        "SMTP_SERVER": "smtp.test.com",
        "SMTP_PORT": "not-a-number", # Invalid port
        "SMTP_USERNAME": "user",
        "SMTP_PASSWORD": "password",
        "EMAIL_FROM": "from@test.com",
    }
    mocker.patch.dict(email_sender.os.environ, env_vars)
    logger_mock = mocker.patch("src.email_sender.logger")

    result = email_sender.send_email("subject", "content", "to@test.com")

    assert result is False
    logger_mock.error.assert_called_with("Invalid SMTP_PORT: not-a-number. Must be an integer.")
