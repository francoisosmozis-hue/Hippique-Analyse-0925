"""Tests covering the H-5 fail-safe logic in ``analyse_courses_du_jour_enrichie``."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import analyse_courses_du_jour_enrichie as acd


def _write_snapshot(rc_dir: Path) -> Path:
    """Create a minimal H-5 snapshot file and return its path."""

    rc_dir.mkdir(parents=True, exist_ok=True)
    snap = rc_dir / "R1C1_H-5.json"
    if not snap.exists():
        snap.write_text("{}\n", encoding="utf-8")
    return snap


def test_safe_enrich_h5_succeeds_when_csv_present(tmp_path, monkeypatch):
    """The fail-safe should pass through when JE/chronos are produced."""

    rc_dir = tmp_path / "R1C1"
    snapshot = _write_snapshot(rc_dir)
    chronos = rc_dir / "chronos.csv"
    je_csv = rc_dir / f"{snapshot.stem}_je.csv"

    calls: dict[str, int] = {"enrich": 0}

    def fake_enrich(target: Path, *, budget: float, kelly: float) -> None:
        assert target == rc_dir
        calls["enrich"] += 1
        snapshot.touch()
        chronos.write_text("num\n1\n", encoding="utf-8")
        je_csv.write_text("num\n1\n", encoding="utf-8")

    monkeypatch.setattr(acd, "enrich_h5", fake_enrich)

    success, outcome = acd.safe_enrich_h5(rc_dir, budget=5.0, kelly=0.05)

    assert success is True
    assert outcome is None
    assert calls["enrich"] == 1, "enrich_h5 should not be retried when CSV exist"
    assert chronos.exists()
    assert je_csv.exists()
    assert not (rc_dir / "UNPLAYABLE.txt").exists()


def test_safe_enrich_h5_marks_course_unplayable(tmp_path, monkeypatch):
    """Missing CSV after retry should mark the course as unplayable."""

    rc_dir = tmp_path / "R1C1"
    snapshot = _write_snapshot(rc_dir)

    calls: dict[str, int] = {"enrich": 0}

    def fake_enrich(target: Path, *, budget: float, kelly: float) -> None:
        assert target == rc_dir
        calls["enrich"] += 1
        snapshot.touch()

    monkeypatch.setattr(acd, "enrich_h5", fake_enrich)
    monkeypatch.setattr(acd, "_run_fetch_script", lambda *a, **k: False)
    monkeypatch.setattr(acd, "_regenerate_chronos_csv", lambda *_a, **_k: False)
    monkeypatch.setattr(acd.time, "sleep", lambda _delay: None)

    success, outcome = acd.safe_enrich_h5(rc_dir, budget=5.0, kelly=0.05)

    assert success is False
    assert isinstance(outcome, dict)
    assert outcome.get("reason") == "data-missing"
    assert calls["enrich"] >= 2, "enrich_h5 should be retried once"

    marker = rc_dir / "UNPLAYABLE.txt"
    assert marker.exists()
    assert "non jouable" in marker.read_text(encoding="utf-8")


def test_safe_enrich_h5_recovers_after_stats_fetch(tmp_path, monkeypatch):
    """Successful stats fetch should regenerate the JE CSV and resume."""

    rc_dir = tmp_path / "R1C1"
    snapshot = _write_snapshot(rc_dir)
    chronos = rc_dir / "chronos.csv"
    partants = rc_dir / "partants.json"
    stats = rc_dir / "stats_je.json"
    je_csv = rc_dir / f"{snapshot.stem}_je.csv"

    calls: dict[str, int] = {"enrich": 0}

    def fake_enrich(target: Path, *, budget: float, kelly: float) -> None:
        assert target == rc_dir
        calls["enrich"] += 1
        snapshot.touch()
        chronos.write_text("num\n1\n", encoding="utf-8")
        partants.write_text(
            json.dumps(
                {
                    "id2name": {"1": "Alpha"},
                    "runners": [{"id": "1", "name": "Alpha"}],
                }
            ),
            encoding="utf-8",
        )
        if stats.exists():
            stats.unlink()
        if je_csv.exists():
            je_csv.unlink()

    fetch_calls = {"stats": 0, "chrono": 0}
    
    def fake_fetch(script_path: Path, course_dir: Path) -> bool:
        assert course_dir == rc_dir
        if script_path == acd._FETCH_JE_STATS_SCRIPT:
            fetch_calls["stats"] += 1
            stats.write_text(
                json.dumps({"coverage": 100, "1": {"j_win": "0.10", "e_win": "0.20"}}),
                encoding="utf-8",
            )
            return True
        fetch_calls["chrono"] += 1
        return False

    monkeypatch.setattr(acd, "enrich_h5", fake_enrich)
    monkeypatch.setattr(acd, "_run_fetch_script", fake_fetch)
    monkeypatch.setattr(acd.time, "sleep", lambda _delay: None)

    success, outcome = acd.safe_enrich_h5(rc_dir, budget=5.0, kelly=0.05)

    assert success is True
    assert outcome is None
    assert calls["enrich"] == 2
    assert je_csv.exists()
    assert not (rc_dir / "UNPLAYABLE.txt").exists()
    assert fetch_calls == {"stats": 1, "chrono": 0}

    content = je_csv.read_text(encoding="utf-8")
    rows = list(csv.reader(io.StringIO(content)))
    assert rows[0] == ["num", "nom", "j_rate", "e_rate"]
    assert rows[1] == ["1", "Alpha", "0.10", "0.20"]
