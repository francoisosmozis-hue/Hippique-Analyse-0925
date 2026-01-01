import logging
import os # Needed for testing os.getenv
import pytest
from unittest.mock import MagicMock, patch # For mocking cast
from config.env_utils import get_env


def test_get_env_missing_warns(monkeypatch, caplog):
    monkeypatch.delenv("FOO", raising=False)
    with caplog.at_level(logging.WARNING):
        val = get_env("FOO", "bar")
    assert val == "bar"
    assert "FOO" in caplog.text


def test_get_env_required_missing_logs_critical(monkeypatch, caplog):
    monkeypatch.delenv("BAR", raising=False)
    with caplog.at_level(logging.CRITICAL):
        # is_prod=False is the default, so this tests the non-blocking behavior
        val = get_env("BAR", required=True, is_prod=False)
    
    assert val is None # It should return the default, which is None
    assert "Missing required environment variable 'BAR'" in caplog.text


def test_get_env_required_missing_in_prod_exits(monkeypatch, caplog):
    monkeypatch.delenv("PROD_VAR", raising=False)
    
    # Mock sys.exit to prevent the test runner from exiting
    with patch("sys.exit") as mock_exit:
        with caplog.at_level(logging.CRITICAL):
            get_env("PROD_VAR", required=True, is_prod=True)

    # Assert that sys.exit was called with the correct exit code
    mock_exit.assert_called_once_with(1)
    assert "Missing required environment variable 'PROD_VAR'" in caplog.text
    assert "IS_PROD=True. Exiting." in caplog.text


def test_get_env_alias_support(monkeypatch, caplog):
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.setenv("FOO_ALIAS", "42")

    with caplog.at_level(logging.INFO):
        val = get_env("FOO", 0, cast=int, aliases=("FOO_ALIAS",))

    assert val == 42
    assert "FOO_ALIAS" in caplog.text

def test_get_env_casting_error_returns_default(monkeypatch, caplog):
    """Tests that a casting error logs an error and returns the default value."""
    monkeypatch.setenv("BAD_INT", "not_an_integer")
    with caplog.at_level(logging.ERROR):
        val = get_env("BAD_INT", 123, cast=int)
    assert val == 123
    assert "Invalid value for environment variable 'BAD_INT'" in caplog.text

def test_get_env_value_equals_default_no_override_log(monkeypatch, caplog):
    """Tests that when a fetched value equals the default, no override log occurs."""
    monkeypatch.setenv("MATCHING_VAR", "same_value")
    with caplog.at_level(logging.INFO):
        val = get_env("MATCHING_VAR", "same_value")
    assert val == "same_value"
    # Assert that the "overrides default" log message is NOT present
    assert "overrides default" not in caplog.text
