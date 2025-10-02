from __future__ import annotations

import json
from pathlib import Path

import pytest

import fetch_je_chrono
import fetch_je_stats


def test_fetch_je_stats_wrapper_uses_snapshot_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    course_dir = tmp_path / "R1C1"
    course_dir.mkdir()
    snapshot = tmp_path / "R1C1_H-5.json"
    snapshot.write_text(
        json.dumps({"meta": {"course_dir": str(course_dir)}}),
        encoding="utf-8",
    )

    calls: list[tuple[Path, str, str]] = []

    def fake_materialise(directory: Path, reunion: str, course: str) -> Path:
        calls.append((directory, reunion, course))
        return directory / f"{reunion}{course}_je.csv"

    monkeypatch.setattr(fetch_je_stats, "_materialise_stats", fake_materialise)

    csv_path = fetch_je_stats.enrich_from_snapshot(snapshot, "r1", "c1")

    assert csv_path == course_dir / "R1C1_je.csv"
    assert calls == [(course_dir, "R1", "C1")]


def test_fetch_je_stats_wrapper_accepts_snapshot_h5(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    course_dir = tmp_path / "R1C1"
    course_dir.mkdir()
    snapshot = tmp_path / "snapshot_H5.json"
    snapshot.write_text(
        json.dumps({"meta": {"course_dir": str(course_dir)}}),
        encoding="utf-8",
    )

    calls: list[tuple[Path, str, str]] = []

    def fake_materialise(directory: Path, reunion: str, course: str) -> Path:
        calls.append((directory, reunion, course))
        return directory / f"{reunion}{course}_je.csv"

    monkeypatch.setattr(fetch_je_stats, "_materialise_stats", fake_materialise)

    csv_path = fetch_je_stats.enrich_from_snapshot(snapshot, "r1", "c1")

    assert csv_path == course_dir / "R1C1_je.csv"
    assert calls == [(course_dir, "R1", "C1")]


def test_fetch_je_stats_wrapper_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    course_dir = tmp_path / "R1C1"
    course_dir.mkdir()
    snapshot = tmp_path / "R1C1_H-5.json"
    snapshot.write_text(
        json.dumps({"meta": {"course_dir": str(course_dir)}}),
        encoding="utf-8",
    )

    csv_path = course_dir / "R1C1_je.csv"
    csv_path.write_text("num,nom\n", encoding="utf-8")

    def forbidden(*_args, **_kwargs):  # pragma: no cover - defensive guard
        raise AssertionError("_materialise_stats should not be called when CSV exists")

    monkeypatch.setattr(fetch_je_stats, "_materialise_stats", forbidden)

    result = fetch_je_stats.enrich_from_snapshot(snapshot, "R1", "C1")

    assert result == csv_path


def test_fetch_je_stats_materialise_builds_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    course_dir = tmp_path / "R1C1"
    course_dir.mkdir()
    snapshot = course_dir / "normalized_h5.json"
    snapshot.write_text(
        json.dumps({"course_id": "123", "runners": [{"id": "1", "name": "Alpha"}]}),
        encoding="utf-8",
    )

    def fake_collect(course_id: str, h5_path: str):
        assert course_id == "123"
        assert Path(h5_path) == snapshot
        return 87.5, {"1": {"j_win": 12.3, "e_win": 45.6}}

    monkeypatch.setattr(fetch_je_stats, "collect_stats", fake_collect)

    csv_path = fetch_je_stats._materialise_stats(course_dir, "R1", "C1")

    assert csv_path == course_dir / "R1C1_je.csv"
    assert (course_dir / "normalized_h5_je.csv").exists()

    stats_path = course_dir / "stats_je.json"
    payload = json.loads(stats_path.read_text(encoding="utf-8"))
    assert payload["coverage"] == pytest.approx(87.5)
    assert payload["1"] == {"j_win": 12.3, "e_win": 45.6}

    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines == ["num,nom,j_rate,e_rate", "1,Alpha,12.3,45.6"]


def test_fetch_je_stats_materialise_persists_placeholder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    course_dir = tmp_path / "R1C1"
    course_dir.mkdir()
    (course_dir / "normalized_h5.json").write_text(
        json.dumps({"course_id": "123"}),
        encoding="utf-8",
    )

    def failing_collect(*_args, **_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(fetch_je_stats, "collect_stats", failing_collect)

    csv_path = fetch_je_stats._materialise_stats(course_dir, "R1", "C1")

    assert csv_path == course_dir / "R1C1_je.csv"

    stats_path = course_dir / "stats_je.json"
    payload = json.loads(stats_path.read_text(encoding="utf-8"))
    assert payload == {"coverage": 0, "ok": 0}

    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines == ["num,nom,j_rate,e_rate,ok", ",,,,0"]

    legacy_path = course_dir / "normalized_h5_je.csv"
    assert legacy_path.exists()
    assert legacy_path.read_text(encoding="utf-8").splitlines() == [
        "num,nom,j_rate,e_rate,ok",
        ",,,,0",
    ]


def test_fetch_je_chrono_wrapper_uses_snapshot_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    course_dir = tmp_path / "R1C1"
    course_dir.mkdir()
    snapshot = tmp_path / "R1C1_H-5.json"
    snapshot.write_text(
        json.dumps({"meta": {"course_dir": str(course_dir)}}),
        encoding="utf-8",
    )

    calls: list[tuple[Path, str, str]] = []

    def fake_materialise(directory: Path, reunion: str, course: str) -> Path:
        calls.append((directory, reunion, course))
        return directory / f"{reunion}{course}_chronos.csv"

    monkeypatch.setattr(fetch_je_chrono, "_materialise_chronos", fake_materialise)

    csv_path = fetch_je_chrono.enrich_from_snapshot(snapshot, "r1", "c1")

    assert csv_path == course_dir / "R1C1_chronos.csv"
    assert calls == [(course_dir, "R1", "C1")]


def test_fetch_je_chrono_wrapper_accepts_snapshot_h5(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    course_dir = tmp_path / "R1C1"
    course_dir.mkdir()
    snapshot = tmp_path / "snapshot_H5.json"
    snapshot.write_text(
        json.dumps({"meta": {"course_dir": str(course_dir)}}),
        encoding="utf-8",
    )

    calls: list[tuple[Path, str, str]] = []

    def fake_materialise(directory: Path, reunion: str, course: str) -> Path:
        calls.append((directory, reunion, course))
        return directory / f"{reunion}{course}_chronos.csv"

    monkeypatch.setattr(fetch_je_chrono, "_materialise_chronos", fake_materialise)

    csv_path = fetch_je_chrono.enrich_from_snapshot(snapshot, "r1", "c1")

    assert csv_path == course_dir / "R1C1_chronos.csv"
    assert calls == [(course_dir, "R1", "C1")]


def test_fetch_je_chrono_wrapper_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    course_dir = tmp_path / "R1C1"
    course_dir.mkdir()
    snapshot = tmp_path / "R1C1_H-5.json"
    snapshot.write_text(
        json.dumps({"meta": {"course_dir": str(course_dir)}}),
        encoding="utf-8",
    )

    csv_path = course_dir / "R1C1_chronos.csv"
    csv_path.write_text("num,chrono\n", encoding="utf-8")

    def forbidden(*_args, **_kwargs):  # pragma: no cover - defensive guard
        raise AssertionError("_materialise_chronos should not be called when CSV exists")
    
    monkeypatch.setattr(fetch_je_chrono, "_materialise_chronos", forbidden)

    result = fetch_je_chrono.enrich_from_snapshot(snapshot, "R1", "C1")

    assert result == csv_path


def test_fetch_je_chrono_materialise_builds_csv(tmp_path: Path) -> None:
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

    csv_path = fetch_je_chrono._materialise_chronos(course_dir, "R1", "C1")

    assert csv_path == course_dir / "R1C1_chronos.csv"
    assert (course_dir / "chronos.csv").exists()
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines == ["num,chrono", "1,1.12", "2,1.18"]


def test_fetch_je_chrono_materialise_requires_snapshot(tmp_path: Path) -> None:
    course_dir = tmp_path / "R1C1"
    course_dir.mkdir()

    with pytest.raises(RuntimeError, match="snapshot-missing"):
        fetch_je_chrono._materialise_chronos(course_dir, "R1", "C1")


