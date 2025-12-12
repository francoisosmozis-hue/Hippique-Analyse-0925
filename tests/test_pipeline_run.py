import pytest
from pytest_mock import MockerFixture

from hippique_orchestrator.pipeline_run import generate_tickets


@pytest.fixture
def mock_gpi_config() -> dict:
    """Provides a basic mock GPI configuration."""
    return {
        "roi_min_sp": 0.20,
        "roi_min_global": 0.25,
        "overround_max_exotics": 1.30,
        "weights": {},
        "tickets": {
            "sp_dutching": {
                "budget_ratio": 0.6,
                "legs_min": 2,
                "odds_range": [1.1, 999],
                "kelly_frac": 0.25,
            },
            "exotics": {
                 "enable_if": {
                    "ev_min": 0.40,
                    "payout_min": 10.0
                }
            }
        },
    }


@pytest.fixture
def mock_calibration_data() -> dict:
    """Provides mock calibration data allowing exotics."""
    return {"exotic_weights": {"TRIO": 1.0}}


def test_generate_tickets_abstains_when_roi_is_low(
    mocker: MockerFixture, mock_gpi_config: dict, mock_calibration_data: dict
):
    """
    Tests that generate_tickets abstains if the runners' ROI is below the threshold.
    """
    # This dependency is not under test, so we mock it.
    mocker.patch(
        "hippique_orchestrator.pipeline_run.evaluate_combo",
        return_value={"status": "error"},
    )

    # Runners with low ROI: prob=0.3, odds=3.0 -> ROI = (0.3 * 2) - 0.7 = -0.1
    snapshot_data = {
        "runners": [
            {"num": 1, "p_no_vig": 0.3, "odds_place": 3.0},
            {"num": 2, "p_no_vig": 0.3, "odds_place": 3.0},
        ],
        "market": {"overround_place": 1.10}
    }
    budget = 5.0

    result = generate_tickets(
        snapshot_data, mock_gpi_config, budget, mock_calibration_data, je_stats={}
    )

    assert "Abstain" in result["gpi_decision"]
    assert len(result["tickets"]) == 0
    assert "No profitable tickets found" in result["message"]


def test_generate_tickets_creates_sp_dutching_ticket_when_roi_is_high(
    mocker: MockerFixture, mock_gpi_config: dict, mock_calibration_data: dict
):
    """
    Tests that generate_tickets creates an SP Dutching ticket for runners with high ROI.
    """
    mocker.patch(
        "hippique_orchestrator.pipeline_run.evaluate_combo",
        return_value={"status": "error"}, # Ensure exotics don't interfere
    )

    # Runners with high ROI
    # R1: prob=0.4, odds=4.0 -> ROI = (0.4 * 3) - 0.6 = 0.6
    # R2: prob=0.3, odds=5.0 -> ROI = (0.3 * 4) - 0.7 = 0.5
    snapshot_data = {
        "runners": [
            {"num": 1, "p_no_vig": 0.4, "odds_place": 4.0},
            {"num": 2, "p_no_vig": 0.3, "odds_place": 5.0},
            {"num": 3, "p_no_vig": 0.1, "odds_place": 10.0}, # Low ROI
        ],
        "market": {"overround_place": 1.10}
    }
    budget = 5.0

    result = generate_tickets(
        snapshot_data, mock_gpi_config, budget, mock_calibration_data, je_stats={}
    )
    
    assert result["gpi_decision"] == "Play"
    assert len(result["tickets"]) == 1
    
    sp_ticket = result["tickets"][0]
    assert sp_ticket["type"] == "SP_DUTCHING"
    assert sp_ticket["stake"] > 0
    # Check that only the high-ROI horses are included
    assert set(sp_ticket["horses"]) == {1, 2}
    assert 3 not in sp_ticket["horses"]
    assert sp_ticket["roi_est"] > mock_gpi_config["roi_min_sp"]
    assert result["roi_global_est"] > mock_gpi_config["roi_min_global"]

def test_generate_tickets_abstains_when_global_roi_is_low(
    mocker: MockerFixture, mock_gpi_config: dict, mock_calibration_data: dict
):
    """
    Tests that even if a ticket is found, the system abstains if the final
    global ROI is below the main threshold.
    """
    mocker.patch(
        "hippique_orchestrator.pipeline_run.evaluate_combo",
        return_value={"status": "error"},
    )
    
    # Set a very high global ROI threshold that won't be met
    mock_gpi_config["roi_min_global"] = 0.99

    # Runners with high ROI, but not high enough to meet the global threshold
    snapshot_data = {
        "runners": [
            {"num": 1, "p_no_vig": 0.4, "odds_place": 4.0}, # ROI = 0.6
            {"num": 2, "p_no_vig": 0.3, "odds_place": 5.0}, # ROI = 0.5
        ],
        "market": {"overround_place": 1.10}
    }
    budget = 5.0

    result = generate_tickets(
        snapshot_data, mock_gpi_config, budget, mock_calibration_data, je_stats={}
    )

    assert "Abstain" in result["gpi_decision"]
    assert f"Global ROI ({result['roi_global_est']:.2f}) is below threshold (0.99)" in result["message"]
    # The tickets list should be empty in the final decision
    assert len(result["tickets"]) == 0