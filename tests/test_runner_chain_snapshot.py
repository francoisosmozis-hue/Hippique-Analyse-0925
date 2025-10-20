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
    def fake_fetch(*args, **kwargs):
        return {
            "rc": "R1C2",
            "course_id": "654321",
            "hippodrome": "Testville",
            "runners": [
                {"id": "1", "name": "Alpha", "odds": 2.5},
                {"id": "2", "name": "Beta", "odds": 3.0},
            ],
        }
    monkeypatch.setattr(ofz, "fetch_race_snapshot", fake_fetch)

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
    def fake_fetch_fail(*args, **kwargs):
        raise requests.ConnectionError("boom")
    monkeypatch.setattr(ofz, "fetch_race_snapshot", fake_fetch_fail)

    rc._write_snapshot(runner_payload, "H30", tmp_path)

    out_path = tmp_path / "R1C2" / "snapshot_H30.json"
    data = json.loads(out_path.read_text(encoding="utf-8"))

    assert data["status"] == "no-data"
    assert data["rc"] == "R1C2"
    assert data["phase"] == "H30"
    assert "boom" in data["reason"]


def test_cli_single_race_uses_course_url(tmp_path, monkeypatch):
    # 1. Create dummy race directory and snapshot
    race_dir = tmp_path / "R1C2"
    race_dir.mkdir()
    snapshot_path = race_dir / "snapshot_H5.json"
    snapshot_data = {
        "payload": {
            "course_id": "654321",
            "reunion": "R1",
            "course": "C2",
            "start_time": "2024-01-01T12:00:00"
        }
    }
    snapshot_path.write_text(json.dumps(snapshot_data))

    # 2. Mock _trigger_phase to capture arguments
    captured_args = {}
    def fake_trigger_phase(payload, course_url=None, **kwargs):
        captured_args['payload'] = payload
        captured_args['course_url'] = course_url

    monkeypatch.setattr(rc, "_trigger_phase", fake_trigger_phase)

    # 3. Set sys.argv
    argv = [
        "runner_chain.py",
        str(race_dir), # Use directory path as main argument
        "--course-url",
        "https://example.test/r1c2",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    # 4. Call main
    rc.main()

    # 5. Assertions
    assert captured_args['course_url'] == "https://example.test/r1c2"
    assert captured_args['payload'].race_id == "R1C2"
