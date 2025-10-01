#!/usr/bin/env python3

import os
import sys
import builtins
import datetime as dt
from typing import Any, Mapping
from pathlib import Path
import json
import importlib.util
import logging
import shutil

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import scripts.online_fetch_zeturf as ofz
import online_fetch_zeturf as cli


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


def test_race_snapshot_as_dict_includes_aliases() -> None:
    """The lightweight dataclass should expose aliases expected downstream."""

    snapshot = cli.RaceSnapshot(
        meeting="Paris-Vincennes",
        date="2024-09-15",
        reunion="R1",
        course="C3",
        discipline="trot",
        runners=[{"num": "1", "name": "Alpha"}],
        partants_count=14,
        phase="H30",
        rc="R1C3",
        r_label="R1",
        c_label="C3",
        source_url="https://www.zeturf.fr/fr/course/2024-09-15/R1C3-paris",
        course_id="987654",
        heure_officielle="13:45",
    )

    payload = snapshot.as_dict()

    assert payload["meeting"] == "Paris-Vincennes"
    assert payload["hippodrome"] == "Paris-Vincennes"
    assert payload["r_label"] == "R1"
    assert payload["c_label"] == "C3"
    assert payload["phase"] == "H30"
    assert payload["rc"] == "R1C3"
    assert payload["source_url"].endswith("R1C3-paris")
    assert payload["course_id"] == "987654"
    assert payload["partants"] is payload["runners"]
    assert payload["partants_count"] == 14
    assert payload["heure_officielle"] == "13:45"


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

    def fake_get(url: str, timeout: int, headers: Any | None = None) -> DummyResp:
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

    def fake_get(url: str, timeout: int = 10, headers: Any | None = None) -> DummyResp:
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


