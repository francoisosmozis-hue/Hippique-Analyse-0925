# Re-use the mock_gpi_config from test_pipeline_run.py or define a more comprehensive one
import copy
import math

import pytest
from pytest_mock import MockerFixture

from hippique_orchestrator import pipeline_run
from hippique_orchestrator.pipeline_run import (
    _apply_base_stat_adjustment,
    _apply_chrono_adjustment,
    _apply_drift_adjustment,
    _calculate_adjusted_probabilities,
    _finalize_and_decide,
    _generate_sp_dutching_tickets,
    _get_legs_for_exotic_type,
    _initialize_and_validate,
    _select_sp_dutching_candidates,
    generate_tickets,
)


# Re-use the mock_gpi_config from test_pipeline_run.py or define a more comprehensive one
@pytest.fixture
def mock_gpi_config():
    """Provides a more comprehensive mock GPI configuration for testing."""
    base_config = {
        "budget": 100.0,
        "budget_cap_eur": 100.0,
        "max_vol_per_horse": 0.6,
        "je_stats": {},
        "h30_snapshot_data": {},  # Will be populated as needed
        "roi_min_sp": 0.20,
        "roi_min_global": 0.25,
        "overround_max_exotics": 1.30,
        "ev_min_combo": 0.40,
        "payout_min_combo": 12.0,
        "weights": {
            "base": {
                "je_bonus": 1.2,
                "je_malus": 0.8,
                "j_rate_bonus_threshold": 12.0,
                "e_rate_bonus_threshold": 15.0,
                "j_rate_malus_threshold": 6.0,
                "e_rate_malus_threshold": 8.0,
            },
            "horse_stats": {},  # Specific horse stats weights can be added here
        },
        "adjustments": {
            "chrono": {"k_c": 0.18},
            "drift": {
                "k_d": 0.70,
                "threshold": 0.07,
                "favorite_odds": 4.0,
                "favorite_factor": 1.20,
                "k_d_fav_drift": 0.90,
                "outsider_odds": 8.0,
                "outsider_steam_factor": 0.85,
                "k_d_out_steam": 0.85,
                "high_odds": 60.0,
                "extreme_drift_factor": 1.80,
            },
            "volatility": {  # Nested under adjustments, then volatility
                "sure_bonus": 1.1,
                "volatile_malus": 0.9,
                "musique_score_weight": 0.01,
            },
        },
        "tickets": {
            "sp_dutching": {
                "budget_ratio": 0.6,
                "legs_min": 2,
                "legs_max": 3,  # Adjusted range for more realistic testing
                "odds_range": [2.5, 7.0],
                "kelly_frac": 0.25,
            },
            "exotics": {
                "allowed": ["TRIO", "COUPLE"],
                "max_combinations": 10,
            },
        },
    }
    # These are added by _initialize_and_validate for functions that expect them at top-level
    base_config["chrono_config"] = base_config["adjustments"]["chrono"]
    base_config["drift_config"] = base_config["adjustments"]["drift"]
    base_config["sp_config"] = base_config["tickets"]["sp_dutching"]
    base_config["exotics_config"] = base_config["tickets"]["exotics"]
    return copy.deepcopy(base_config)


@pytest.fixture
def mock_snapshot_data():
    """Provides a basic mock snapshot data."""
    return copy.deepcopy(
        {
            "runners": [
                {"num": 1, "nom": "Horse A", "odds_win": 5.0, "odds_place": 2.0},
                {"num": 2, "nom": "Horse B", "odds_win": 8.0, "odds_place": 3.0},
                {"num": 3, "nom": "Horse C", "odds_win": 12.0, "odds_place": 4.0},
                {"num": 4, "nom": "Horse D", "odds_win": 3.0, "odds_place": 1.5},
            ]
        }
    )


def test_normalize_probs_empty_list():
    assert pipeline_run._normalize_probs([]) == []


def test_normalize_probs_zero_sum():
    assert pipeline_run._normalize_probs([0.0, 0.0, 0.0]) == [1 / 3, 1 / 3, 1 / 3]


# --- Tests for _initialize_and_validate ---


def test_initialize_and_validate_success(mock_snapshot_data, mock_gpi_config):
    # _initialize_and_validate expects the raw gpi_config, not the pre-processed one.
    # We create a temporary config that looks like the raw gpi_config before processing.
    raw_gpi_config = {
        k: v
        for k, v in mock_gpi_config.items()
        if k not in ["chrono_config", "drift_config", "sp_config", "exotics_config"]
    }
    runners, config = _initialize_and_validate(mock_snapshot_data, raw_gpi_config)
    assert len(runners) == 4
    assert config["budget"] == 100.0
    assert "roi_min_sp" in config
    assert "chrono_config" in config  # Check that _initialize_and_validate added it


