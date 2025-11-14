import json
from pathlib import Path

import pytest

from src.overround import compute_overround_place
import pipeline_run
from src.hippique_orchestrator.pipeline_run import _load_simulate_ev
from tests.test_pipeline_exotics_filters import (
    _prepare_stubs,
    _write_inputs,
)
from tests.test_pipeline_smoke import partants_sample


def test_estimate_overround_place_from_runners() -> None:
    runners = [
        {"odds_place": 2.0},
        {"odds_place": 2.5},
        {"odds_place": 3.5},
    ]
    expected = sum(1.0 / runner["odds_place"] for runner in runners)
    value = compute_overround_place([r["odds_place"] for r in runners])
    assert value == pytest.approx(expected)


def test_pipeline_blocks_combos_when_place_overround_high(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_stats = {
        "status": "ok",
        "ev_ratio": 0.65,
        "payout_expected": 25.0,
        "roi": 0.4,
        "sharpe": 0.5,
    }

    captured_log, _ = _prepare_stubs(
        monkeypatch,
        eval_stats,
        overround_cap=1.30,
    )

    partants_override = partants_sample()
    high_place = [
        {"id": "1", "name": "A", "odds_place": 2.0},
        {"id": "2", "name": "B", "odds_place": 2.0},
        {"id": "3", "name": "C", "odds_place": 2.0},
    ]
    market_override = {
        "slots_place": 3,
        "horses": [
            {"id": entry["id"], "odds": 2.5, "odds_place": entry["odds_place"]}
            for entry in high_place
        ],
    }
    partants_override.update({"runners": high_place, "market": market_override})

    inputs = _write_inputs(tmp_path, partants_override=partants_override)

    outdir = tmp_path / "out"
    result = pipeline_run.run_pipeline(
        h30=str(inputs["h30"]),
        h5=str(inputs["h5"]),
        stats_je=str(inputs["stats"]),
        partants=str(inputs["partants"]),
        gpi=str(inputs["gpi"]),
        outdir=str(outdir),
        calibration="config/payout_calibration.yaml",
    )

    metrics = result["metrics"]
    assert metrics["status"] == "abstain"
    assert metrics["overround"] > 1.30
    assert "overround_above_threshold" in metrics["abstention_reasons"]

    combo_meta = metrics.get("combo", {})
    decision = combo_meta.get("decision", "")
    assert isinstance(decision, str) and decision.startswith("reject")
    assert "overround_above_threshold" in combo_meta.get("notes", [])

    meta = json.loads((Path(result["outdir"]) / "p_finale.json").read_text())
    assert not meta.get("tickets"), "no tickets should be emitted on high overround"
    assert captured_log, "journaux should receive entries"