def test_fetch_race_snapshot_uses_entry_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit entry URL should be used directly without template injection."""

    entry_url = "https://www.zeturf.fr/rest/api/race/55555"
    called: dict[str, Any] = {}

    def fake_fetch(url: str) -> dict[str, Any]:
        called.setdefault("fetch_urls", []).append(url)
        return {"rc": "R1C1", "runners": []}

    def fake_retry(
        operation: Any,
        *,
        retries: int,
        initial_delay: float,
        backoff: float,
        retry_exceptions: Any,
    ) -> dict[str, Any]:
        called["operation"] = operation
        return operation()

    monkeypatch.setattr(ofz, "fetch_runners", fake_fetch)
    monkeypatch.setattr(ofz, "_retry_with_backoff", fake_retry)

    config = {
        "entries": {
            "R1C1": {
                "rc": "R1C1",
                "url": entry_url,
                "course_id": "55555",
            }
        },
        "online": {"zeturf": {"h30": {"url": "https://template/{course_id}"}}},
    }

    snapshot = ofz.fetch_race_snapshot("R1C1", phase="H-30", sources=config)

    assert called["fetch_urls"] == [entry_url]
    assert callable(called["operation"])
    assert snapshot["rc"] == "R1C1"


def test_fetch_race_snapshot_accepts_direct_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Providing a direct URL should skip template resolution entirely."""

    direct_url = "https://www.zeturf.fr/rest/api/race/12345"
    called: dict[str, Any] = {}

    def fake_fetch(url: str) -> dict[str, Any]:
        called.setdefault("fetch_urls", []).append(url)
        return {"rc": "R1C1", "runners": []}

    def fake_retry(
        operation: Any,
        *,
        retries: int,
        initial_delay: float,
        backoff: float,
        retry_exceptions: Any,
    ) -> dict[str, Any]:
        called["operation"] = operation
        return operation()

    def forbidden_resolver(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("resolve_source_url should not be called when a direct URL is provided")

    monkeypatch.setattr(ofz, "fetch_runners", fake_fetch)
    monkeypatch.setattr(ofz, "_retry_with_backoff", fake_retry)
    monkeypatch.setattr(ofz, "resolve_source_url", forbidden_resolver)

    config = {"rc_map": {"R1C1": {"course_id": "12345"}}}

    snapshot = ofz.fetch_race_snapshot(
        "R1C1",
        phase="H-30",
        sources=config,
        url=direct_url,
    )

    assert called["fetch_urls"] == [direct_url]
    assert callable(called["operation"])
    assert snapshot["rc"] == "R1C1"
    assert snapshot["course_id"] == "12345"


def test_fetch_race_snapshot_merges_h30_odds_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshots should merge odds from local maps produced by the analyser."""

    rc_dir = Path("data") / "R7C8"
    try:
        rc_dir.mkdir(parents=True, exist_ok=True)
        (rc_dir / "h30.json").write_text(json.dumps({"1": 4.2, "2": 9.0}), encoding="utf-8")
        (rc_dir / "normalized_h30.json").write_text(
            json.dumps(
                {
                    "runners": [
                        {"num": "1", "odds_place_h30": 1.85},
                        {"num": "2"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        def fake_fetch(
            reunion: str | None,
            course: str | None,
            *,
            phase: str,
            **_kwargs: Any,
        ) -> Mapping[str, Any]:
            assert phase == "H5"
            return {
                "runners": [
                    {"num": "1", "name": "Alpha"},
                    {"num": "2", "name": "Bravo"},
                ]
            }

        monkeypatch.setattr(cli._impl, "fetch_race_snapshot", fake_fetch)

        snapshot = cli.fetch_race_snapshot("R7", "C8", phase="H5", sources={})

        assert snapshot["runners"][0]["odds_win_h30"] == 4.2
        assert snapshot["runners"][0]["odds_place_h30"] == 1.85
        assert snapshot["runners"][1]["odds_win_h30"] == 9.0
        assert "odds_place_h30" not in snapshot["runners"][1]
    finally:
        shutil.rmtree(rc_dir, ignore_errors=True)


def test_fetch_race_snapshot_returns_minimal_snapshot_on_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Total failures should yield a minimal snapshot without raising."""

    attempts: list[tuple[str, str]] = []

    def failing_double_extract(
        url: str, *, snapshot: str, session: Any | None = None
    ) -> dict[str, Any]:
        attempts.append((url, snapshot))
        raise RuntimeError("html failure")

    def failing_impl_fetch(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("impl failure")

    monkeypatch.setattr(cli, "_double_extract", failing_double_extract)
    monkeypatch.setattr(cli, "_fetch_snapshot_via_html", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_exp_backoff_sleep", lambda *a, **k: None)
    monkeypatch.setattr(cli._impl, "fetch_race_snapshot", failing_impl_fetch)
    monkeypatch.setattr(cli._impl, "discover_course_id", lambda *_args, **_kw: None, raising=False)

    caplog.set_level(logging.ERROR, logger=cli.logger.name)

    snapshot = cli.fetch_race_snapshot(
        "R1",
        "C2",
        phase="H30",
        url="https://www.zeturf.fr/fr/course/placeholder",
        retries=2,
        backoff=0.0,
        sources={"rc_map": {}},
    )

    assert attempts, "at least one direct HTML attempt should be recorded"
    assert all(url == "https://www.zeturf.fr/fr/course/placeholder" for url, _ in attempts)
    assert {label for _, label in attempts} <= {"H30", "H-30"}
    assert snapshot["reunion"] == "R1"
    assert snapshot["course"] == "C2"
    assert snapshot["runners"] == []
    assert snapshot["partants"] == []
    assert snapshot.get("partants_count") is None
    assert any(
        "échec fetch_race_snapshot" in record.getMessage()
        for record in caplog.records
    )


def test_double_extract_populates_hippodrome_from_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallback extraction should backfill both meeting and hippodrome."""

    html = """
    <html>
      <body data-meeting-name="Paris-Vincennes">
        <div data-runner-num="1" data-runner-name="Alpha" data-odds="4.2"></div>
      </body>
    </html>
    """

    monkeypatch.setattr(cli, "_http_get", lambda url, session=None: html)

    def fake_parse(url: str, snapshot: str) -> dict[str, Any]:
        return {"runners": [{"num": "1", "name": "Alpha"}]}

    monkeypatch.setattr(cli._impl, "parse_course_page", fake_parse, raising=False)

    data = cli._double_extract("https://example.test/R1C1", snapshot="H-30")

    assert data["meeting"] == "Paris-Vincennes"
    assert data["hippodrome"] == "Paris-Vincennes"
    assert data["runners"]


def test_double_extract_warns_when_no_runners(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The helper should warn when the DOM yields no runner entries."""

    html = "<html><body><p>Course indisponible</p></body></html>"

    monkeypatch.setattr(cli, "_http_get", lambda url, session=None: html)

    def fake_parse(url: str, snapshot: str) -> dict[str, Any]:
        assert snapshot in {"H-30", "H-5"}
        return {}

    monkeypatch.setattr(cli._impl, "parse_course_page", fake_parse, raising=False)

    with caplog.at_level(logging.WARNING, logger=cli.logger.name):
        data = cli._double_extract("https://example.test/R9C9", snapshot="H-5")

    assert data["runners"] == []
    assert any("Aucun partant détecté" in record.message for record in caplog.records)


def test_fallback_parse_handles_singular_partant() -> None:
    """The HTML fallback should recognise singular ``partant`` mentions."""

    html = "<div class='meta'>9 partant annoncé</div>"

    parsed = cli._fallback_parse_html(html)

    assert parsed["partants"] == 9


def test_lightweight_fetch_snapshot_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    """The public helper should fetch and normalise a remote course page."""

    captured: dict[str, Any] = {}

    def fake_parse(url: str, *, snapshot: str) -> Mapping[str, Any]:
        captured["url"] = url
        captured["snapshot"] = snapshot
        return {
            "runners": [
                {"num": "1", "name": "Alpha"},
                {"num": "2", "name": "Bravo"},
            ],
            "market": {"win": {"1": 2.8}},
        }

    def fake_normalize(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        captured["normalized"] = payload
        return {
            "runners": [
                {"num": "1", "name": "Alpha"},
                {"num": "2", "name": "Bravo"},
            ],
            "partants": 2,
        }

    monkeypatch.setattr(cli._impl, "parse_course_page", fake_parse, raising=False)
    monkeypatch.setattr(cli._impl, "normalize_snapshot", fake_normalize, raising=False)

    snapshot = cli.fetch_race_snapshot("1", "2", phase="H-5")

    assert snapshot == {
        "runners": [
            {"num": "1", "name": "Alpha"},
            {"num": "2", "name": "Bravo"},
        ],
        "partants": [
            {"num": "1", "name": "Alpha"},
            {"num": "2", "name": "Bravo"},
        ],
        "market": {"win": {"1": 2.8}},
        "phase": "H5",
    }
    assert captured["snapshot"] == "H5"
    assert captured["url"] == f"https://www.zeturf.fr/fr/course/R1C2"

    
def test_lightweight_fetch_snapshot_use_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The cache flag should bypass the remote parser and load local files."""

    payload = {
        "runners": [{"num": "7", "name": "Zulu"}],
        "partants": [{"num": "7", "name": "Zulu"}],
        "market": {"place": {"7": 1.9}},
    }
    cache_file = tmp_path / "snapshot.json"
    cache_file.write_text(json.dumps(payload), encoding="utf-8")
    
    monkeypatch.setattr(cli, "_load_local_snapshot", lambda rc: cache_file)
    monkeypatch.setattr(
        cli._impl,
        "parse_course_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("remote fetch should not happen")),
        raising=False,
    )

   snapshot = cli.fetch_race_snapshot("R9", "C3", use_cache=True) 

    assert snapshot == {
        "runners": payload["runners"],
        "partants": payload["partants"],
        "market": payload["market"],
        "phase": "H30",
    }


def test_lightweight_fetch_snapshot_cache_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing cache entry should raise a clear runtime error."""

    monkeypatch.setattr(cli, "_load_local_snapshot", lambda rc: None)

    with pytest.raises(RuntimeError):
        cli.fetch_race_snapshot("R4", "C5", use_cache=True)
        

def test_fetch_from_geny_parser_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Geny parser should fallback to attribute/regex extraction."""

    id_course = "55555"
    partants_html = """
    <section>
        <div data-num="1" data-name="Alpha" data-jockey="J1" data-entraineur="T1"></div>
        <div data-num="2" data-name="Bravo"></div>
    </section>
    """
    cotes_payload = {"runners": [{"num": "1", "cote": "3"}, {"num": "2", "cote": "5"}]}
    calls: list[str] = []

    def fake_get(url: str, headers: Any | None = None, timeout: int = 10) -> DummyResp:
        calls.append(url)
        if "partants" in url:
            return DummyResp(200, partants_html)
        if "cotes" in url:
            return DummyResp(200, cotes_payload)
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(ofz.requests, "get", fake_get)

    snap = ofz.fetch_from_geny_idcourse(id_course)

    assert [r["num"] for r in snap["runners"]] == ["1", "2"]
    assert snap["runners"][0]["jockey"] == "J1"
    assert snap["runners"][0]["entraineur"] == "T1"
    assert snap["partants"] == 2
    assert calls.count(f"{ofz.GENY_BASE}/partants-pmu/_c{id_course}") == 1


def test_fetch_from_geny_retries_on_empty_dom(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty DOM responses should trigger exponential backoff."""

    id_course = "66666"
    valid_html = """
    <table><tr><td>1</td><td>Gamma</td><td>J2</td><td>T2</td></tr></table>
    """
    partants_responses = [DummyResp(200, "   "), DummyResp(200, valid_html)]
    sleep_calls: list[float] = []

    def fake_get(url: str, headers: Any | None = None, timeout: int = 10) -> DummyResp:
        if "partants" in url:
            return partants_responses.pop(0)
        if "cotes" in url:
            return DummyResp(200, {"runners": []})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(ofz.requests, "get", fake_get)
    monkeypatch.setattr(ofz.time, "sleep", lambda delay: sleep_calls.append(delay))

    snap = ofz.fetch_from_geny_idcourse(id_course)

    assert snap["partants"] == 1
    assert sleep_calls == [0.5]


def test_fetch_from_geny_retries_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 429 responses should be retried with exponential backoff."""

    id_course = "77777"
    html = """
    <table><tr><td>1</td><td>Delta</td><td>J3</td><td>T3</td></tr></table>
    """
    responses = [DummyResp(429, None, text="Too many requests"), DummyResp(200, html)]
    sleep_calls: list[float] = []

    def fake_get(url: str, headers: Any | None = None, timeout: int = 10) -> DummyResp:
        if "partants" in url:
            return responses.pop(0)
        if "cotes" in url:
            return DummyResp(200, {"runners": []})
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(ofz.requests, "get", fake_get)
    monkeypatch.setattr(ofz.time, "sleep", lambda delay: sleep_calls.append(delay))

    snap = ofz.fetch_from_geny_idcourse(id_course)

    assert snap["partants"] == 1
    assert sleep_calls == [0.5]


def test_normalize_snapshot_logs_missing_metadata(caplog: pytest.LogCaptureFixture) -> None:
    """Missing metadata should emit a warning for visibility."""

    payload = {"rc": "R1C1", "runners": []}

    with caplog.at_level(logging.WARNING):
        meta = ofz.normalize_snapshot(payload)

    assert meta["partants"] == 0
    messages = [record.message for record in caplog.records]
    assert any("meeting" in message for message in messages)
    assert any("discipline" in message for message in messages)
    assert any("partants" in message for message in messages)
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



def test_normalize_snapshot_honours_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    """ISO datetimes should be converted to the timezone specified via ``$TZ``."""

    payload = sample_snapshot()
    payload["start_time"] = "2025-09-10T15:42:00+02:00"

    ofz._env_timezone.cache_clear()
    monkeypatch.setenv("TZ", "UTC")
    try:
        normalized = ofz.normalize_snapshot(payload)
    finally:
        ofz._env_timezone.cache_clear()

    assert normalized["start_time"] == "13:42"


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

    url_file = out.with_name(out.name + ".url")
    assert url_file.exists()
    assert url_file.read_text(encoding="utf-8") == "http://x"


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

    url1 = out_dir / "R1C1" / "source_url.txt"
    url2 = out_dir / "R1C2" / "source_url.txt"
    assert url1.read_text(encoding="utf-8") == "https://api.example/race/11111"
    assert url2.read_text(encoding="utf-8") == "https://api.example/race/22222"


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

    url_file = out.with_name(out.name + ".url")
    assert url_file.exists()
    assert url_file.read_text(encoding="utf-8") == "http://x"


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
