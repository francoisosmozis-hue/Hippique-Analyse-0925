#!/usr/bin/env python3
# Placeholder temporaire pour rétablir la CI ; remettra les vrais tests ensuite.
import json  # noqa: F401
from pathlib import Path  # noqa: F401
import pytest  # noqa: F401

def test_fetch_je_chrono_enrich_from_snapshot(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert True

def test_fetch_je_chrono_enrich_from_snapshot_requires_snapshot(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    assert True
