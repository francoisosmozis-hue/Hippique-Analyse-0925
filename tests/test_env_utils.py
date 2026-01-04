import logging
from unittest.mock import patch

import pytest

from config.env_utils import get_env


def test_get_env_missing_warns(caplog):
    """Test that a warning is logged when a non-required variable is missing."""
    with caplog.at_level(logging.WARNING):
        val = get_env("MISSING_VAR", default="fallback")
    assert val == "fallback"
    assert "MISSING_VAR not set; using default 'fallback'" in caplog.text


def test_get_env_required_missing_logs_critical(caplog):
    """Test that a critical error is logged for a required missing variable."""
    with caplog.at_level(logging.CRITICAL):
        get_env("REQUIRED_MISSING", required=True)
    assert "Missing required environment variable 'REQUIRED_MISSING'" in caplog.text


def test_get_env_required_missing_in_prod_exits(monkeypatch):
    """Test that get_env exits with code 1 if a required variable is missing in production."""
    monkeypatch.setenv("PROD", "true")
    monkeypatch.delenv("MY_VAR", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        get_env("MY_VAR", required=True)

    assert excinfo.value.code == 1


@pytest.mark.parametrize("prod_value", ["true", "True", "1", "t", "yes", "y"])
def test_get_env_required_missing_in_prod_exits_variations(monkeypatch, caplog, prod_value):
    """Test that get_env exits for various 'true' values of PROD."""
    monkeypatch.setenv("PROD", prod_value)
    monkeypatch.delenv("MY_VAR", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        get_env("MY_VAR", required=True)

    assert excinfo.value.code == 1
    assert "Missing required environment variable 'MY_VAR'" in caplog.text
    assert "IS_PROD=True. Exiting." in caplog.text


def test_get_env_alias_support(monkeypatch):
    """Test that aliases are correctly used as fallbacks."""
    monkeypatch.setenv("ALIAS_VAR", "alias_value")
    val = get_env("PRIMARY_VAR", aliases=["ALIAS_VAR"])
    assert val == "alias_value"


def test_get_env_casting_error_returns_default(monkeypatch, caplog):
    """Test that a casting error on a variable returns the default."""
    monkeypatch.setenv("INT_VAR", "not-an-int")
    with caplog.at_level(logging.ERROR):
        val = get_env("INT_VAR", cast=int, default=0)
    assert val == 0
    assert "Invalid value for environment variable 'INT_VAR'" in caplog.text


def test_get_env_value_equals_default_no_override_log(monkeypatch, caplog):
    """
    Test that no override message is logged if the env var value is the
    same as the default.
    """
    monkeypatch.setenv("MY_VAR", "default_value")
    with caplog.at_level(logging.INFO):
        val = get_env("MY_VAR", default="default_value")
    assert val == "default_value"
    assert "overrides default" not in caplog.text


def test_get_env_required_missing_non_prod_logs_critical_no_exit(monkeypatch, caplog):
    """
    Test that get_env logs a critical error but does not exit if a required
    variable is missing in a non-production environment.
    """
    monkeypatch.setenv("PROD", "false")  # Explicitly set PROD to false
    monkeypatch.delenv("NON_PROD_REQUIRED", raising=False)  # Ensure the variable is not set

    with caplog.at_level(logging.CRITICAL):
        val = get_env("NON_PROD_REQUIRED", required=True)
    
    assert "Missing required environment variable 'NON_PROD_REQUIRED'" in caplog.text
    assert val is None
    assert "IS_PROD=True. Exiting." not in caplog.text