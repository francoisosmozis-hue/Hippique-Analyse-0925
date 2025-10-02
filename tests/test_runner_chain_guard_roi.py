import csv
from pathlib import Path

import runner_chain


_DEF_PARAMS = {
    "budget": 100.0,
    "overround_max": 1.30,
    "ev_min_exotic": 0.4,
    "payout_min_exotic": 15.0,
    "ev_min_sp": 0.0,
    "roi_min_global": 0.08,
    "kelly_frac": 0.4,
}


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _analyse(course_dir: Path, **overrides):
    params = dict(_DEF_PARAMS)
    params.update(overrides)
    params.setdefault("calibration", str(course_dir / "calibration.yaml"))
    return runner_chain._analyse_course(course_dir, **params)


def test_analyse_course_rejects_when_roi_below_threshold(tmp_path, monkeypatch):
    course_dir = tmp_path / "R1C5"
    course_dir.mkdir()

    _write_csv(
        course_dir / "je_stats.csv",
        ["id", "odds_place", "p_place"],
        [
            {"id": "A", "odds_place": "3.0", "p_place": "0.33"},
            {"id": "B", "odds_place": "4.0", "p_place": "0.25"},
        ],
    )
    _write_csv(
        course_dir / "chronos.csv",
        ["num", "chrono", "ok"],
        [{"num": "1", "chrono": "1'14\"", "ok": "1"}],
    )

    def fake_allocate(cfg, runners):
        return ([{**runner, "stake": 5.0} for runner in runners], 30.0)

    def fake_simulate(tickets, bankroll, kelly_cap):
        assert tickets
        return {"ev": 4.0, "ev_ratio": 0.04, "roi": 0.02}

    monkeypatch.setattr(runner_chain, "allocate_dutching_sp", fake_allocate)
    monkeypatch.setattr(runner_chain, "simulate_ev_batch", fake_simulate)

    payload = _analyse(course_dir)

    assert payload["status"] == "abstain"
    assert "roi_global_below_min" in payload["reasons"]
    assert payload["tickets"] == []
    assert payload["guards"]["jouable"] is False
    assert payload["guards"]["sp_final"] == 0
