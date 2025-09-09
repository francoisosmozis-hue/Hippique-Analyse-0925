#!/usr/bin/env python3

import os
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import scripts.online_fetch_zeturf as ofz


class DummyResp:
    """Minimal Response object for simulating HTTP errors."""

    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self._payload = payload

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
             return DummyResp(404)
        return DummyResp(200, text=geny_html)

    monkeypatch.setattr(ofz.requests, "get", fake_get)

    data = ofz.fetch_meetings(primary)

    aassert calls == [primary, ofz.GENY_FALLBACK_URL]
    assert data == {"meetings": [{"id": "R1", "name": "Meeting A", "date": today}]}
