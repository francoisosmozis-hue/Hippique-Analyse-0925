import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
