from __future__ import annotations

import json
from pathlib import Path

import pytest

from hippique.analytics import (
    AllocationPlan,
    RaceMetrics,
    compute_allocation_plan,
    load_analysis_reports,
)


@pytest.fixture()
def sample_reports(tmp_path: Path) -> list[RaceMetrics]:
    base = tmp_path / "reports"
    base.mkdir()
    payloads = [
        {
            "race_id": "R1C1",
            "metrics": {
                "total_stake": 5.0,
                "ev": {"ev": 1.5, "roi": 0.30, "risk_of_ruin": 0.02},
            },
        },
        {
            "race_id": "R2C4",
            "metrics": {
                "total_stake": 5.0,
                "ev": {"ev": 0.8, "roi": 0.16, "risk_of_ruin": 0.01},
            },
        },
        {
            "race_id": "R3C2",
            "metrics": {
                "total_stake": 5.0,
                "ev": {"ev": -0.4, "roi": -0.08, "risk_of_ruin": 0.02},
            },
        },
    ]
    files = []
    for payload in payloads:
        file_path = base / f"{payload['race_id']}" / "analysis.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(payload), encoding="utf-8")
        files.append(file_path)
    reports = load_analysis_reports(files)
    assert len(reports) == 2
    return reports


def test_compute_allocation_plan_prioritises_high_ev(sample_reports: list[RaceMetrics]) -> None:
    plan = compute_allocation_plan(sample_reports, bankroll=20.0, target_ror=0.05, min_roi=0.10)
    assert isinstance(plan, AllocationPlan)
    assert pytest.approx(plan.bankroll) == 20.0
    assert plan.expected_return > 0
    assert plan.expected_roi > 0
    assert len(plan.allocations) == 2
    alloc_map = {alloc.race.race_id: alloc for alloc in plan.allocations}
    assert alloc_map["R1C1"].recommended_stake > alloc_map["R2C4"].recommended_stake
    assert alloc_map["R1C1"].scaled_roi >= alloc_map["R2C4"].scaled_roi
    assert plan.aggregate_risk <= 0.99


def test_plan_serialisation_round_trip(sample_reports: list[RaceMetrics]) -> None:
    plan = compute_allocation_plan(sample_reports, bankroll=10.0, target_ror=0.05, min_roi=0.10)
    data = plan.as_dict()
    assert data["bankroll"] == 10.0
    assert data["expected_return"] == pytest.approx(plan.expected_return)
    assert data["expected_roi"] == pytest.approx(plan.expected_roi)
    assert len(data["allocations"]) == len(plan.allocations)
    first = data["allocations"][0]
    assert {"race_id", "stake", "expected_ev", "expected_roi", "risk_of_ruin"}.issubset(first)


def test_allocation_plan_requires_positive_bankroll(sample_reports: list[RaceMetrics]) -> None:
    with pytest.raises(ValueError):
        compute_allocation_plan(sample_reports, bankroll=0.0)
