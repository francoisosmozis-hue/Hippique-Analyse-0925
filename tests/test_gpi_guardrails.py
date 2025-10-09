"""Regression tests covering GPI guardrail helpers.

The scenarios mirror the safeguards enforced by the live automation:

* Exotic validation should gracefully abstain with an ``insufficient_data``
  status when the payout calibration file is unavailable.
* Runner-chain market filtering must reject exotic tickets when the observed
  overround breaches the configured 1.30 ceiling.
* ``p_finale_export`` should faithfully propagate scoring artefacts, even when
  chronos are missing (``ok_chrono == ""``).
"""

from __future__ import annotations

import json
from pathlib import Path

import p_finale_export
from scripts import runner_chain


def test_validate_exotics_missing_calibration_flags_insufficient_data(
    monkeypatch, tmp_path: Path
) -> None:
    """Validate that missing calibration triggers an ``insufficient_data`` status."""

    missing_calibration = tmp_path / "payout_calibration.yaml"

    def _fail_if_called(*_a, **_k):  # pragma: no cover - defensive guard
        raise AssertionError("evaluate_combo should not be called without calibration")

    monkeypatch.setattr(runner_chain, "evaluate_combo", _fail_if_called)

    tickets, info = runner_chain.validate_exotics_with_simwrapper(
        [[{"id": "combo", "p": 0.5, "odds": 2.0, "stake": 1.0}]],
        bankroll=10,
        calibration=missing_calibration,
    )

    assert tickets == []
    assert info["status"] == "insufficient_data"
    assert info["decision"] == "reject:calibration_missing"
    assert info["flags"]["combo"] is False
    assert "calibration_missing" in info["notes"]


def test_filter_exotics_rejects_when_overround_exceeds_cap() -> None:
    """Markets whose overround exceeds 1.30 should discard exotic tickets."""

    market = {"overround": 1.35}
    exotics = [[{"id": "combo", "p": 0.5, "odds": 3.0, "stake": 1.0}]]

    filtered = runner_chain.filter_exotics_by_overround(
        exotics,
        overround=market["overround"],
        overround_max=1.30,
        discipline="Plat",
        partants=14,
    )

    assert filtered == []


def test_p_finale_export_preserves_scores_when_chrono_missing(tmp_path: Path) -> None:
    """The export helper must not mutate runner scores with missing chronos."""

    scores = [{"id": "R1C1-1", "score": 0.42, "ok_chrono": ""}]
    p_finale = {
        "meta": {"rc": "R1C1", "date": "2024-05-01", "discipline": "Plat"},
        "tickets": [{"id": "CP1", "stake": 1.5}],
        "ev": {"global": 0.55, "scores": scores},
    }

    outdir = tmp_path / "exports"
    p_finale_export.export(outdir, p_finale)

    saved = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))

    assert saved["ev"]["scores"] == scores
    assert saved["ev"]["scores"][0]["ok_chrono"] == ""
    assert saved["ev"]["scores"][0]["score"] == 0.42
