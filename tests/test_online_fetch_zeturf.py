#!/usr/bin/env python3

import os
import sys
import datetime as dt
from typing import Any
from pathlib import Path
import json

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import scripts.online_fetch_zeturf as ofz


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


@pytest.mark.parametrize(
    "url",
    [
        "https://www.zeturf.fr/rest/api/race/12345",
        "https://www.zeturf.fr/rest/api/race/12345?foo=bar",
        "https://www.zeturf.fr/rest/api/race/12345/details",
    ],
)
def test_fetch_runners_fallback(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """``fetch_runners`` should fallback to Geny on a 404."""
    
    seen: list[str] = []

    def fake_get(u: str, timeout: int = 10) -> DummyResp:
        seen.append(u)
        return DummyResp(404, None)

    monkeypatch.setattr(ofz.requests, "get", fake_get)

    called: dict[str, Any] = {}

    def fake_fetch(id_course: str) -> dict:
        called["id"] = id_course
        return {"id_course": id_course}

    monkeypatch.setattr(ofz, "fetch_from_geny_idcourse", fake_fetch)

    data = ofz.fetch_runners(url)

    assert seen == [url]
    assert called["id"] == "12345"
    assert data["id_course"] == "12345"


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
            {"id": "7", "odds": 12},
            {"id": "8", "odds": 14},
            {"id": "9", "odds": 10},
            {"id": "10", "odds": 5},
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
            {"id": "7", "odds": 8},
            {"id": "8", "odds": 11},
            {"id": "9", "odds": 14},
            {"id": "10", "odds": 10},
        ]
    }

    res = ofz.compute_diff(h30, h5)
    assert [r["id"] for r in res["top_steams"]] == ["4", "7", "8", "1", "3"]
    assert [r["id"] for r in res["top_drifts"]] == ["6", "10", "9", "5", "2"]
    assert len(res["top_steams"]) == 5
    assert len(res["top_drifts"]) == 5