def test_initialize_and_validate_missing_budget_raises_error(mock_snapshot_data, mock_gpi_config):
    raw_gpi_config = {
        k: v
        for k, v in mock_gpi_config.items()
        if k not in ["chrono_config", "drift_config", "sp_config", "exotics_config"]
    }
    del raw_gpi_config["budget"]
    del raw_gpi_config["budget_cap_eur"]  # Ensure both are missing
    with pytest.raises(
        ValueError, match="Configuration file is missing 'budget' or 'budget_cap_eur'"
    ):
        _initialize_and_validate(mock_snapshot_data, raw_gpi_config)


def test_initialize_and_validate_empty_runners_raises_error(mock_gpi_config):
    empty_snapshot = {"runners": []}
    raw_gpi_config = {
        k: v
        for k, v in mock_gpi_config.items()
        if k not in ["chrono_config", "drift_config", "sp_config", "exotics_config"]
    }
    with pytest.raises(ValueError, match="No runners found"):
        _initialize_and_validate(empty_snapshot, raw_gpi_config)


def test_initialize_and_validate_missing_critical_key_raises_error(
    mock_snapshot_data, mock_gpi_config
):
    raw_gpi_config = {
        k: v
        for k, v in mock_gpi_config.items()
        if k not in ["chrono_config", "drift_config", "sp_config", "exotics_config"]
    }
    del raw_gpi_config["roi_min_sp"]
    with pytest.raises(ValueError, match="Configuration file is missing a critical key"):
        _initialize_and_validate(mock_snapshot_data, raw_gpi_config)


# --- Tests for _calculate_adjusted_probabilities ---


def test_calculate_adjusted_probabilities_missing_base_probabilities_raises_error(
    mock_snapshot_data, mock_gpi_config
):
    # Simulate a runner with no valid odds_place or odds_win
    mock_snapshot_data["runners"][0].pop("odds_place")
    mock_snapshot_data["runners"][0].pop("odds_win")  # Horse A has no valid base prob

    with pytest.raises(ValueError, match="Missing valid base probabilities for runner 1"):
        _calculate_adjusted_probabilities(mock_snapshot_data["runners"], mock_gpi_config)


def test_calculate_adjusted_probabilities_p_base_fallback_from_win_odds(
    mock_snapshot_data, mock_gpi_config
):
    # Test a scenario where only win odds are present and p_base is derived from odds_win
    mock_snapshot_data["runners"] = [
        {"num": 1, "nom": "Horse A", "odds_win": 5.0, "odds_place": None},
        {"num": 2, "nom": "Horse B", "odds_win": 8.0, "odds_place": None},
    ]
    # Ensure p_base is not pre-set for this sub-test
    for r in mock_snapshot_data["runners"]:
        r.pop("p_base", None)
        r.pop("p_no_vig", None)
        r.pop("p_place", None)

    runners_adjusted, messages = _calculate_adjusted_probabilities(
        mock_snapshot_data["runners"], mock_gpi_config
    )

    assert runners_adjusted[0]["p_base"] > 0
    assert runners_adjusted[1]["p_base"] > 0
    assert "overround_win" in mock_gpi_config["market"]


def test_calculate_adjusted_probabilities_real_favorites_detection(
    mock_snapshot_data, mock_gpi_config
):
    mock_snapshot_data["runners"][0]["p_place"] = 0.30  # Make Horse A a real favorite
    runners_adjusted, messages = _calculate_adjusted_probabilities(
        mock_snapshot_data["runners"], mock_gpi_config
    )
    assert "Favori(s) réel(s) (Place > 25%): Horse A, Horse D." in messages
    assert runners_adjusted[0]["is_real_favorite_place"] is True


def test_calculate_adjusted_probabilities_overround_calculation(
    mock_snapshot_data, mock_gpi_config
):
    runners_adjusted, messages = _calculate_adjusted_probabilities(
        mock_snapshot_data["runners"], mock_gpi_config
    )
    assert "overround_win" in mock_gpi_config["market"]
    assert "overround_place" in mock_gpi_config["market"]
    assert mock_gpi_config["market"]["overround_win"] > 0
    assert mock_gpi_config["market"]["overround_place"] > 0


# --- Tests for _apply_base_stat_adjustment ---


