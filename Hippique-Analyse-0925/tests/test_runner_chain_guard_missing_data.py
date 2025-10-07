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


def _analyse(course_dir: Path, **overrides):
    params = dict(_DEF_PARAMS)
    params.update(overrides)
    params.setdefault("calibration", str(course_dir / "calibration.yaml"))
    return runner_chain._analyse_course(course_dir, **params)


def test_analyse_course_aborts_when_je_missing(tmp_path):
    course_dir = tmp_path / "R1C1"
    course_dir.mkdir()
    (course_dir / "chronos.csv").write_text("num,chrono,ok\n1,1.0,1\n", encoding="utf-8")

    payload = _analyse(course_dir)

    assert payload["status"] == "aborted"
    assert payload["tickets"] == []
    assert payload["reasons"] == ["data_missing"]

    guards = payload["guards"]
    assert guards["jouable"] is False
    assert guards["reason"] == "data_missing"
    assert "je_stats" in guards["missing"]


def test_analyse_course_aborts_when_chronos_missing(tmp_path):
    course_dir = tmp_path / "R1C2"
    course_dir.mkdir()
    (course_dir / "je_stats.csv").write_text(
        "id,odds_place,p_place\n1,2.5,0.45\n", encoding="utf-8"
    )

    payload = _analyse(course_dir)

    assert payload["status"] == "aborted"
    assert payload["tickets"] == []
    assert payload["reasons"] == ["data_missing"]

    guards = payload["guards"]
    assert guards["jouable"] is False
    assert guards["reason"] == "data_missing"
    assert "chronos" in guards["missing"]
