import datetime as dt
import json
import sys

import pytest
import requests

import scripts.runner_chain as rc
from scripts import online_fetch_zeturf as ofz


class DummyResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self) -> dict[str, object]:
        return self._payload


@pytest.fixture
def runner_payload() -> rc.RunnerPayload:
    return rc.RunnerPayload(
        id_course="654321",
        reunion="R1",
        course="C2",
        phase="H30",
        start_time=dt.datetime(2024, 1, 1, 12, 0),
        budget=5.0,
    )


@pytest.fixture(autouse=True)
def disable_gcs(monkeypatch):
    monkeypatch.setattr(rc, "USE_GCS", False)
    monkeypatch.setattr(rc, "upload_file", None)


def test_write_snapshot_success(tmp_path, monkeypatch, runner_payload):
    sources = {"zeturf": {"url": "https://example.test/race/{course_id}"}}
    monkeypatch.setattr(rc, "_load_sources_config", lambda: sources)
    monkeypatch.setattr(ofz.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        ofz, "_scrape_start_time_from_course_page", lambda course_id: "13:45"
    )

    def fake_get(url, timeout=None, headers=None):
        assert url == "https://example.test/race/654321"
        return DummyResponse(
            {
                "rc": "R1C2",
                "course_id": "654321",
                "hippodrome": "Testville",
                "runners": [
                    {"id": "1", "name": "Alpha", "odds": 2.5},
                    {"id": "2", "name": "Beta", "odds": 3.0},
                ],
            }
        )

    monkeypatch.setattr(ofz.requests, "get", fake_get)

    rc._write_snapshot(runner_payload, "H30", tmp_path)

    out_path = tmp_path / "R1C2" / "snapshot_H30.json"
    data = json.loads(out_path.read_text(encoding="utf-8"))

    assert data["status"] == "ok"
    assert data["rc"] == "R1C2"
    assert data["phase"] == "H30"
    assert data["payload"]["rc"] == "R1C2"
    assert [runner["name"] for runner in data["payload"]["runners"]] == [
        "Alpha",
        "Beta",
    ]


def test_write_snapshot_network_error(tmp_path, monkeypatch, runner_payload):
    sources = {"zeturf": {"url": "https://example.test/race/{course_id}"}}
    monkeypatch.setattr(rc, "_load_sources_config", lambda: sources)
    monkeypatch.setattr(ofz.time, "sleep", lambda *a, **k: None)

    def failing_get(url, timeout=None, headers=None):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(ofz.requests, "get", failing_get)

    rc._write_snapshot(runner_payload, "H30", tmp_path)

    out_path = tmp_path / "R1C2" / "snapshot_H30.json"
    data = json.loads(out_path.read_text(encoding="utf-8"))

    assert data["status"] == "no-data"
    assert data["rc"] == "R1C2"
    assert data["phase"] == "H30"
    assert "boom" in data["reason"]


def test_cli_single_race_uses_course_url(tmp_path, monkeypatch):
    sources_config = {"rc_map": {"R9C9": {"course_id": "999"}}}
    monkeypatch.setattr(rc, "_load_sources_config", lambda: sources_config)

    captured: dict[str, object] = {}

    def fake_fetch(
        reunion: str,
        course: str | None = None,
        phase: str = "H30",
        *,
        sources: dict | None = None,
        url: str | None = None,
        **_: object,
    ) -> dict[str, object]:
        captured["reunion"] = reunion
        captured["course"] = course
        captured["phase"] = phase
        captured["url"] = url
        captured["sources"] = sources or {}
        return {"rc": f"{reunion}{course}", "runners": []}

    monkeypatch.setattr(ofz, "fetch_race_snapshot", fake_fetch)

    argv = [
        "runner_chain",
        "--course-id",
        "654321",
        "--reunion",
        "R1",
        "--course",
        "C2",
        "--phase",
        "H30",
        "--start-time",
        "2024-01-01T12:00:00",
        "--snap-dir",
        str(tmp_path),
        "--analysis-dir",
        str(tmp_path / "analysis"),
        "--course-url",
        "https://example.test/r1c2",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    rc.main()

    assert captured["url"] == "https://example.test/r1c2"
    sources_arg = captured["sources"]
    assert isinstance(sources_arg, dict)
    rc_map = dict(sources_arg.get("rc_map", {}))
    assert "R1C2" not in rc_map
    assert rc_map == {"R9C9": {"course_id": "999"}}
