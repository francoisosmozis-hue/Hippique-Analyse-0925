import json
import datetime as dt
from pathlib import Path

from scripts import runner_chain


def test_write_analysis_disables_exotics_without_stats(monkeypatch, tmp_path):
    snap_dir = tmp_path / "snapshots"
    analysis_dir = tmp_path / "analysis"
    snap_dir.mkdir()
    analysis_dir.mkdir()

    payload = runner_chain.RunnerPayload(
        id_course="123456",
        reunion="R1",
        course="C1",
        phase="H5",
        start_time=dt.datetime.now(dt.timezone.utc),
        budget=5.0,
    )

    race_snap_dir = snap_dir / payload.race_id
    race_snap_dir.mkdir()

    # Minimal snapshot inputs
    for name in ("h30.json", "h5.json"):
        (race_snap_dir / name).write_text("{}\n", encoding="utf-8")
    partants_payload = {"runners": [{"id": "1", "name": "Alpha", "odds": 2.0}]}
    (race_snap_dir / "partants.json").write_text(json.dumps(partants_payload), encoding="utf-8")

    recorded_kwargs: dict[str, object] = {}

    def fake_run_pipeline(**kwargs):
        recorded_kwargs.update(kwargs)
        outdir = Path(kwargs["outdir"])
        outdir.mkdir(parents=True, exist_ok=True)
        finale_payload = {
            "tickets": [
                {"type": "SP_DUTCH", "label": "SP", "stake": 3.0},
                {"type": "TRIO", "label": "TRIO", "stake": 2.0},
            ],
            "meta": {"market": {"overround": 1.10}},
        }
        (outdir / "p_finale.json").write_text(json.dumps(finale_payload), encoding="utf-8")
        (outdir / "metrics.json").write_text(json.dumps({"tickets": {"total": 2}}), encoding="utf-8")
        return {
            "outdir": str(outdir),
            "metrics": {"status": "ok", "tickets": {"total": 2, "sp": 1, "combo": 1}},
        }

    monkeypatch.setattr(runner_chain.pipeline_run, "run_pipeline", fake_run_pipeline)

    monkeypatch.setattr(runner_chain, "USE_GCS", False)
    monkeypatch.setattr(runner_chain, "upload_file", None, raising=False)

    runner_chain._write_analysis(
        payload,
        snap_dir,
        analysis_dir,
        budget=5.0,
        ev_min=0.4,
        roi_min=0.25,
        mode="H5",
        calibration=Path("calibration/payout_calibration.yaml"),
    )

    assert "stats_je" not in recorded_kwargs

    race_dir = analysis_dir / payload.race_id
    analysis_data = json.loads((race_dir / "analysis.json").read_text(encoding="utf-8"))
    assert analysis_data.get("exotics_disabled") is True
    notes = analysis_data.get("notes") or []
    assert any("stats_je" in note for note in notes)

    finale = json.loads((race_dir / "p_finale.json").read_text(encoding="utf-8"))
    tickets = finale.get("tickets") or []
    assert len(tickets) == 1
    assert tickets[0].get("type") == "SP_DUTCH"
