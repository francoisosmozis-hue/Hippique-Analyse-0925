# tests/test_pipeline_run.py

import pytest

from hippique_orchestrator.pipeline_run import generate_tickets


@pytest.fixture
def gpi_config():
    """Provides a default GPI configuration for tests."""
    return {
        "budget_cap_eur": 5.0,
        "overround_max_exotics": 1.25,
        "roi_min_sp": 0.1,
        "roi_min_global": 0.15,
        "ev_min_combo": 0.2,
        "payout_min_combo": 10.0,
        "max_vol_per_horse": 0.6,
        "tickets": {
            "sp_dutching": {
                "budget_ratio": 0.6,
                "legs_min": 2,
                "legs_max": 3,
                "odds_range": [2.0, 20.0],
                "kelly_frac": 0.25,
            },
            "exotics": {
                "type": "TRIO",
                "stake_eur": 2.0,
                "legs_count": 4,
            },
        },
    }

@pytest.fixture
def calibration_data():
    """Provides default calibration data."""
    return {
        "version": 1,
        "exotic_weights": {
            "TRIO": 1.0,
            "ZE4": 1.0,
            "CPL": 1.0,
        }
    }

@pytest.mark.unit
def test_generate_tickets_no_runners(gpi_config, calibration_data):
    """Test that the function abstains when there are no runners."""
    snapshot = {"runners": []}
    result = generate_tickets(snapshot, gpi_config, 5.0, calibration_data)
    assert "Abstain: No runners found" in result["gpi_decision"]
    assert result["tickets"] == []


@pytest.mark.unit
def test_abstain_on_high_overround(gpi_config, calibration_data):
    """
    Tests that exotic bets are disallowed and the function abstains if overround is too high
    and no other valid bets (like SP) are found.
    """
    snapshot = {
        "market": {"overround_place": 1.30},
        "runners": [
            {"num": 1, "p_place": 0.1, "cote": 10.0, "volatility": 0.5},
            {"num": 2, "p_place": 0.1, "cote": 10.0, "volatility": 0.5},
            {"num": 3, "p_place": 0.1, "cote": 10.0, "volatility": 0.5},
            {"num": 4, "p_place": 0.1, "cote": 10.0, "volatility": 0.5},
        ]
    }
    gpi_config["overround_max_exotics"] = 1.25

    result = generate_tickets(snapshot, gpi_config, 5.0, calibration_data)

    assert "Abstain: No valid tickets found" in result["gpi_decision"]
    assert result["tickets"] == []


@pytest.mark.unit
def test_abstain_on_low_global_roi(gpi_config, calibration_data):
    """
    Tests that the function abstains if SP tickets are generated but their
    combined ROI is below the global minimum.
    """
    snapshot = {
        "market": {"overround_place": 1.10},
        "runners": [
            {"num": 1, "p_place": 0.4, "cote": 3.0, "volatility": 0.5, "roi_sp": 0.2},
            {"num": 2, "p_place": 0.3, "cote": 4.0, "volatility": 0.5, "roi_sp": 0.2},
            {"num": 3, "p_place": 0.1, "cote": 10.0, "volatility": 0.5, "roi_sp": 0.0},
            {"num": 4, "p_place": 0.1, "cote": 10.0, "volatility": 0.5, "roi_sp": 0.0},
        ]
    }
    gpi_config["roi_min_global"] = 0.25
    gpi_config["roi_min_sp"] = 0.1

    result = generate_tickets(snapshot, gpi_config, 5.0, calibration_data)

    assert "Abstain: Global ROI" in result["gpi_decision"]
    assert result["tickets"] == []


@pytest.mark.unit
def test_correct_kelly_staking(gpi_config, calibration_data):
    """
    Tests that the Kelly Criterion is applied correctly for SP dutching stakes.
    """
    snapshot = {
        "market": {"overround_place": 1.10},
        "discipline": "Trot",
        "runners": [
            {"num": 1, "p_place": 0.6, "cote": 2.0, "volatility": 0.3, "roi_sp": 0.2},
            {"num": 2, "p_place": 0.4, "cote": 3.0, "volatility": 0.4, "roi_sp": 0.2},
            {"num": 3, "p_place": 0.1, "cote": 10.0, "volatility": 0.5, "roi_sp": 0.0},
        ]
    }
    gpi_config["roi_min_sp"] = 0.1
    gpi_config["roi_min_global"] = 0.1

    result = generate_tickets(snapshot, gpi_config, 5.0, calibration_data)

    assert result["gpi_decision"] == "Play"
    assert len(result["tickets"]) == 1
    sp_ticket = result["tickets"][0]
    assert sp_ticket["type"] == "SP_DUTCHING"

    assert sp_ticket["stake"] == pytest.approx(3.0, abs=0.1)
    details = sp_ticket["details"]
    assert details[1] > details[2]


@pytest.mark.unit
def test_combo_bet_triggered_on_success(gpi_config, calibration_data, mocker):
    """
    Tests that a combo bet is created when all guardrails pass.
    """
    mocker.patch(
        "hippique_orchestrator.pipeline_run.evaluate_combo",
        return_value={"status": "ok", "roi": 0.5, "payout_expected": 25.0}
    )

    snapshot = {
        "market": {"overround_place": 1.10},
        "discipline": "Trot",
        "runners": [
            {"num": 1, "p_place": 0.6, "cote": 2.0, "volatility": 0.3, "roi_sp": 0.2},
            {"num": 2, "p_place": 0.4, "cote": 3.0, "volatility": 0.4, "roi_sp": 0.2},
            {"num": 3, "p_place": 0.2, "cote": 5.0, "volatility": 0.5, "roi_sp": 0.0},
            {"num": 4, "p_place": 0.1, "cote": 10.0, "volatility": 0.5, "roi_sp": 0.0},
        ]
    }
    gpi_config["roi_min_global"] = 0.1

    result = generate_tickets(snapshot, gpi_config, 5.0, calibration_data)

    assert result["gpi_decision"] == "Play"
    assert len(result["tickets"]) == 2  # SP Dutching + Combo

    combo_ticket = next(t for t in result["tickets"] if t["type"] == "TRIO")
    assert combo_ticket is not None
    assert combo_ticket["stake"] == 2.0
    assert combo_ticket["roi_est"] == 0.5
    assert combo_ticket["payout_est"] == 25.0

@pytest.mark.unit
def test_combo_bet_blocked_without_calibration(gpi_config, mocker):
    """
    Tests that a combo bet is NOT created if calibration data is missing.
    """
    mocker.patch(
        "hippique_orchestrator.pipeline_run.evaluate_combo",
        return_value={"status": "ok", "roi": 0.5, "payout_expected": 25.0}
    )

    snapshot = {
        "market": {"overround_place": 1.10},
        "discipline": "Trot",
        "runners": [
            {"num": 1, "p_place": 0.6, "cote": 2.0, "volatility": 0.3, "roi_sp": 0.2},
            {"num": 2, "p_place": 0.4, "cote": 3.0, "volatility": 0.4, "roi_sp": 0.2},
        ]
    }
    gpi_config["roi_min_global"] = 0.1

    result = generate_tickets(snapshot, gpi_config, 5.0, calibration_data={})

    # The system should play the SP ticket but abstain from the combo
    assert result["gpi_decision"] == "Play"
    assert len(result["tickets"]) == 1
    assert result["tickets"][0]["type"] == "SP_DUTCHING"
