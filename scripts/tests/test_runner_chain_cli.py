from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def runner_chain_module(monkeypatch):
    """Return a freshly reloaded ``scripts.runner_chain`` module."""

    monkeypatch.setenv("USE_GCS", "0")
    if "scripts.runner_chain" in sys.modules:
        module = sys.modules["scripts.runner_chain"]
    else:  # pragma: no cover - defensive branch
        import scripts.runner_chain as module  # type: ignore[no-redef]
    module = importlib.reload(sys.modules.get("scripts.runner_chain", module))
    return module


def _stub_analysis(monkeypatch, module):
    monkeypatch.setattr(
        module,
        "simulate_ev_batch",
        lambda tickets, bankroll: {"ev": 0.4, "roi": 0.3, "green": True},
    )
    monkeypatch.setattr(module, "validate_ev", lambda *_, **__: True)
    

def _invoke(module, monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["runner_chain.py", *args])
    module.main()


def _create_test_env(
    tmp_path: Path,
    rc: str,
    phase: str,
    with_snapshot: bool = True,
    with_csv: bool = True,
) -> Path:
    course_dir = tmp_path / rc
    course_dir.mkdir(parents=True, exist_ok=True)

    if with_snapshot:
        snapshot_payload = {
            "payload": {
                "course_id": "123456",
                "reunion": "R1",
                "course": "C2",
                "start_time": "2024-01-01T12:05:00",
            }
        }
        (course_dir / f"snapshot_{phase}.json").write_text(json.dumps(snapshot_payload))

    if with_csv:
        (course_dir / "je_stats.csv").write_text("p,odds\n0.5,2.0")
        (course_dir / "chronos.csv").write_text("time,value\n10,1")

    return course_dir


def test_single_race_h5_creates_analysis(tmp_path, monkeypatch, runner_chain_module):
    _stub_analysis(monkeypatch, runner_chain_module)
    course_dir = _create_test_env(tmp_path, "R1C2", "H5")

    monkeypatch.setattr(
        runner_chain_module.ofz, "fetch_race_snapshot", lambda *_, **__: {}
    )

    _invoke(
        runner_chain_module,
        monkeypatch,
        [
            "--analysis-dir-path",
            str(course_dir),
            "--output",
            str(tmp_path),
        ],
    )

    assert (course_dir / "analysis.json").exists()


def test_missing_calibration_disables_combos(
    tmp_path, monkeypatch, runner_chain_module
):
    calls: list[tuple] = []

    def fake_simulation(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ev": 0.4, "roi": 0.3, "green": True}

    monkeypatch.setattr(runner_chain_module, "simulate_ev_batch", fake_simulation)
    monkeypatch.setattr(runner_chain_module, "validate_ev", lambda *_, **__: True)

    monkeypatch.setattr(
        runner_chain_module.ofz, "fetch_race_snapshot", lambda *_, **__: {}
    )
    
    course_dir = _create_test_env(tmp_path, "R1C2", "H5")
    calibration_path = tmp_path / "missing_calibration.yaml"

    _invoke(
        runner_chain_module,
        monkeypatch,
        [
            "--analysis-dir-path",
            str(course_dir),
            "--calibration",
            str(calibration_path),
            "--output",
            str(tmp_path),
        ],
    )
    analysis_file = course_dir / "analysis.json"
    payload = json.loads(analysis_file.read_text(encoding="utf-8"))

    assert payload["status"] == "insufficient_data"
    assert "calibration_missing" in payload["notes"]


def test_single_race_h30_only_writes_snapshot(
    tmp_path, monkeypatch, runner_chain_module
):
    _stub_analysis(monkeypatch, runner_chain_module)
    course_dir = _create_test_env(tmp_path, "R1C2", "H30")

    # Mock snapshot fetch to avoid network calls
    monkeypatch.setattr(
        runner_chain_module.ofz, "fetch_race_snapshot", lambda *_, **__: {}
    )

    _invoke(
        runner_chain_module,
        monkeypatch,
        [
            "--analysis-dir-path",
            str(course_dir),
            "--output",
            str(tmp_path),
        ],
    )
    assert (course_dir / "snapshot_H30.json").exists()
    assert not (course_dir / "analysis_H5.json").exists()


def test_missing_snapshot_file_exits(
    tmp_path, monkeypatch, runner_chain_module, capsys
):
    course_dir = _create_test_env(tmp_path, "R1C2", "H5", with_snapshot=False)

    with pytest.raises(SystemExit) as excinfo:
        _invoke(
            runner_chain_module,
            monkeypatch,
                    [
                        "--analysis-dir-path",
                        str(course_dir),
                        "--output",
                        str(tmp_path),
                    ],        )
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "Snapshot file not found" in err


def test_missing_analysis_csv_aborts(tmp_path, monkeypatch, runner_chain_module):
    _stub_analysis(monkeypatch, runner_chain_module)
    course_dir = _create_test_env(tmp_path, "R1C2", "H5", with_csv=False)

    monkeypatch.setattr(
        runner_chain_module.ofz, "fetch_race_snapshot", lambda *_, **__: {}
    )

    _invoke(
        runner_chain_module,
        monkeypatch,
        [
            "--analysis-dir-path",
            str(course_dir),
            "--output",
            str(tmp_path),
        ],
    )

    analysis_file = course_dir / "analysis.json"
    payload = json.loads(analysis_file.read_text(encoding="utf-8"))
    assert payload["status"] == "aborted"
    assert "data_missing" in payload["reasons"]
