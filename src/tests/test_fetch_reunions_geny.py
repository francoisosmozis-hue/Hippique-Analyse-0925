import json
import sys
from pathlib import Path

import pytest

import fetch_reunions_geny as frg


class DummyResp:
    def __init__(self, text: str):
        self.text = text
        self.status_code = 200

    def raise_for_status(self) -> None:  # pragma: no cover - trivial
        return None


def test_fetch_reunions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    html = """
    <html><body>
      <section class="reunion">
        <h2><a href="https://www.geny.com/r1/chateaubriant">R1 - Châteaubriant</a></h2>
      </section>
    </body></html>
    """

    monkeypatch.setattr(
        frg.requests, "get", lambda url, headers=None, **kwargs: DummyResp(html)
    )


    out = tmp_path / "reuns.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["fetch_reunions_geny.py", "--date", "2024-09-25", "--out", str(out)],
    )

    frg.main()

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["date"] == "2024-09-25"
    assert data["reunions"] == [
        {
            "label": "R1",
            "hippodrome": "Châteaubriant",
            "url_geny": "https://www.geny.com/r1/chateaubriant",
            "url_zeturf": "https://www.zeturf.fr/fr/reunion/2024-09-25/R1-chateaubriant",
        }
    ]
