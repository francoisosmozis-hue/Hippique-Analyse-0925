import pytest
import json
from pathlib import Path
from hippique.analytics.roi_rebalancer import compute_allocation_plan, AllocationPlan, RaceMetrics, Allocation, _score, _scale_risk, load_analysis_reports, _extract_metrics

def test_compute_allocation_plan_empty_tickets():
    plan = compute_allocation_plan(races=[], bankroll=100)
    assert plan.bankroll == 100
    assert not plan.allocations

def test_compute_allocation_plan_no_positive_ev_tickets():
    races = [
        RaceMetrics(race_id="t1", stake=10, ev=-1, roi=-0.1, risk_of_ruin=0.5),
        RaceMetrics(race_id="t2", stake=10, ev=-5, roi=-0.5, risk_of_ruin=0.2),
    ]
    plan = compute_allocation_plan(races=races, bankroll=100)
    assert plan.bankroll == 100
    assert not plan.allocations

def test_compute_allocation_plan_stake_cap():
    races = [
        RaceMetrics(race_id="t1", stake=10, ev=5, roi=0.5, risk_of_ruin=0.8),
    ]
    plan = compute_allocation_plan(races=races, bankroll=100)
    assert plan.allocations[0].recommended_stake == 100.0

def test_compute_allocation_plan_invalid_ticket_format():
    races = [
        {"id": "t1", "EV_ratio": 0.5},  # Missing p_success and payout_expected
    ]
    with pytest.raises(AttributeError):
        compute_allocation_plan(races=races, bankroll=100)

def test_allocation_plan_serialization():
    race = RaceMetrics(race_id="t1", stake=10.0, ev=5.0, roi=0.5, risk_of_ruin=0.1)
    allocation = Allocation(
        race=race,
        recommended_stake=10.0,
        scaled_ev=5.0,
        scaled_roi=0.5,
        scaled_risk=0.1,
    )
    plan = AllocationPlan(allocations=[allocation], bankroll=100.0, expected_return=5.0, aggregate_risk=0.1)
    serialized = plan.as_dict()
    assert serialized["bankroll"] == 100.0
    assert len(serialized["allocations"]) == 1
    assert serialized["allocations"][0]["race_id"] == "t1"

def test_compute_allocation_plan_zero_bankroll():
    races = [
        RaceMetrics(race_id="t1", stake=10, ev=5, roi=0.5, risk_of_ruin=0.8),
    ]
    with pytest.raises(ValueError):
        compute_allocation_plan(races=races, bankroll=0)

def test_extract_metrics_nominal():
    payload = {
        "metrics": {
            "total_stake": 100,
            "roi": 0.2,
            "ev": 20,
            "risk_of_ruin": 0.1,
            "clv": 0.5
        }
    }
    stake, ev, roi, risk, clv = _extract_metrics(payload)
    assert stake == 100
    assert ev == 20
    assert roi == 0.2
    assert risk == 0.1
    assert clv == 0.5

def test_extract_metrics_missing_metrics_block():
    payload = {"budget": 100}
    stake, ev, roi, risk, clv = _extract_metrics(payload)
    assert stake == 100
    assert ev == 0.0
    assert roi == 0.0
    assert risk == 0.0
    assert clv is None

def test_extract_metrics_ev_block():
    payload = {
        "metrics": {
            "ev": {
                "roi": 0.25,
                "ev": 25,
                "risk_of_ruin": 0.15
            }
        },
        "budget": 100
    }
    stake, ev, roi, risk, clv = _extract_metrics(payload)
    assert stake == 100
    assert ev == 25
    assert roi == 0.25
    assert risk == 0.15
    assert clv is None

def test_extract_metrics_calculates_ev_from_roi_and_stake():
    payload = {
        "metrics": {
            "total_stake": 50,
            "roi": 0.3
        }
    }
    stake, ev, roi, risk, clv = _extract_metrics(payload)
    assert stake == 50
    assert ev == 15.0  # 50 * 0.3
    assert roi == 0.3
    assert risk == 0.0
    assert clv is None

