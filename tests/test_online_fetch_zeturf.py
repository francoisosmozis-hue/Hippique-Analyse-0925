#!/usr/bin/env python3

import os
import sys
import datetime as dt
from typing import Any

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import scripts.online_fetch_zeturf as ofz
import online_fetch_zeturf as core


class DummyResp:
    """Minimal Response object for simulating HTTP errors."""

    def __init__(self, status_code: int, payload: Any, text: str | None = None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            err = ofz.requests.HTTPError(f"{self.status_code} error")
            err.response = self
            raise err

    def json(self) -> Any:  # pragma: no cover - trivial accessor
        return self._payload


def test_fetch_meetings_fallback_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 404 from the primary endpoint should trigger the Geny fallback."""
    primary = "https://www.zeturf.fr/rest/api/meetings/today"
    calls: list[str] = []
    today = dt.date.today().isoformat()
    geny_html = f"""
    <ul id='reunions'>
        <li data-id='R1' data-date='{today}'>Meeting A</li>
    </ul>
    """

    def fake_get(url: str, timeout: int) -> DummyResp:
        calls.append(url)
        if url == primary:
             return DummyResp(404, None)
        return DummyResp(200, geny_html)

    monkeypatch.setattr(ofz.requests, "get", fake_get)

    data = ofz.fetch_meetings(primary)

    assert calls == [primary, ofz.GENY_FALLBACK_URL]
    assert data == {"meetings": [{"id": "R1", "name": "Meeting A", "date": today}]}


def test_compute_diff_top_lists() -> None:
    """``compute_diff`` should expose top steams and drifts."""

    h30 = {
        "runners": [
            {"id": "1", "odds": 10},
            {"id": "2", "odds": 5},
            {"id": "3", "odds": 7},
            {"id": "4", "odds": 9},
            {"id": "5", "odds": 6},
            {"id": "6", "odds": 11},
        ]
    }
    h5 = {
        "runners": [
            {"id": "1", "odds": 8},
            {"id": "2", "odds": 7},
            {"id": "3", "odds": 6},
            {"id": "4", "odds": 4},
            {"id": "5", "odds": 9},
            {"id": "6", "odds": 17},
        ]
    }

    res = core.compute_diff(h30, h5)
    assert [r["id"] for r in res["top_steams"]] == ["4", "1", "3"]
    assert [r["id"] for r in res["top_drifts"]] == ["6", "5", "2"]
