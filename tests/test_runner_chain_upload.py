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
    monkeypatch.setattr(rc, "USE_GCS", True)

    # Create dummy files required by _write_analysis
    race_dir = tmp_path / "R1C1"
    race_dir.mkdir()
    (race_dir / "snapshot_H5.json").write_text('{"payload": {"runners": [{"num": "1", "odds": 2.0}]}}')
    (race_dir / "je_stats.csv").touch()
    (race_dir / "chronos.csv").touch()

    # Mock dutching to return a passing portfolio
    import pandas as pd
    bets_df = pd.DataFrame({
        "EV (€)": [1.0], "Stake (€)": [1.0], "Gain brut (€)": [11.0]
    })
    monkeypatch.setattr(rc, "dutching_kelly_fractional", lambda **kwargs: bets_df)
    
    # Mock config loading to ensure gates pass
    monkeypatch.setattr(rc, "_load_gpi_config", lambda: {"ROI_MIN_SP": 0.1, "EV_MIN_SP": 0.1})

    rc._write_analysis(
        "R1C1",
        tmp_path,
        budget=5.0,
        ev_min=0.4,
        roi_min=0.2,
        mode="test",
        calibration=tmp_path / "cal.yaml",
        calibration_available=False,
    )

    assert called == [tmp_path / "R1C1" / "analysis.json"]
