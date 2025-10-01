from __future__ import annotations

import logging
import json
import subprocess
import sys
from pathlib import Path

import pytest

import fetch_je_chrono
import fetch_je_stats


def test_fetch_je_stats_wrapper_invokes_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out_dir = tmp_path / "R1C1"
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        assert check is False
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(fetch_je_stats.subprocess, "run", fake_run)

    csv_path = fetch_je_stats.enrich_from_snapshot(out_dir, "R1", "C1")

    assert csv_path == out_dir / "R1C1_je.csv"
    assert out_dir.is_dir()

    assert calls == [
        [
            sys.executable,
            str(Path(fetch_je_stats.__file__).resolve()),
            "--out",
            str(out_dir),
            "--reunion",
            "R1",
            "--course",
            "C1",
        ]
    ]


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


def test_fetch_je_stats_materialise_propagates_failure(
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

    with pytest.raises(RuntimeError, match="network down"):
        fetch_je_stats._materialise_stats(course_dir, "R1", "C1")


def test_fetch_je_stats_wrapper_logs_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    out_dir = tmp_path / "R1C1"

    def fake_run(cmd: list[str], check: bool) -> subprocess.CompletedProcess[str]:
        assert check is False
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(fetch_je_stats.subprocess, "run", fake_run)

    with caplog.at_level(logging.WARNING):
        csv_path = fetch_je_stats.enrich_from_snapshot(out_dir, "R1", "C1")

    assert csv_path == out_dir / "R1C1_je.csv"
    assert out_dir.is_dir()
    assert any(
        "fetch_je_stats CLI failed for R1C1 (returncode=1)" in message
        for message in caplog.messages
    )


def test_fetch_je_chrono_wrapper_invokes_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out_dir = tmp_path / "R1C1"
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], check: bool) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        assert check is False
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(fetch_je_chrono.subprocess, "run", fake_run)

    csv_path = fetch_je_chrono.enrich_from_snapshot(
        out_dir,
        "R1",
        "C1",
    )

    expected_command = [
        sys.executable,
        str(Path(fetch_je_chrono.__file__).resolve()),
        "--out",
        str(out_dir),
        "--reunion",
        "R1",
        "--course",
        "C1",
    ]
    assert csv_path == out_dir / "R1C1_chronos.csv"
    assert out_dir.is_dir()

    assert calls == [expected_command]


def test_fetch_je_chrono_wrapper_logs_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    out_dir = tmp_path / "R1C1"

    def fake_run(cmd: list[str], check: bool) -> subprocess.CompletedProcess[str]:
        assert check is False
        return subprocess.CompletedProcess(cmd, 2)

    monkeypatch.setattr(fetch_je_chrono.subprocess, "run", fake_run)

    with caplog.at_level(logging.WARNING):
        csv_path = fetch_je_chrono.enrich_from_snapshot(out_dir, "R1", "C1")

    assert csv_path == out_dir / "R1C1_chronos.csv"
    assert out_dir.is_dir()
    assert any(
        "fetch_je_chrono CLI failed for R1C1 (returncode=2)" in message
        for message in caplog.messages
    )


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


