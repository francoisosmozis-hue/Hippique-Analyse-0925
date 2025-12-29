import logging

import pytest

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
        val = get_env("BAR", required=True)
    
    assert val is None # It should return the default, which is None
    assert "Missing required environment variable 'BAR'" in caplog.text


def test_get_env_alias_support(monkeypatch, caplog):
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.setenv("FOO_ALIAS", "42")

    with caplog.at_level(logging.INFO):
        val = get_env("FOO", 0, cast=int, aliases=("FOO_ALIAS",))

    assert val == 42
    assert "FOO_ALIAS" in caplog.text
