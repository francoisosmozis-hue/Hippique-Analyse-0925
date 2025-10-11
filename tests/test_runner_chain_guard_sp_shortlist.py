import csv
from pathlib import Path

import runner_chain

_DEF_PARAMS = {
    "budget": 100.0,
    "overround_max": 1.30,
    "ev_min_exotic": 0.4,
    "payout_min_exotic": 15.0,
    "ev_min_sp": 0.1,
    "roi_min_global": 0.05,
    "kelly_frac": 0.4,
}


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
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


def test_analyse_course_abstains_with_single_sp_candidate(tmp_path):
    course_dir = tmp_path / "R1C3"
    course_dir.mkdir()

    _write_csv(
        course_dir / "je_stats.csv",
        ["id", "odds_place", "p_place"],
        [{"id": "A", "odds_place": "2.4", "p_place": "0.45"}],
    )
    _write_csv(
        course_dir / "chronos.csv",
        ["num", "chrono", "ok"],
        [{"num": "1", "chrono": "1'15\"", "ok": "1"}],
    )

    payload = _analyse(course_dir)

    assert payload["status"] == "abstain"
    assert payload["tickets"] == []
    assert "sp_insufficient_candidates" in payload["reasons"]

    guards = payload["guards"]
    assert guards["jouable"] is False
    assert guards["sp_candidates"] == 1
    assert guards["sp_final"] == 0