def test_apply_base_stat_adjustment_je_bonus(mock_snapshot_data, mock_gpi_config):
    runners = mock_snapshot_data["runners"]
    # Ensure p_base is present for all runners, as _apply_base_stat_adjustment expects it
    for r in runners:
        r["p_base"] = 0.2  # Arbitrary base prob for all
    # J_rate above bonus threshold, e_rate above bonus threshold
    je_stats = {"1": {"j_rate": 15.0, "e_rate": 20.0}}

    adjusted_probs = _apply_base_stat_adjustment(
        runners, je_stats, mock_gpi_config["weights"], mock_gpi_config
    )
    assert adjusted_probs[0] > runners[0]["p_base"]  # Should be increased by je_bonus


def test_apply_base_stat_adjustment_je_malus(mock_snapshot_data, mock_gpi_config):
    runners = mock_snapshot_data["runners"]
    for r in runners:
        r["p_base"] = 0.2
    je_stats = {"1": {"j_rate": 5.0, "e_rate": 7.0}}  # J_rate below malus threshold

    adjusted_probs = _apply_base_stat_adjustment(
        runners, je_stats, mock_gpi_config["weights"], mock_gpi_config
    )
    assert adjusted_probs[0] < runners[0]["p_base"]  # Should be decreased by je_malus


def test_apply_base_stat_adjustment_volatility_bonus(mock_snapshot_data, mock_gpi_config):
    runners = mock_snapshot_data["runners"]
    for r in runners:
        r["p_base"] = 0.2
    runners[0]["volatility"] = "SÛR"

    adjusted_probs = _apply_base_stat_adjustment(
        runners, {}, mock_gpi_config["weights"], mock_gpi_config
    )
    assert adjusted_probs[0] > runners[0]["p_base"]  # Should be increased by sure_bonus


def test_apply_base_stat_adjustment_musique_score(mock_snapshot_data, mock_gpi_config):
    runners = mock_snapshot_data["runners"]
    for r in runners:
        r["p_base"] = 0.2

    # Simulate parsed_musique data that results in a non-zero score
    runners[0]["parsed_musique"] = {
        "top3_count": 1,
        "top5_count": 1,
        "disqualified_count": 0,
        "recent_performances_numeric": [1],
        "is_dai": False,
        "regularity_score": 1.0,
        "last_race_placing": 1,
        "num_races_in_musique": 1,
    }

    # Create a local copy of volatility config to modify
    local_volatility_config = copy.deepcopy(mock_gpi_config["adjustments"]["volatility"])
    # Set musique_score_weight to a value that will cause a clear adjustment
    local_volatility_config["musique_score_weight"] = 1.0

    # Pass the modified volatility_config through the full config structure
    temp_config = copy.deepcopy(mock_gpi_config)
    temp_config["adjustments"]["volatility"] = local_volatility_config

    adjusted_probs = _apply_base_stat_adjustment(runners, {}, temp_config["weights"], temp_config)
    # Expected score from score_musique_form for this data:
    # score = top3_count * 2.0 + (top5_count_only) * 1.0 - normalized_regularity_penalty * 3.0
    # top3_count = 1, top5_count_only = 0
    # num_races_in_musique = 1
    # normalized_regularity_penalty = (1.0 - 1.0) / 9.0 = 0
    # score = 1 * 2.0 + 0 - 0 = 2.0
    # factor = 1 + 2.0 * 1.0 = 3.0
    # adjusted_probs[0] = 0.2 * 3.0 = 0.6
    assert adjusted_probs[0] > runners[0]["p_base"]  # Should be increased by musique_score_weight
    assert adjusted_probs[0] == pytest.approx(
        runners[0]["p_base"] * (1 + 2.0 * local_volatility_config["musique_score_weight"])
    )


def test_apply_base_stat_adjustment_no_je_or_volatility_data(mock_snapshot_data, mock_gpi_config):
    runners = mock_snapshot_data["runners"]
    for r in runners:
        r["p_base"] = 0.2

    adjusted_probs = _apply_base_stat_adjustment(
        runners, {}, mock_gpi_config["weights"], mock_gpi_config
    )
    assert adjusted_probs[0] == runners[0]["p_base"]  # Should remain unchanged (factor 1.0)


def test_apply_base_stat_adjustment_je_neutral(mock_snapshot_data, mock_gpi_config):
    runners = mock_snapshot_data["runners"]
    for r in runners:
        r["p_base"] = 0.2
    # J_rate and e_rate are between bonus and malus thresholds
    je_stats = {"1": {"j_rate": 10.0, "e_rate": 10.0}}

    adjusted_probs = _apply_base_stat_adjustment(
        runners, je_stats, mock_gpi_config["weights"], mock_gpi_config
    )
    assert adjusted_probs[0] == runners[0]["p_base"]  # Should remain unchanged (factor 1.0)


