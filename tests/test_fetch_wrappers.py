from __future__ import annotations

import json
from pathlib import Path

import pytest

import fetch_je_chrono
import fetch_je_stats


def test_fetch_je_stats_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    course_dir = tmp_path / "R1C1"
    course_dir.mkdir()
    snapshot = course_dir / "R1C1_H-5.json"
    snapshot.write_text(
        json.dumps({"course_id": "123", "runners": [{"id": "1", "name": "Alpha"}]}),
        encoding="utf-8",
    )

    def fake_collect(course_id: str, h5_path: str):
        assert course_id == "123"
        assert Path(h5_path) == snapshot
        return 87.5, {"1": {"j_win": 12.3, "e_win": 45.6}}

    monkeypatch.setattr(fetch_je_stats, "collect_stats", fake_collect)

    result = fetch_je_stats.enrich_from_snapshot(snapshot, "R1", "C1")

    assert result["ok"] is True
    assert result["coverage"] == pytest.approx(87.5)

    stats_path = course_dir / "stats_je.json"
    csv_path = course_dir / "R1C1_H-5_je.csv"

    assert result["paths"] == {
        "stats_json": str(stats_path),
        "je_csv": str(csv_path),
    }

    payload = json.loads(stats_path.read_text(encoding="utf-8"))
    assert payload["coverage"] == pytest.approx(87.5)
    assert payload["1"] == {"j_win": 12.3, "e_win": 45.6}

    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines == ["num,nom,j_rate,e_rate", "1,Alpha,12.3,45.6"]


def test_fetch_je_stats_handles_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(json.dumps({"course_id": "123"}), encoding="utf-8")

    def failing_collect(*_args, **_kwargs):  # pragma: no cover - deliberate failure
        raise RuntimeError("network down")

    monkeypatch.setattr(fetch_je_stats, "collect_stats", failing_collect)

    result = fetch_je_stats.enrich_from_snapshot(snapshot, "R1", "C1")

    assert result == {"ok": False, "reason": "network down"}
    assert not (tmp_path / "stats_je.json").exists()
    assert not list(tmp_path.glob("*_je.csv"))


def test_fetch_je_chrono_builds_csv(tmp_path: Path) -> None:
    course_dir = tmp_path / "R1C1"
    course_dir.mkdir()
    snapshot = course_dir / "R1C1_H-5.json"
    snapshot.write_text(
        json.dumps(
            {
                "partants": {
                    "runners": [
                        {"id": "1", "chrono": "1.12"},
                        {"id": "2", "time": "1.18"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = fetch_je_chrono.enrich_from_snapshot(snapshot, "R1", "C1")

    assert result == {"ok": True, "paths": {"chronos": str(course_dir / "chronos.csv")}}

    lines = (course_dir / "chronos.csv").read_text(encoding="utf-8").splitlines()
    assert lines == ["num,chrono", "1,1.12", "2,1.18"]


def test_fetch_je_chrono_handles_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(json.dumps({"runners": []}), encoding="utf-8")

    def boom(*_args, **_kwargs):  # pragma: no cover - deliberate failure
        raise OSError("disk full")

    monkeypatch.setattr(fetch_je_chrono, "_write_chronos_csv", boom)

    result = fetch_je_chrono.enrich_from_snapshot(snapshot, "R1", "C1")

    assert result == {"ok": False, "reason": "io-error: disk full"}
    assert not (tmp_path / "chronos.csv").exists()
