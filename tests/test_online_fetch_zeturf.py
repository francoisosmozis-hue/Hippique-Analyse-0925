#!/usr/bin/env python3

import os
import sys
import builtins
import datetime as dt
from typing import Any
from pathlib import Path
import json
import importlib.util

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


def test_import_guard_when_requests_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing the module without ``requests`` should raise a helpful error."""

    module_path = Path(__file__).resolve().parents[1] / "scripts" / "online_fetch_zeturf.py"
    spec = importlib.util.spec_from_file_location(
        "_scripts_online_fetch_zeturf_import_guard", module_path
    )
    assert spec is not None and spec.loader is not None

    monkeypatch.delitem(sys.modules, "requests", raising=False)

    original_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any):
        if name == "requests":
            raise ModuleNotFoundError("No module named 'requests'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    module = importlib.util.module_from_spec(spec)

    with pytest.raises(RuntimeError) as excinfo:
        spec.loader.exec_module(module)

    sys.modules.pop(spec.name, None)

    message = str(excinfo.value)
    assert "pip install requests" in message
    assert "urllib" in message


def test_resolve_source_url_new_structure() -> None:
    """The resolver should pick Geny/PMU entries from the new layout."""

    cfg = {
        "online": {
            "geny": {"planning": {"url": "https://geny/planning"}},
            "pmu": {
                "h30": {"url": "https://pmu/h30"},
                "h5": {"endpoint": "https://pmu/h5"},
            },
        }
    }

    assert ofz.resolve_source_url(cfg, "planning") == "https://geny/planning"
    assert ofz.resolve_source_url(cfg, "h30") == "https://pmu/h30"
    assert ofz.resolve_source_url(cfg, "h5") == "https://pmu/h5"


def test_resolve_source_url_legacy_shape() -> None:
    """Legacy ``zeturf.url`` entries should remain supported."""

    cfg = {"zeturf": {"url": "https://legacy"}}

    assert ofz.resolve_source_url(cfg, "planning") == "https://legacy"
    assert ofz.resolve_source_url(cfg, "h5") == "https://legacy"


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


def test_fetch_meetings_fallback_on_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Network failures should trigger the Geny fallback."""

    primary = "https://www.zeturf.fr/rest/api/meetings/today"
    fallback_payload = {"meetings": [{"id": "GENY", "name": "Fallback", "date": "today"}]}
    called: dict[str, int] = {"fallback": 0}

    def fake_get(url: str, timeout: int = 10) -> DummyResp:
        if url == primary:
            raise ofz.requests.ConnectionError("boom")
        raise AssertionError("Unexpected URL")

    def fake_fallback() -> dict:
        called["fallback"] += 1
        return fallback_payload

    monkeypatch.setattr(ofz.requests, "get", fake_get)
    monkeypatch.setattr(ofz, "_fetch_from_geny", fake_fallback)

    data = ofz.fetch_meetings(primary)

    assert called["fallback"] == 1
    assert data is fallback_payload


def test_fetch_runners_placeholder_url() -> None:
    """The fetcher should fail fast when the course_id placeholder is still present."""

    with pytest.raises(ValueError, match="course_id"):
        ofz.fetch_runners("https://m.zeeturf.fr/rest/api/2/race/{course_id}")