def test_apply_base_stat_adjustment_je_invalid_rate_type(mock_snapshot_data, mock_gpi_config):
    runners = mock_snapshot_data["runners"]
    for r in runners:
        r["p_base"] = 0.2
    je_stats = {"1": {"j_rate": "invalid_float", "e_rate": 10.0}}  # Invalid j_rate type

    adjusted_probs = _apply_base_stat_adjustment(
        runners, je_stats, mock_gpi_config["weights"], mock_gpi_config
    )
    assert adjusted_probs[0] == runners[0]["p_base"]  # Should remain unchanged (factor 1.0)


# --- Tests for _apply_chrono_adjustment ---


def test_apply_chrono_adjustment_success(mock_snapshot_data, mock_gpi_config):
    # Only pass two runners for this test to match assertion length
    runners_for_test = [
        {"num": 1, "nom": "Horse A", "p_base": 0.1},
        {"num": 2, "nom": "Horse B", "p_base": 0.1},
    ]
    je_stats = {
        "1": {"last_3_chrono": [70.0, 71.0, 72.0]},  # Best 70.0
        "2": {"last_3_chrono": [75.0, 76.0, 77.0]},  # Best 75.0
    }

    factors = _apply_chrono_adjustment(
        runners_for_test, je_stats, mock_gpi_config["adjustments"]["chrono"]
    )
    assert len(factors) == 2
    assert factors[0] > 1.0  # Horse A has better chrono than median
    assert factors[1] < 1.0  # Horse B has worse chrono than median


def test_apply_chrono_adjustment_no_best_chronos(mock_snapshot_data, mock_gpi_config):
    runners = mock_snapshot_data["runners"]
    # No chrono data in je_stats
    factors = _apply_chrono_adjustment(runners, {}, mock_gpi_config["adjustments"]["chrono"])
    assert all(f == 1.0 for f in factors)  # Factors should all be 1.0


def test_apply_chrono_adjustment_malformed_chrono_data(mock_gpi_config):
    # Use a single runner with malformed chrono data
    runners = [{"num": 1, "nom": "Horse A", "p_base": 0.1}]
    malformed_je_stats = {
        "1": {"last_3_chrono": ["invalid", 71.0, 72.0]},
    }

    factors = _apply_chrono_adjustment(
        runners, malformed_je_stats, mock_gpi_config["adjustments"]["chrono"]
    )
    # Factors should all be 1.0 because no valid chrono was found for the runner
    assert len(factors) == 1
    assert factors[0] == 1.0


# --- Tests for _apply_drift_adjustment ---


def test_apply_drift_adjustment_no_h30_odds(mock_snapshot_data, mock_gpi_config):
    runners = mock_snapshot_data["runners"]
    # No h30_odds_map means no drift adjustment, factors should be 1.0
    factors = _apply_drift_adjustment(runners, {}, mock_gpi_config["adjustments"]["drift"])
    assert all(f == 1.0 for f in factors)
    assert all(r["drift_status"] == "Stable" for r in runners)


def test_apply_drift_adjustment_stable_odds(mock_snapshot_data, mock_gpi_config):
    runners = mock_snapshot_data["runners"]
    # Simulate very little change in odds, within threshold
    h30_odds_map = {1: 2.05, 2: 3.05}  # Original: 2.0, 3.0

    # Set initial odds_place for runners to reflect h30_odds
    runners[0]["odds_place"] = 2.05
    runners[1]["odds_place"] = 3.05

    factors = _apply_drift_adjustment(
        runners[:2], h30_odds_map, mock_gpi_config["adjustments"]["drift"]
    )
    assert all(f == 1.0 for f in factors)
    assert runners[0]["drift_status"] == "Stable"
    assert runners[0]["drift_percent"] == ((2.05 - 2.05) / 2.05) * 100


def test_apply_drift_adjustment_drift_detected(mock_snapshot_data, mock_gpi_config):
    runners = mock_snapshot_data["runners"]
    # Simulate drift: H-5 odds higher than H-30 odds
    h30_odds_map = {1: 1.5, 2: 2.0}
    runners[0]["odds_place"] = 2.0  # Drifted up
    runners[1]["odds_place"] = 3.0  # Drifted up

    factors = _apply_drift_adjustment(
        runners[:2], h30_odds_map, mock_gpi_config["adjustments"]["drift"]
    )
    assert factors[0] < 1.0  # Factor should penalize drift
    assert factors[1] < 1.0
    assert runners[0]["drift_status"] == "Drift"
    assert runners[1]["drift_status"] == "Drift"
    assert runners[0]["drift_percent"] > mock_gpi_config["adjustments"]["drift"]["threshold"] * 100