def test_make_diff(tmp_path: Path) -> None:
    """``make_diff`` writes expected steam and drift lists."""

    h30 = {
        "runners": [
            {"id": "1", "odds": 10},
            {"id": "2", "odds": 5},
            {"id": "3", "odds": 7},
            {"id": "4", "odds": 9},
            {"id": "5", "odds": 6},
            {"id": "6", "odds": 11},
            {"id": "7", "odds": 12},
            {"id": "8", "odds": 14},
            {"id": "9", "odds": 10},
            {"id": "10", "odds": 5},
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
            {"id": "7", "odds": 8},
            {"id": "8", "odds": 11},
            {"id": "9", "odds": 14},
            {"id": "10", "odds": 10},
        ]
    }

    h30_fp = tmp_path / "h30.json"
    h30_fp.write_text(json.dumps(h30), encoding="utf-8")
    h5_fp = tmp_path / "h5.json"
    h5_fp.write_text(json.dumps(h5), encoding="utf-8")

    out_fp = ofz.make_diff("R1C1", h30_fp, h5_fp, outdir=tmp_path)
    with open(out_fp, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    assert out_fp.name == "R1C1_diff_drift.json"
    assert [r["id_cheval"] for r in data["steams"]] == ["4", "7", "8", "1", "3"]
    assert [r["id_cheval"] for r in data["drifts"]] == ["6", "10", "9", "5", "2"]




def sample_snapshot() -> dict:
    return {
        "rc": "R1C1",
        "hippodrome": "Test",
        "date": "2025-09-10",
        "discipline": "trot",
        "runners": [
            {"id": 1, "name": "A", "odds": "5"},
            {"id": 2, "name": "B", "odds": 7},
        ],
    }


@pytest.mark.parametrize("mode", ["h30", "h5"])
def test_main_snapshot_modes(mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI should normalise snapshots for h30/h5 modes."""

    def fake_get(url: str, timeout: int = 10) -> DummyResp:
        return DummyResp(200, sample_snapshot())

    monkeypatch.setattr(ofz.requests, "get", fake_get)
    sources = tmp_path / "src.yml"
    sources.write_text("zeturf:\n  url: 'http://x'\n", encoding="utf-8")
    out = tmp_path / f"{mode}.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["scripts/online_fetch_zeturf.py", "--mode", mode, "--out", str(out), "--sources", str(sources)],
    )
    ofz.main()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["rc"] == "R1C1"
    assert data["runners"][0]["odds"] == 5.0
    assert data["id2name"]["1"] == "A"


def test_main_diff_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``main`` should compute drifts when run with ``--mode diff``."""

    root = tmp_path
    h30_dir = root / "h30"
    h5_dir = root / "h5"
    diff_dir = root / "diff"
    h30_dir.mkdir()
    h5_dir.mkdir()
    diff_dir.mkdir()
    h30_dir.joinpath("h30.json").write_text(
        json.dumps({"runners": [{"id": "1", "odds": 10}, {"id": "2", "odds": 5}]}),
        encoding="utf-8",
    )
    h5_dir.joinpath("h5.json").write_text(
        json.dumps({"runners": [{"id": "1", "odds": 8}, {"id": "2", "odds": 7}]}),
        encoding="utf-8",
    )
    out = diff_dir / "diff_drift.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["scripts/online_fetch_zeturf.py", "--mode", "diff", "--out", str(out)],
    )
    ofz.main()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["steams"][0]["id_cheval"] == "1"
    assert data["drifts"][0]["id_cheval"] == "2"



def test_main_planning_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``main`` should fetch and filter today's meetings in planning mode."""

    today = dt.date.today().isoformat()

    def fake_get(url: str, timeout: int = 10) -> DummyResp:
        payload = {"meetings": [{"id": "R1", "name": "Meeting A", "date": today}]}
        return DummyResp(200, payload)

    monkeypatch.setattr(ofz.requests, "get", fake_get)
    sources = tmp_path / "src.yml"
    sources.write_text("zeturf:\n  url: 'http://x'\n", encoding="utf-8")
    out = tmp_path / "planning.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["scripts/online_fetch_zeturf.py", "--mode", "planning", "--out", str(out), "--sources", str(sources)],
    )
    ofz.main()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == [{"id": "R1", "name": "Meeting A", "date": today}]


def test_fetch_from_geny_idcourse(monkeypatch: pytest.MonkeyPatch) -> None:
    partants_html = """
    <div>R1C1</div>
    <table>
        <tr><td>1</td><td>A</td><td>J1</td><td>T1</td></tr>
        <tr><td>2</td><td>B</td><td>J2</td><td>T2</td></tr>
    </table>
    """
    odds_json = {"runners": [{"num": "1", "odds": 5}, {"num": "2", "odds": 7}]}

    def fake_get(url: str, headers: dict[str, str] | None = None, timeout: int = 10) -> DummyResp:
        if "partants" in url:
            return DummyResp(200, None, text=partants_html)
        if "cotes" in url:
            return DummyResp(200, odds_json)
        raise AssertionError("unexpected url")

    monkeypatch.setattr(ofz.requests, "get", fake_get)

    snap = ofz.fetch_from_geny_idcourse("123")
    assert snap["r_label"] == "R1"
    assert snap["partants"] == 2
    assert snap["runners"][0]["odds"] == 5
    assert snap["runners"][1]["odds"] == 7


def test_write_snapshot_from_geny(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = {
        "date": "2025-09-10",
        "source": "geny",
        "id_course": "123",
        "r_label": "R1",
        "runners": [],
        "partants": 0,
    }

    monkeypatch.setattr(ofz, "fetch_from_geny_idcourse", lambda _id: sample)

    class DummyDT(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> "DummyDT":
            return cls(2025, 9, 10, 8, 7, 6)

    monkeypatch.setattr(ofz.dt, "datetime", DummyDT)

    dest = ofz.write_snapshot_from_geny("123", "h30", tmp_path)
    data = json.loads(dest.read_text(encoding="utf-8"))

    assert dest.parent == tmp_path
    assert dest.name == "20250910T080706_R1C?_H-30.json"
    assert data["id_course"] == "123"
    assert data["source"] == "geny"
