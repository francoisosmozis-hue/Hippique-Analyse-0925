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
    assert calls["enrich"] == 1
    assert je_csv.exists()
    assert not (rc_dir / "UNPLAYABLE.txt").exists()
    assert fetch_calls == {"stats": 1, "chrono": 0}

    content = je_csv.read_text(encoding="utf-8")
    rows = list(csv.reader(io.StringIO(content)))
    assert rows[0] == ["num", "nom", "j_rate", "e_rate"]
    assert rows[1] == ["1", "Alpha", "0.10", "0.20"]


def test_safe_enrich_h5_retries_when_rebuild_impossible(tmp_path, monkeypatch):
    """If rebuild fails after stats fetch, ``enrich_h5`` should be retried."""

    rc_dir = tmp_path / "R1C3"
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
        if calls["enrich"] == 1:
            if partants.exists():
                partants.unlink()
            if je_csv.exists():
                je_csv.unlink()
        else:
            partants.write_text(
                json.dumps(
                    {
                        "id2name": {"1": "Gamma"},
                        "runners": [{"id": "1", "name": "Gamma"}],
                    }
                ),
                encoding="utf-8",
            )
            je_csv.write_text(
                "num,nom,j_rate,e_rate\n1,Gamma,0.50,0.60\n",
                encoding="utf-8",
            )

    def fake_fetch(script_path: Path, course_dir: Path) -> bool:
        assert script_path == acd._FETCH_JE_STATS_SCRIPT
        assert course_dir == rc_dir
        stats.write_text(
            json.dumps({"coverage": 100, "1": {"j_win": "0.50", "e_win": "0.60"}}),
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(acd, "enrich_h5", fake_enrich)
    monkeypatch.setattr(acd, "_run_fetch_script", fake_fetch)
    monkeypatch.setattr(acd.time, "sleep", lambda _delay: None)

    success, outcome = acd.safe_enrich_h5(rc_dir, budget=5.0, kelly=0.05)

    assert success is True
    assert outcome is None
    assert calls["enrich"] == 2, "enrich_h5 should be retried when rebuild fails"
    assert je_csv.exists()
    assert not (rc_dir / "UNPLAYABLE.txt").exists()

    content = je_csv.read_text(encoding="utf-8")
    rows = list(csv.reader(io.StringIO(content)))
    assert rows[0] == ["num", "nom", "j_rate", "e_rate"]
    assert rows[1] == ["1", "Gamma", "0.50", "0.60"]


def test_ensure_h5_artifacts_rebuilds_csv_from_stats(tmp_path, monkeypatch):
    """_ensure_h5_artifacts should rebuild the JE CSV after a stats fetch."""

    rc_dir = tmp_path / "R2C1"
    snap = _write_snapshot(rc_dir)
    chronos = rc_dir / "chronos.csv"
    chronos.write_text("num,chrono\n1,\n", encoding="utf-8")

    (rc_dir / "partants.json").write_text(
        json.dumps({"id2name": {"1": "Bravo"}, "runners": [{"id": "1", "name": "Bravo"}]}),
        encoding="utf-8",
    )

    stats_path = rc_dir / "stats_je.json"

    fetch_calls: list[Path] = []

    def fake_fetch(script_path: Path, course_dir: Path) -> bool:
        assert course_dir == rc_dir
        if script_path == acd._FETCH_JE_STATS_SCRIPT:
            fetch_calls.append(script_path)
            stats_path.write_text(
                json.dumps({"coverage": 100, "1": {"j_win": "0.30", "e_win": "0.40"}}),
                encoding="utf-8",
            )
            return True
        return False

    monkeypatch.setattr(acd, "_run_fetch_script", fake_fetch)
    monkeypatch.setattr(acd.time, "sleep", lambda _delay: None)

    outcome = acd._ensure_h5_artifacts(rc_dir)

    assert outcome is None
    assert fetch_calls == [acd._FETCH_JE_STATS_SCRIPT]

    je_csv = rc_dir / f"{snap.stem}_je.csv"
    assert je_csv.exists()
    assert not (rc_dir / "UNPLAYABLE.txt").exists()

    rows = list(csv.reader(io.StringIO(je_csv.read_text(encoding="utf-8"))))
    assert rows[0] == ["num", "nom", "j_rate", "e_rate"]
    assert rows[1] == ["1", "Bravo", "0.30", "0.40"]


def test_rebuild_from_stats_uses_normalized_payload(tmp_path):
    """Fallback rebuild should use normalized snapshots when partants absent."""

    rc_dir = tmp_path / "R1C2"
    snapshot = _write_snapshot(rc_dir)

    normalized = rc_dir / "normalized_h5.json"
    normalized.write_text(
        json.dumps(
            {
                "id2name": {"3": "Bravo"},
                "runners": [{"id": "3", "name": "Bravo"}],
            }
        ),
        encoding="utf-8",
    )

    stats_payload = {"coverage": 100, "3": {"j_win": "0.30", "e_win": "0.40"}}
    (rc_dir / "stats_je.json").write_text(json.dumps(stats_payload), encoding="utf-8")

    assert acd._rebuild_je_csv_from_stats(rc_dir) is True

    je_csv = rc_dir / f"{snapshot.stem}_je.csv"
    assert je_csv.exists()

    rows = list(csv.reader(io.StringIO(je_csv.read_text(encoding="utf-8"))))
    assert rows[0] == ["num", "nom", "j_rate", "e_rate"]
    assert rows[1] == ["3", "Bravo", "0.30", "0.40"]