def test_apply_drift_adjustment_steam_detected(mock_snapshot_data, mock_gpi_config):
    runners = mock_snapshot_data["runners"]
    # Simulate steam: H-5 odds lower than H-30 odds
    h30_odds_map = {1: 3.0, 2: 4.0}
    runners[0]["odds_place"] = 2.0  # Steamed down
    runners[1]["odds_place"] = 3.0  # Steamed down

    factors = _apply_drift_adjustment(
        runners[:2], h30_odds_map, mock_gpi_config["adjustments"]["drift"]
    )
    assert factors[0] > 1.0  # Factor should bonus steam
    assert factors[1] > 1.0
    assert runners[0]["drift_status"] == "Steam"
    assert runners[1]["drift_status"] == "Steam"
    assert runners[0]["drift_percent"] < -mock_gpi_config["adjustments"]["drift"]["threshold"] * 100


def test_apply_drift_adjustment_favorite_drift_factor(mock_snapshot_data, mock_gpi_config):
    runners = mock_snapshot_data["runners"]
    # Horse 1 is favorite, drifts more than favorite_factor
    h30_odds_map = {1: 3.0}
    runners[0]["odds_place"] = 4.0  # 3.0 -> 4.0 is 33% drift, > 20% fav_factor (1.20)

    drift_config = mock_gpi_config["adjustments"]["drift"]
    factors = _apply_drift_adjustment(runners[:1], h30_odds_map, drift_config)
    # The k_d_fav_drift should be used, resulting in a stronger penalty
    assert factors[0] < 1.0
    assert "Drift" in runners[0]["drift_status"]


def test_apply_drift_adjustment_outsider_steam_factor(mock_snapshot_data, mock_gpi_config):
    runners = mock_snapshot_data["runners"]
    # Horse 1 is outsider, steams more than outsider_steam_factor
    h30_odds_map = {1: 10.0}
    runners[0]["odds_place"] = 8.0  # 10.0 -> 8.0 is 20% steam, > 15% out_steam_factor (0.85)

    drift_config = mock_gpi_config["adjustments"]["drift"]
    factors = _apply_drift_adjustment(runners[:1], h30_odds_map, drift_config)
    # The k_d_out_steam should be used, resulting in a stronger bonus
    assert factors[0] > 1.0
    assert "Steam" in runners[0]["drift_status"]


def test_apply_drift_adjustment_medium_drift_no_special_factors(
    mock_snapshot_data, mock_gpi_config
):
    runners = mock_snapshot_data["runners"]
    # Simulate a runner with odds that drift outside the threshold, but not enough to be a fav/outsider
    h30_odds_map = {1: 5.0}  # Initial odds
    runners[0]["odds_place"] = (
        5.8  # Drifted up by 16% (5.8/5.0 - 1 = 0.16), which is > 0.07 threshold
    )
    # The default fav_odds_threshold is 4.0, out_odds_threshold is 8.0, so 5.0 is in between

    factors = _apply_drift_adjustment(
        runners[:1], h30_odds_map, mock_gpi_config["adjustments"]["drift"]
    )
    assert len(factors) == 1
    assert factors[0] != 1.0  # Factor should be applied
    assert runners[0]["drift_status"] == "Drift"
    assert factors[0] == pytest.approx(
        math.exp(-mock_gpi_config["adjustments"]["drift"]["k_d"] * math.log(5.8 / 5.0))
    )


def test_select_sp_dutching_candidates_min_candidates(mock_snapshot_data):
    # Need at least 2 candidates for SP Dutching
    dutching_pool = [
        {"num": 1, "odds": 3.0},
        {"num": 2, "odds": 4.0},
    ]
    selected = _select_sp_dutching_candidates(dutching_pool)
    assert len(selected) == 2


def test_select_sp_dutching_candidates_mid_range_priority(mock_snapshot_data):
    dutching_pool = [
        {"num": 1, "odds": 3.0},
        {"num": 2, "odds": 9.0},  # Out of range for mid_range_horse_found
        {"num": 3, "odds": 5.0},  # Mid-range
    ]
    selected = _select_sp_dutching_candidates(dutching_pool)
    assert len(selected) == 3  # Should select 1 and 3, then 2 if no other mid range
    assert {c["num"] for c in selected} == {1, 3, 2}


