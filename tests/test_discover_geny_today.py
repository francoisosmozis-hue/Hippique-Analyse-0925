import datetime as dt
import json
import os
import subprocess
import sys
import types

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import discover_geny_today as dgt


def test_main_parses_geny_page(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    html = """
    <ul>
        <li class="prog-meeting-name">
            <a class="meeting-name-link">R1 - Paris-Vincennes</a>
            <span class="nomReunion">Paris-Vincennes</span>
            <span class="flag flag-fr"></span>
        </li>
    </ul>
    <div class="timeline-container">
        <ul>
            <li class="meeting">
                <ul>
                    <li class="race" data-id="123">
                        <a href="/fr/programme-courses/R1/C1">C1</a>
                    </li>
                    <li class="race" data-id="456">
                        <a href="/fr/programme-courses/R1/C2">C2</a>
                    </li>
                </ul>
            </li>
        </ul>
    </div>
    """

    def fake_run(*args, **kwargs):
        return types.SimpleNamespace(stdout=html, stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    dgt.main()
    out = capsys.readouterr().out
    data = json.loads(out)

    assert data["date"] == dt.datetime.today().strftime("%Y-%m-%d")
    assert data["meetings"][0]["r"] == "R1"
    assert data["meetings"][0]["courses"][0]["id_course"] == "123"
