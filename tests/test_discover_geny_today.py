import datetime as dt
import json
import os
import subprocess
import sys
import types

import httpx
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import discover_geny_today as dgt


def test_main_parses_geny_page(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    html = """
    <div id="next-races-container">
        <table>
            <tbody>
                <tr id="race_1617728">
                    <th class="race-name">Paris-Vincennes</th>
                    <td></td>
                    <td></td>
                    <td><a href="/fr/programme-courses/R1/C1">C1</a></td>
                </tr>
            </tbody>
        </table>
    </div>
    """

    def fake_get(*args, **kwargs):
        return types.SimpleNamespace(text=html, status_code=200, raise_for_status=lambda: None)

    monkeypatch.setattr(httpx, "get", fake_get)

    dgt.main()
    out = capsys.readouterr().out
    data = json.loads(out)

    assert data["date"] == dt.datetime.today().strftime("%Y-%m-%d")
    assert data["meetings"][0]["r"] == "R1"
    assert data["meetings"][0]["courses"][0]["id_course"] == "1617728"
