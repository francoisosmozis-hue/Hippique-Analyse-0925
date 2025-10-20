import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture(autouse=True, scope="session")
def _configure_rounding_step() -> None:
    """Ensure simulations use the finer 0.05 rounding step expected by tests."""

    original = os.environ.get("ROUND_TO_SP")
    os.environ.setdefault("ROUND_TO_SP", "0.05")
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("ROUND_TO_SP", None)
        else:
            os.environ["ROUND_TO_SP"] = original


from unittest import mock

@pytest.fixture(autouse=True)
def mock_google_auth():
    with mock.patch("google.auth.default", return_value=(None, None)) as m:
        yield m