def test_extract_metrics_with_invalid_values():
    payload = {
        "metrics": {
            "total_stake": "invalid",
            "roi": "invalid",
            "ev": "invalid",
            "risk_of_ruin": "invalid",
            "clv": "invalid"
        }
    }
    stake, ev, roi, risk, clv = _extract_metrics(payload)
    assert stake == 0.0
    assert ev == 0.0
    assert roi == 0.0
    assert risk == 0.0
    assert clv is None

@pytest.fixture
def analysis_files(tmp_path):
    d = tmp_path / "analysis"
    d.mkdir()
    p1 = d / "race1"
    p1.mkdir()
    (p1 / "analysis.json").write_text(json.dumps({
        "race_id": "R1C1",
        "metrics": {
            "total_stake": 10,
            "ev": 1,
            "roi": 0.1,
            "risk_of_ruin": 0.05
        }
    }))
    p2 = d / "race2"
    p2.mkdir()
    (p2 / "analysis.json").write_text(json.dumps({
        "race_id": "R1C2",
        "metrics": {
            "total_stake": 20,
            "ev": 5,
            "roi": 0.25,
            "risk_of_ruin": 0.1
        }
    }))
    # Malformed file
    p3 = d / "race3"
    p3.mkdir()
    (p3 / "analysis.json").write_text("not a json")
    
    # File with no metrics
    p4 = d / "race4"
    p4.mkdir()
    (p4 / "analysis.json").write_text(json.dumps({"race_id": "R1C4"}))

    return d

def test_load_analysis_reports_from_dir(analysis_files):
    reports = sorted(load_analysis_reports([analysis_files]), key=lambda r: r.race_id)
    assert len(reports) == 2
    assert reports[0].race_id == "R1C1"
    assert reports[1].race_id == "R1C2"
    assert reports[0].stake == 10
    assert reports[1].ev == 5

def test_load_analysis_reports_with_direct_file_paths(analysis_files):
    paths = [
        analysis_files / "race1" / "analysis.json",
        analysis_files / "race2" / "analysis.json",
    ]
    reports = load_analysis_reports(paths)
    assert len(reports) == 2

def test_load_analysis_reports_skips_malformed_files(analysis_files):
    reports = load_analysis_reports([analysis_files])
    assert len(reports) == 2

def test_load_analysis_reports_skips_files_with_no_metrics(analysis_files):
    reports = load_analysis_reports([analysis_files])
    assert len(reports) == 2

def test_load_analysis_reports_with_non_existent_path():
    reports = load_analysis_reports([Path("non_existent_dir")])
    assert len(reports) == 0

def test_score_basic():
    race = RaceMetrics(race_id="r1", stake=10, ev=1, roi=0.1, risk_of_ruin=0.05)
    assert _score(race, target_ror=0.05) > 0

def test_score_zero_ev():
    race = RaceMetrics(race_id="r1", stake=10, ev=0, roi=0.0, risk_of_ruin=0.05)
    assert _score(race, target_ror=0.05) == 0

def test_score_high_risk():
    race = RaceMetrics(race_id="r1", stake=10, ev=1, roi=0.1, risk_of_ruin=0.01) # Lower initial risk
    assert _score(race, target_ror=0.05) > _score(race, target_ror=0.1) # Higher target_ror should lead to lower score (higher risk)

def test_scale_risk_basic():
    race = RaceMetrics(race_id="r1", stake=10, ev=1, roi=0.1, risk_of_ruin=0.05)
    assert _scale_risk(race, target_stake=20) > race.risk_of_ruin

def test_scale_risk_zero_stake():
    race = RaceMetrics(race_id="r1", stake=0, ev=0, roi=0.0, risk_of_ruin=0.05)
    assert _scale_risk(race, target_stake=20) == race.safe_risk # Returns safe_risk if original stake is zero

def test_scale_risk_zero_target_stake():
    race = RaceMetrics(race_id="r1", stake=10, ev=1, roi=0.1, risk_of_ruin=0.05)
    assert _scale_risk(race, target_stake=0) == 0.0 # Returns 0 if target stake is zero

def test_scale_risk_clamps_max():
    race = RaceMetrics(race_id="r1", stake=10, ev=1, roi=0.1, risk_of_ruin=0.05)
    assert _scale_risk(race, target_stake=1000) == 0.99 # Should be clamped at 0.99