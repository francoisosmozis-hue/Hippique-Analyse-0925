import csv
import json
from pathlib import Path

import pytest

import runner_chain


_DEF_PARAMS = {
    "budget": 100.0,
    "overround_max": 1.30,
    "ev_min_exotic": 0.4,
    "payout_min_exotic": 15.0,
    "ev_min_sp": 0.0,
    "roi_min_global": 0.05,
    "kelly_frac": 0.4,
}


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: value for key, value in row.items()})


def _analyse(course_dir: Path, **overrides):
    params = dict(_DEF_PARAMS)
    params.update(overrides)
    params.setdefault("calibration", str(course_dir / "calibration.yaml"))
    return runner_chain._analyse_course(course_dir, **params)


@pytest.fixture
def course_with_combo(tmp_path):
    course_dir = tmp_path / "R1C4"
    course_dir.mkdir()

    combo = [{"combo_id": "CP1", "combo_legs": ["1", "2"], "combo_odds": 18.0, "combo_p": 0.05}]
    _write_csv(
        course_dir / "je_stats.csv",
        ["id", "odds_place", "p_place", "combo_json", "combo_overround"],
        [
            {
                "id": "A",
                "odds_place": "3.0",
                "p_place": "0.30",
                "combo_json": json.dumps(combo),
                "combo_overround": "1.60",
            },
            {"id": "B", "odds_place": "4.0", "p_place": "0.25", "combo_json": "", "combo_overround": ""},
        ],
    )
    _write_csv(
        course_dir / "chronos.csv",
        ["num", "chrono", "ok"],
        [{"num": "1", "chrono": "1'13\"", "ok": "1"}],
    )
    return course_dir


def test_analyse_course_flags_combo_overround(monkeypatch, course_with_combo):
    def fake_sp_candidates(_rows):
        return [
            {"id": "A", "odds": 3.0, "p": 0.3},
            {"id": "B", "odds": 4.0, "p": 0.25},
        ]

    def fake_allocate(cfg, runners):
        assert len(runners) == 2
        return ([{"id": r["id"], "stake": 5.0} for r in runners], 20.0)

    def fake_simulate(tickets, bankroll, kelly_cap):
        return {"ev": 5.0, "ev_ratio": 0.05, "roi": 0.10}

    monkeypatch.setattr(runner_chain, "_extract_sp_candidates", fake_sp_candidates)
    monkeypatch.setattr(runner_chain, "allocate_dutching_sp", fake_allocate)
    monkeypatch.setattr(runner_chain, "simulate_ev_batch", fake_simulate)

    payload = _analyse(course_with_combo)

    assert "combo_overround_exceeded" in payload["reasons"]
    assert payload["guards"]["combo_overround"] == pytest.approx(1.60)
    assert payload["guards"]["jouable"] is True
    assert payload["tickets"]
    assert all(ticket.get("type") != "CP" for ticket in payload["tickets"])
