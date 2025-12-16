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
        "ev_min_combo": 0.40,
        "payout_min_combo": 10.0,
        "weights": {
            "base": {},
            "horse_stats": {}
        },
        "adjustments": {
            "chrono": {"k_c": 0.18},
            "drift": {"k_d": 0.70}
        },
        "tickets": {
            "sp_dutching": {
                "budget_ratio": 0.6,
                "legs_min": 2,
                "odds_range": [1.1, 999],
                "kelly_frac": 0.25,
            },
            "exotics": {
                 "type": "TRIO",
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
    mocker.patch("hippique_orchestrator.pipeline_run.evaluate_combo", return_value={"status": "error"})
    snapshot_data = {
        "runners": [
            {"num": 1, "p_no_vig": 0.3, "odds_place": 3.0},
            {"num": 2, "p_no_vig": 0.3, "odds_place": 3.0},
        ],
        "market": {"overround_place": 1.10}
    }
    budget = 5.0

    result = generate_tickets(
        snapshot_data=snapshot_data,
        gpi_config=mock_gpi_config,
        budget=budget,
        calibration_data=mock_calibration_data,
        je_stats={},
        h30_snapshot_data=None
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
    mocker.patch("hippique_orchestrator.pipeline_run.evaluate_combo", return_value={"status": "error"})
    snapshot_data = {
        "runners": [
            {"num": 1, "p_no_vig": 0.4, "odds_place": 4.0},
            {"num": 2, "p_no_vig": 0.3, "odds_place": 5.0},
            {"num": 3, "p_no_vig": 0.1, "odds_place": 10.0},
        ],
        "market": {"overround_place": 1.10}
    }
    budget = 5.0

    result = generate_tickets(
        snapshot_data=snapshot_data,
        gpi_config=mock_gpi_config,
        budget=budget,
        calibration_data=mock_calibration_data,
        je_stats={},
        h30_snapshot_data=None
    )

    assert result["gpi_decision"] == "Play"
    assert len(result["tickets"]) == 1

    sp_ticket = result["tickets"][0]
    assert sp_ticket["type"] == "SP_DUTCHING"
    assert sp_ticket["stake"] > 0
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
    mocker.patch("hippique_orchestrator.pipeline_run.evaluate_combo", return_value={"status": "error"})
    mock_gpi_config["roi_min_global"] = 0.99
    snapshot_data = {
        "runners": [
            {"num": 1, "p_no_vig": 0.4, "odds_place": 4.0},
            {"num": 2, "p_no_vig": 0.3, "odds_place": 5.0},
        ],
        "market": {"overround_place": 1.10}
    }
    budget = 5.0

    result = generate_tickets(
        snapshot_data=snapshot_data,
        gpi_config=mock_gpi_config,
        budget=budget,
        calibration_data=mock_calibration_data,
        je_stats={},
        h30_snapshot_data=None
    )

    assert "Abstain" in result["gpi_decision"]
    assert f"Global ROI ({result['roi_global_est']:.2f})" in result["message"]
    assert len(result["tickets"]) == 0

def test_generate_tickets_creates_trio_ticket_with_best_roi(
    mocker: MockerFixture, mock_gpi_config: dict, mock_calibration_data: dict
):
    """
    Tests that the new Trio logic correctly evaluates multiple combinations,
    selects the one with the best ROI, and creates a valid ticket.
    """
    snapshot_data = {
        "runners": [
            {"num": 1, "p_no_vig": 0.4, "odds_place": 4.0},
            {"num": 2, "p_no_vig": 0.3, "odds_place": 5.0},
            {"num": 3, "p_no_vig": 0.25, "odds_place": 6.0},
            {"num": 4, "p_no_vig": 0.2, "odds_place": 7.0},
        ],
        "market": {"overround_place": 1.10}
    }
    budget = 5.0
    mock_gpi_config["tickets"]["exotics"]["type"] = "TRIO"

    def evaluate_combo_side_effect(tickets, bankroll, calibration):
        horse_nums = {leg["num"] for leg in tickets[0]["legs"]}
        if horse_nums == {1, 2, 3}: return {"status": "ok", "roi": 0.8, "payout_expected": 50.0}
        if horse_nums == {1, 2, 4}: return {"status": "ok", "roi": 0.5, "payout_expected": 30.0}
        return {"status": "ok", "roi": 0.1, "payout_expected": 5.0}

    mocker.patch("hippique_orchestrator.pipeline_run.evaluate_combo", side_effect=evaluate_combo_side_effect)

    result = generate_tickets(
        snapshot_data=snapshot_data,
        gpi_config=mock_gpi_config,
        budget=budget,
        calibration_data=mock_calibration_data,
        je_stats={},
        h30_snapshot_data=None
    )

    assert result["gpi_decision"] == "Play"
    assert len(result["tickets"]) == 2, "Should create one SP and one TRIO ticket"

    trio_ticket = next((t for t in result["tickets"] if t["type"] == "TRIO"), None)

    assert trio_ticket is not None, "A TRIO ticket should have been created"
    assert set(trio_ticket["horses"]) == {1, 2, 3}
    assert trio_ticket["roi_est"] == 0.8
    assert trio_ticket["payout_est"] == 50.0
    assert trio_ticket["stake"] == budget * (1 - mock_gpi_config["tickets"]["sp_dutching"]["budget_ratio"])