def test_select_sp_dutching_candidates_max_candidates_limit(mock_snapshot_data):
    dutching_pool = [
        {"num": 1, "odds": 3.0},
        {"num": 2, "odds": 4.0},
        {"num": 3, "odds": 5.0},
        {"num": 4, "odds": 6.0},
    ]
    selected = _select_sp_dutching_candidates(dutching_pool)
    assert len(selected) == 3


# --- Tests for _generate_sp_dutching_tickets ---


def test_generate_sp_dutching_tickets_no_profitable_candidates(mock_snapshot_data, mock_gpi_config):
    runners = mock_snapshot_data["runners"]
    for r in runners:
        r["p_finale"] = 0.1  # Ensure p_finale is present for ROI calculation
    # Set ROI_min_sp very high to ensure no profitable candidates
    mock_gpi_config["roi_min_sp"] = 100.0

    final_tickets = []
    analysis_messages = []

    sp_candidates_for_exotics, final_tickets, analysis_messages = _generate_sp_dutching_tickets(
        runners, mock_gpi_config, final_tickets, analysis_messages
    )
    assert not final_tickets
    assert "Less than 2 suitable candidates found" in analysis_messages[0]


def test_generate_sp_dutching_tickets_profitable_candidates_creates_ticket(
    mock_snapshot_data, mock_gpi_config
):
    runners = mock_snapshot_data["runners"]
    # Ensure all runners have p_finale and odds_place for calculation
    runners[0].update({"p_finale": 0.8, "odds_place": 2.6})  # Make profitable
    runners[1].update({"p_finale": 0.7, "odds_place": 3.0})  # Make profitable
    runners[2].update({"p_finale": 0.1, "odds_place": 8.0})  # Outside odds_range
    runners[3].update({"p_finale": 0.05, "odds_place": 10.0})  # Another runner

    # Adjust config to accept these odds
    mock_gpi_config["tickets"]["sp_dutching"]["odds_range"] = [2.0, 5.0]

    final_tickets = []
    analysis_messages = []

    # Make sure runners have p_finale set for sp_candidates_for_exotics as well
    for r in runners:
        if "p_finale" not in r:
            r["p_finale"] = 0.1  # Default if not explicitly set above

    sp_candidates_for_exotics, final_tickets, analysis_messages = _generate_sp_dutching_tickets(
        runners, mock_gpi_config, final_tickets, analysis_messages
    )
    assert len(final_tickets) == 1
    assert final_tickets[0]["type"] == "SP_DUTCHING"
    assert "SP Dutching ticket created" in analysis_messages[0]
    assert len(sp_candidates_for_exotics) >= 2


# --- Tests for _get_legs_for_exotic_type ---
@pytest.mark.parametrize(
    "exotic_type, expected_legs",
    [
        ("COUPLE", 2),
        ("COUPLE_PLACE", 2),
        ("ZE234", 2),
        ("TRIO", 3),
        ("ZE4", 4),
        ("UNKNOWN", 3),  # Default fallback
    ],
)
def test_get_legs_for_exotic_type(exotic_type, expected_legs, caplog):
    if exotic_type == "UNKNOWN":
        _ = _get_legs_for_exotic_type(exotic_type)
        assert "Unknown exotic type 'UNKNOWN', assuming 3 legs." in caplog.text
    else:
        assert _get_legs_for_exotic_type(exotic_type) == expected_legs


# --- Tests for _generate_exotic_tickets ---


def test_generate_exotic_tickets_no_profitable_combos(
    mocker: MockerFixture, mock_snapshot_data, mock_gpi_config
):
    mocker.patch(
        "hippique_orchestrator.pipeline_run.evaluate_combo", return_value={"status": "error"}
    )

    sp_candidates = mock_snapshot_data["runners"][:3]  # Use some candidates
    mock_gpi_config["exotics_config"]["allowed"] = ["TRIO"]  # Ensure config allows exotics
    mock_gpi_config["market"] = {"overround_place": 1.10}  # Add market for overround check
    mock_gpi_config["overround_max"] = mock_gpi_config["overround_max_exotics"]

    final_tickets = []
    analysis_messages = []

    final_tickets, analysis_messages = pipeline_run._generate_exotic_tickets(
        sp_candidates, mock_snapshot_data, mock_gpi_config, final_tickets, analysis_messages
    )
    assert not final_tickets  # No tickets should be added if evaluate_combo fails
    assert not analysis_messages