@pytest.mark.parametrize(
    "url",
    [
        "https://www.zeturf.fr/rest/api/race/12345",
        "https://www.zeturf.fr/rest/api/race/12345?foo=bar",
        "https://www.zeturf.fr/rest/api/race/12345/details",
    ],
)
def test_fetch_runners_fallback_on_404(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
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


def test_fetch_runners_enriches_start_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Successful API fetches should scrape the course page for start time."""

    api_url = "https://www.zeturf.fr/rest/api/race/12345"
    html = "<time datetime='2024-09-25T13:05:00+02:00'>13h05</time>"
    calls: list[str] = []

    def fake_get(url: str, timeout: int = 10, headers: Any | None = None) -> DummyResp:
        calls.append(url)
        if url == api_url:
            return DummyResp(200, {"meta": {}})
        if url == "https://www.zeturf.fr/fr/course/12345":
            return DummyResp(200, {}, text=html)
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(ofz.requests, "get", fake_get)

    data = ofz.fetch_runners(api_url)

    assert data["meta"]["start_time"] == "13:05"
    assert data["start_time"] == "13:05"
    assert data["course_id"] == "12345"
    assert calls == [api_url, "https://www.zeturf.fr/fr/course/12345"]


def test_extract_course_ids_from_meeting() -> None:
    """Meeting pages should yield ordered course identifiers."""

    html = """
    <div data-course-id="12345"></div>
    <a href="/fr/course/67890-course-name">Course 2</a>
    <script>window.__NUXT__ = {"courseId": "99999"}</script>
    """

    assert ofz._extract_course_ids_from_meeting(html) == ["12345", "67890", "99999"]


def test_extract_start_time_variants() -> None:
    """The helper should normalise hours from HTML fragments."""

    html = """
    <div class='infos-course'>
        <time datetime="2024-09-25T13:45:00+02:00">13h45</time>
    </div>
    """

    assert ofz._extract_start_time(html) == "13:45"

    html_alt = "<span class='depart'>Départ 9h05</span>"
    assert ofz._extract_start_time(html_alt) == "09:05"

    html_meta = """
    <meta property="event:start_time" content="2025-10-09T09:15:00+01:00" />
    <div>Autre contenu</div>
    """
    assert ofz._extract_start_time(html_meta) == "09:15"

    html_single_digit = "<div>Départ prévu 7h5</div>"
    assert ofz._extract_start_time(html_single_digit) == "07:05"

    html_hour_only = "<p>Off 15h</p>"
    assert ofz._extract_start_time(html_hour_only) == "15:00"

    html_words = "<div>Départ prévu à 18 heures 30</div>"
    assert ofz._extract_start_time(html_words) == "18:30"


def test_fetch_from_geny_adds_start_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Geny fallback snapshots should expose the parsed start time."""

    html = """
    <div id='horaire'>Départ prévu à <strong>16h20</strong></div>
    <table><tr><td>1</td><td>Nom</td><td>J</td><td>E</td></tr></table>
    """

    def fake_get(url: str, headers: Any = None, timeout: int = 10) -> DummyResp:
        if "partants" in url:
            return DummyResp(200, "", text=html)
        return DummyResp(200, {"runners": []})

    monkeypatch.setattr(ofz.requests, "get", fake_get)

    snap = ofz.fetch_from_geny_idcourse("99999")

    assert snap["start_time"] == "16:20"


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


def test_normalize_snapshot_with_program_numbers() -> None:
    """``normalize_snapshot`` should fallback to program numbers and deduplicate."""

    payload = {
        "rc": "R1C1",
        "hippodrome": "Test",
        "date": "2025-09-10",
        "discipline": "trot",
        "runners": [
            {"num": 1, "name": "Alpha", "odds": "5"},
            {"number": "2", "name": "Bravo", "odds": 7},
            {"num": "1", "name": "Ghost", "odds": 10},
        ],
    }

    normalized = ofz.normalize_snapshot(payload)

    ids = [runner["id"] for runner in normalized["runners"]]
    assert ids == ["1", "2"]
    assert normalized["id2name"] == {"1": "Alpha", "2": "Bravo"}
    assert len(ids) == len(set(ids)) == len(normalized["id2name"])
    assert normalized["odds"] == {"1": 5.0, "2": 7.0}
    assert set(normalized["p_imp"]) == {"1", "2"}
    expected = (1 / 5.0) / ((1 / 5.0) + (1 / 7.0))
    assert normalized["runners"][0]["p_imp"] == pytest.approx(expected)
    assert sum(normalized["p_imp"].values()) == pytest.approx(1.0)


def test_normalize_snapshot_derives_labels() -> None:
    """The normaliser should expose reunion/course labels when rc is present."""

    payload = sample_snapshot()
    payload["rc"] = "R4C7"
    payload["course_id"] = 555666

    normalized = ofz.normalize_snapshot(payload)

    assert normalized["reunion"] == "R4"
    assert normalized["course"] == "C7"
    assert normalized["course_id"] == "555666"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2025-09-10T15:42:00", "15:42"),
        ("13h05", "13:05"),
        ("7h", "07:00"),
    ],
)
def test_normalize_snapshot_includes_start_time(raw: str, expected: str) -> None:
    """Start times available in the payload should be normalised to HH:MM."""

    payload = sample_snapshot()
    payload["start_time"] = raw

    normalized = ofz.normalize_snapshot(payload)

    assert normalized["start_time"] == expected




