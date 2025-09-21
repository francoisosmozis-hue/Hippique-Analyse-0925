from __future__ import annotations

import datetime as dt
import importlib
import json
import sys

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


def test_single_race_h5_creates_snapshot_and_analysis(tmp_path, monkeypatch, runner_chain_module):
    _stub_analysis(monkeypatch, runner_chain_module)

    snap_dir = tmp_path / "snapshots"
    analysis_dir = tmp_path / "analyses"

    _invoke(
        runner_chain_module,
        monkeypatch,
        [
            "--reunion",
            "R1",
            "--course",
            "C2",
            "--phase",
            "H5",
            "--snap-dir",
            str(snap_dir),
            "--analysis-dir",
            str(analysis_dir),
        ],
    )

    race_dir = snap_dir / "R1C2"
    assert (race_dir / "snapshot_H5.json").exists()
    assert (analysis_dir / "R1C2" / "analysis.json").exists()


def test_single_race_h30_only_writes_snapshot(tmp_path, monkeypatch, runner_chain_module):
    _stub_analysis(monkeypatch, runner_chain_module)

    snap_dir = tmp_path / "snapshots"
    analysis_dir = tmp_path / "analyses"

    _invoke(
        runner_chain_module,
        monkeypatch,
        [
            "--reunion",
            "R1",
            "--course",
            "C2",
            "--phase",
            "H30",
            "--snap-dir",
            str(snap_dir),
            "--analysis-dir",
            str(analysis_dir),
        ],
    )

    race_dir = snap_dir / "R1C2"
    assert (race_dir / "snapshot_H30.json").exists()
    assert not (analysis_dir / "R1C2" / "analysis.json").exists()


def test_planning_mode_remains_functional(tmp_path, monkeypatch, runner_chain_module):
    _stub_analysis(monkeypatch, runner_chain_module)

    base = tmp_path / "planning"
    base.mkdir()
    planning_path = base / "plan.json"

    reference_now = dt.datetime(2024, 1, 1, 12, 0, 0)
    start_time = reference_now + dt.timedelta(minutes=5)
    planning_path.write_text(json.dumps([{"id": "R1C2", "start": start_time.isoformat()}]), encoding="utf-8")

    class FixedDateTime(dt.datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is not None:
                return reference_now.replace(tzinfo=tz)
            return reference_now

    monkeypatch.setattr(runner_chain_module.dt, "datetime", FixedDateTime)

    snap_dir = tmp_path / "snapshots"
    analysis_dir = tmp_path / "analyses"

    _invoke(
        runner_chain_module,
        monkeypatch,
        [
            "--planning",
            str(planning_path),
            "--snap-dir",
            str(snap_dir),
            "--analysis-dir",
            str(analysis_dir),
        ],
    )

    assert (snap_dir / "R1C2" / "snapshot_H5.json").exists()
    assert (analysis_dir / "R1C2" / "analysis.json").exists()