def test_generate_exotic_tickets_overround_too_high(mock_snapshot_data, mock_gpi_config):
    mock_gpi_config["overround_max_exotics"] = 1.0  # Set very low
    mock_gpi_config["market"] = {"overround_place": 1.5}  # Higher than max
    mock_gpi_config["exotics_config"]["allowed"] = ["TRIO"]  # Ensure allowed exotics
    mock_gpi_config["overround_max"] = mock_gpi_config["overround_max_exotics"]

    final_tickets = []
    analysis_messages = []

    final_tickets, analysis_messages = pipeline_run._generate_exotic_tickets(
        [], mock_snapshot_data, mock_gpi_config, final_tickets, analysis_messages
    )
    assert not final_tickets
    assert "Exotics forbidden due to high overround." in analysis_messages[0]


def test_generate_exotic_tickets_no_allowed_types(mock_snapshot_data, mock_gpi_config):
    mock_gpi_config["exotics_config"]["allowed"] = []  # No allowed types
    mock_gpi_config["market"] = {"overround_place": 1.10}  # Add market for overround check
    mock_gpi_config["overround_max"] = mock_gpi_config["overround_max_exotics"]

    final_tickets = []
    analysis_messages = []

    final_tickets, analysis_messages = pipeline_run._generate_exotic_tickets(
        mock_snapshot_data["runners"][:3],
        mock_snapshot_data,
        mock_gpi_config,
        final_tickets,
        analysis_messages,
    )
    assert not final_tickets
    assert not analysis_messages


def test_generate_exotic_tickets_not_enough_sp_candidates(mock_snapshot_data, mock_gpi_config):
    mock_gpi_config["exotics_config"]["allowed"] = ["TRIO"]  # Set allowed exotic type
    mock_gpi_config["market"] = {"overround_place": 1.10}  # Add market for overround check
    mock_gpi_config["overround_max"] = mock_gpi_config["overround_max_exotics"]

    final_tickets = []
    analysis_messages = []

    final_tickets, analysis_messages = pipeline_run._generate_exotic_tickets(
        mock_snapshot_data["runners"][:1],
        mock_snapshot_data,
        mock_gpi_config,
        final_tickets,
        analysis_messages,  # Only 1 candidate
    )
    assert not final_tickets
    assert not analysis_messages


def test_generate_exotic_tickets_multiple_profitable_combos_updates_best(
    mocker: MockerFixture, mock_snapshot_data, mock_gpi_config
):
    # Mock evaluate_combo to return different results for different combos
    # First combo: lower ROI
    # Second combo: higher ROI
    mocker.patch(
        "hippique_orchestrator.pipeline_run.evaluate_combo",
        side_effect=[
            {"status": "ok", "roi": 0.5, "payout_expected": 20.0},  # First combo
            {"status": "ok", "roi": 0.3, "payout_expected": 15.0},  # Second combo (lower)
            {"status": "ok", "roi": 0.6, "payout_expected": 22.0},  # Third combo (medium)
            {"status": "ok", "roi": 0.7, "payout_expected": 25.0},  # Fourth combo (best)
        ],
    )
    # Ensure sp_candidates have the 'odds' key expected by math.prod
    sp_candidates = [
        {"num": 1, "nom": "Horse A", "odds": 5.0},
        {"num": 2, "nom": "Horse B", "odds": 8.0},
        {"num": 3, "nom": "Horse C", "odds": 12.0},
        {"num": 4, "nom": "Horse D", "odds": 6.0},  # Added a fourth horse
    ]
    mock_gpi_config["exotics_config"]["allowed"] = ["TRIO"]
    mock_gpi_config["market"] = {"overround_place": 1.10}
    mock_gpi_config["overround_max"] = mock_gpi_config["overround_max_exotics"]

    final_tickets = []
    analysis_messages = []

    final_tickets, analysis_messages = pipeline_run._generate_exotic_tickets(
        sp_candidates, mock_snapshot_data, mock_gpi_config, final_tickets, analysis_messages
    )
    assert len(final_tickets) == 1
    assert final_tickets[0]["roi_est"] == 0.7  # Should pick the best ROI
    assert "Profitable TRIO combo found" in analysis_messages[0]


# --- Tests for _finalize_and_decide ---


def test_finalize_and_decide_no_tickets(mock_gpi_config):
    result = _finalize_and_decide([], mock_gpi_config["roi_min_global"], [])
    assert "Abstain: No valid tickets found" == result["gpi_decision"]
    assert not result["tickets"]
    assert result["roi_global_est"] == 0


def test_finalize_and_decide_low_global_roi(mock_gpi_config):
    final_tickets = [{"stake": 10.0, "roi_est": 0.1}]
    mock_gpi_config["roi_min_global"] = 0.5  # Ensure it's higher than actual ROI
    result = _finalize_and_decide(final_tickets, mock_gpi_config["roi_min_global"], [])
    assert "Abstain: Global ROI" in result["gpi_decision"]
    assert not result["tickets"]
    assert result["roi_global_est"] == 0.1


