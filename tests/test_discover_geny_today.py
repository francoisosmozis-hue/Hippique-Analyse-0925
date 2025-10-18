import datetime as dt
import json
import os
import sys

import pytest



import discover_geny_today as dgt


class DummyResp:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            err = dgt.requests.HTTPError(f"{self.status_code} error")
            err.response = self
            raise err


def test_main_parses_geny_page(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    html = """
    <section class='reunion'>
        <h2>R1 Paris-Vincennes (FR)</h2>
        <a href='/course/123.html'>C1</a>
        <a href='/course/456.html'>C2</a>
    </section>
    """

    def fake_get(url: str, headers: dict[str, str], **kwargs) -> DummyResp:
        assert url == dgt.URL
        return DummyResp(html)

    monkeypatch.setattr(dgt.requests, "get", fake_get)

    dgt.main()
    out = capsys.readouterr().out
    data = json.loads(out)

    assert data["date"] == dt.datetime.today().strftime("%Y-%m-%d")
    assert data["meetings"][0]["r"] == "R1"
    assert data["meetings"][0]["courses"][0]["id_course"] == "123"
