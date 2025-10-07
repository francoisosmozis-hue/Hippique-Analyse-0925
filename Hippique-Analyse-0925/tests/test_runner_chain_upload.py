import datetime as dt
import pathlib

import scripts.runner_chain as rc


def test_upload_file_called_for_snapshot(tmp_path, monkeypatch):
    called = []

    def fake_upload(path):
        called.append(pathlib.Path(path))

    monkeypatch.setattr(rc, "upload_file", fake_upload)
    monkeypatch.setattr(rc, "USE_GCS", True)
    monkeypatch.setattr(rc, "_load_sources_config", lambda: {})
    monkeypatch.setattr(rc.ofz, "fetch_race_snapshot", lambda *a, **k: {"rc": "R1C1"})

    payload = rc.RunnerPayload(
        id_course="123456",
        reunion="R1",
        course="C1",
        phase="H30",
        start_time=dt.datetime(2024, 1, 1, 12, 0),
        budget=5.0,
    )

    rc._write_snapshot(payload, "H30", tmp_path)

    assert called == [tmp_path / "R1C1" / "snapshot_H30.json"]


def test_upload_file_called_for_analysis(tmp_path, monkeypatch):
    called = []

    def fake_upload(path):
        called.append(pathlib.Path(path))

    monkeypatch.setattr(rc, "upload_file", fake_upload)
    monkeypatch.setattr(rc, "simulate_ev_batch", lambda *a, **k: {"ev": 0.5, "roi": 0.3, "green": True})
    monkeypatch.setattr(rc, "validate_ev", lambda *a, **k: None)
    monkeypatch.setattr(rc, "USE_GCS", True)

    rc._write_analysis(
        "R1C1",
        tmp_path,
        budget=5.0,
        ev_min=0.4,
        roi_min=0.2,
        mode="test",
    )

    assert called == [tmp_path / "R1C1" / "analysis.json"]