def test_finalize_and_decide_play(mock_gpi_config):
    final_tickets = [{"stake": 10.0, "roi_est": 0.3}]
    mock_gpi_config["roi_min_global"] = 0.2
    result = _finalize_and_decide(final_tickets, mock_gpi_config["roi_min_global"], ["Message 1"])
    assert "Play" == result["gpi_decision"]
    assert result["tickets"] == final_tickets
    assert result["roi_global_est"] == 0.3
    assert "Message 1" in result["message"]


# --- Tests for generate_tickets reporting ---


def test_generate_tickets_populates_top5_pronostic(
    mock_snapshot_data, mock_gpi_config, mocker: MockerFixture
):
    # Mock internal calls to simplify and control flow
    mocker.patch(
        "hippique_orchestrator.pipeline_run._initialize_and_validate",
        return_value=(mock_snapshot_data["runners"], mock_gpi_config),
    )
    mocker.patch(
        "hippique_orchestrator.pipeline_run._calculate_adjusted_probabilities",
        return_value=(mock_snapshot_data["runners"], []),
    )
    mocker.patch(
        "hippique_orchestrator.pipeline_run._generate_sp_dutching_tickets",
        return_value=(mock_snapshot_data["runners"], [], []),
    )
    mocker.patch(
        "hippique_orchestrator.pipeline_run._generate_exotic_tickets", return_value=([], [])
    )
    mocker.patch(
        "hippique_orchestrator.pipeline_run._finalize_and_decide",
        return_value={"gpi_decision": "Play", "tickets": [], "roi_global_est": 0.3, "message": ""},
    )

    # Ensure p_finale is set for sorting
    mock_snapshot_data["runners"][0]["p_finale"] = 0.5
    mock_snapshot_data["runners"][1]["p_finale"] = 0.1
    mock_snapshot_data["runners"][2]["p_finale"] = 0.8
    mock_snapshot_data["runners"][3]["p_finale"] = 0.2

    result = generate_tickets(mock_snapshot_data, mock_gpi_config)
    assert "top5_pronostic" in result
    assert len(result["top5_pronostic"]) == 4  # Only 4 runners in this mock
    assert result["top5_pronostic"][0]["nom"] == "Horse C"
    assert result["top5_pronostic"][0]["rank"] == 1


def test_generate_tickets_populates_market_analysis_table(
    mock_snapshot_data, mock_gpi_config, mocker: MockerFixture
):
    mocker.patch(
        "hippique_orchestrator.pipeline_run._initialize_and_validate",
        return_value=(mock_snapshot_data["runners"], mock_gpi_config),
    )
    mocker.patch(
        "hippique_orchestrator.pipeline_run._calculate_adjusted_probabilities",
        return_value=(mock_snapshot_data["runners"], []),
    )
    mocker.patch(
        "hippique_orchestrator.pipeline_run._generate_sp_dutching_tickets",
        return_value=(mock_snapshot_data["runners"], [], []),
    )
    mocker.patch(
        "hippique_orchestrator.pipeline_run._generate_exotic_tickets", return_value=([], [])
    )
    mocker.patch(
        "hippique_orchestrator.pipeline_run._finalize_and_decide",
        return_value={"gpi_decision": "Play", "tickets": [], "roi_global_est": 0.3, "message": ""},
    )

    # Ensure drift info is available
    mock_snapshot_data["runners"][0]["drift_percent"] = 5.0
    mock_snapshot_data["runners"][0]["drift_status"] = "Steam"

    result = generate_tickets(mock_snapshot_data, mock_gpi_config)
    assert "market_analysis_table" in result
    assert len(result["market_analysis_table"]) == 4
    assert result["market_analysis_table"][0]["nom"] == "Horse A"
    assert result["market_analysis_table"][0]["drift_status"] == "Steam"


def test_calculate_adjusted_probabilities_p_base_value_error(mock_gpi_config):
    # Simulate a runner with no valid odds_place or odds_win
    # Create a clean runners list for this specific test
    runners_for_test = [
        {"num": 1, "nom": "Horse A", "odds_win": None, "odds_place": None},
        {"num": 2, "nom": "Horse B", "odds_win": 8.0, "odds_place": 3.0},
    ]

    with pytest.raises(ValueError, match="Missing valid base probabilities for runner 1"):
        _calculate_adjusted_probabilities(runners_for_test, mock_gpi_config)
