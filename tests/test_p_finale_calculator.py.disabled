import pytest

from hippique_orchestrator.pipeline_run import calculate_p_finale


@pytest.fixture
def gpi_weights():
    """Provides a sample weights configuration from gpi_v52.yml."""
    return {
        "base": {
            "je_bonus": 1.10,  # Use a distinct value for testing
            "je_malus": 0.90
        }
    }

def test_p_finale_applies_je_bonus(gpi_weights):
    """
    Tests that p_finale is increased when jockey or trainer stats are high.
    """
    p_base = 0.20
    # Case 1: Jockey rate is high
    runner_stats_jockey_bonus = {"j_rate": "15.0", "e_rate": "10.0"}
    p_final = calculate_p_finale(p_base, runner_stats_jockey_bonus, gpi_weights)
    assert p_final == pytest.approx(p_base * 1.10)

    # Case 2: Trainer rate is high
    runner_stats_trainer_bonus = {"j_rate": "10.0", "e_rate": "20.0"}
    p_final = calculate_p_finale(p_base, runner_stats_trainer_bonus, gpi_weights)
    assert p_final == pytest.approx(p_base * 1.10)

def test_p_finale_applies_je_malus(gpi_weights):
    """
    Tests that p_finale is decreased when jockey and trainer stats are low.
    """
    p_base = 0.20
    # Both j_rate and e_rate are low
    runner_stats = {"j_rate": "5.0", "e_rate": "7.0"}
    p_final = calculate_p_finale(p_base, runner_stats, gpi_weights)
    assert p_final == pytest.approx(p_base * 0.90)

def test_p_finale_no_change_if_stats_are_average(gpi_weights):
    """
    Tests that p_finale does not change if stats are in the neutral zone.
    """
    p_base = 0.20
    runner_stats = {"j_rate": "10.0", "e_rate": "10.0"} # Neutral values
    p_final = calculate_p_finale(p_base, runner_stats, gpi_weights)
    assert p_final == pytest.approx(p_base)

def test_p_finale_handles_missing_stats(gpi_weights):
    """
    Tests that p_finale does not change if stats are missing.
    """
    p_base = 0.20
    # Case 1: Empty stats dict
    p_final = calculate_p_finale(p_base, {}, gpi_weights)
    assert p_final == pytest.approx(p_base)

    # Case 2: Stats are None
    runner_stats_none = {"j_rate": None, "e_rate": None}
    p_final = calculate_p_finale(p_base, runner_stats_none, gpi_weights)
    assert p_final == pytest.approx(p_base)

    # Case 3: Malformed stats
    runner_stats_malformed = {"j_rate": "N/A", "e_rate": "10.0"}
    p_final = calculate_p_finale(p_base, runner_stats_malformed, gpi_weights)
    assert p_final == pytest.approx(p_base)

def test_p_finale_caps_at_max_value(gpi_weights):
    """
    Tests that the final probability is capped at 0.99 for safety.
    """
    p_base = 0.95
    runner_stats = {"j_rate": "20.0", "e_rate": "20.0"} # Trigger bonus
    p_final = calculate_p_finale(p_base, runner_stats, gpi_weights)
    assert p_final == 0.99