@pytest.mark.parametrize("mode", ["h30", "h5"])
def test_main_snapshot_modes(mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI should normalise snapshots for h30/h5 modes."""

    def fake_get(url: str, timeout: int = 10) -> DummyResp:
        return DummyResp(200, sample_snapshot())

    monkeypatch.setattr(ofz.requests, "get", fake_get)
    sources = tmp_path / "src.yml"
    sources.write_text(
        "pmu:\n  h30:\n    url: 'http://x'\n  h5:\n    url: 'http://x'\n",
        encoding="utf-8",
    )
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
    assert data["runners"][0]["p_imp"] > 0
    assert sum(data["p_imp"].values()) == pytest.approx(1.0)


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



def test_reunion_snapshot_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI should fetch all course snapshots for a meeting URL."""

    meeting_url = "https://www.zeturf.fr/fr/reunion/2024-09-25/R1-paris"
    meeting_html = """
    <div data-course-id="11111"></div>
    <a href="/course/22222-prix-test">Course 2</a>
    """

    config_path = tmp_path / "sources.yml"
    config_path.write_text(
        "zeturf:\n  url: 'https://api.example/race/{course_id}'\n",
        encoding="utf-8",
    )

    def fake_get(url: str, headers: Any | None = None, timeout: int = 10) -> DummyResp:
        if url == meeting_url:
            return DummyResp(200, {}, text=meeting_html)
        if "11111" in url:
            payload = {
                "rc": "R1C1",
                "hippodrome": "Paris-Vincennes",
                "date": "2024-09-25",
                "discipline": "trot",
                "runners": [{"id": 1, "name": "Alpha", "odds": 3.5}],
            }
            return DummyResp(200, payload, text="<html></html>")
        if "22222" in url:
            payload = {
                "rc": "R1C2",
                "hippodrome": "Paris-Vincennes",
                "date": "2024-09-25",
                "discipline": "trot",
                "runners": [{"id": 2, "name": "Beta", "odds": 4.0}],
            }
            return DummyResp(200, payload, text="<html></html>")
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(ofz.requests, "get", fake_get)

    out_dir = tmp_path / "meeting"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scripts/online_fetch_zeturf.py",
            "--reunion-url",
            meeting_url,
            "--snapshot",
            "H-30",
            "--out",
            str(out_dir),
            "--sources",
            str(config_path),
        ],
    )

    ofz.main()

    snap1 = out_dir / "R1C1" / "snapshot_H-30.json"
    snap2 = out_dir / "R1C2" / "snapshot_H-30.json"
    assert snap1.exists()
    assert snap2.exists()

    data1 = json.loads(snap1.read_text(encoding="utf-8"))
    data2 = json.loads(snap2.read_text(encoding="utf-8"))
    assert data1["course_id"] == "11111"
    assert data2["course_id"] == "22222"
    assert data1["reunion"] == "R1"
    assert data2["course"] == "C2"


def test_main_planning_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``main`` should fetch and filter today's meetings in planning mode."""

    today = dt.date.today().isoformat()

    def fake_get(url: str, timeout: int = 10) -> DummyResp:
        payload = {"meetings": [{"id": "R1", "name": "Meeting A", "date": today}]}
        return DummyResp(200, payload)

    monkeypatch.setattr(ofz.requests, "get", fake_get)
    sources = tmp_path / "src.yml"
    sources.write_text(
        "geny:\n  planning:\n    url: 'http://x'\n",
        encoding="utf-8",
    )
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
