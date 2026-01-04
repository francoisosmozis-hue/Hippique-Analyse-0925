import pytest
from unittest.mock import patch
from hippique.analytics.roi_rebalancer import RaceMetrics
from hippique_orchestrator import p_finale

@pytest.fixture
def sample_gpi_config():
    """Provides a sample GPI configuration for testing."""
    return {
        "adjustments": {
            "drift": {
                "threshold": 0.05,
                "favorite_odds": 3.0,
                "favorite_factor": 1.2,
                "outsider_odds": 7.0,
                "outsider_steam_factor": 0.8,
                "k_d": 0.7,
                "k_d_fav_drift": 0.9,
                "k_d_out_steam": 0.85,
                "F_STEAM": 1.03,
                "F_DRIFT_FAV": 0.97,
                "DRIFT_DELTA": 0.04
            }
        }
    }

@pytest.fixture
def sample_runners_data():
    """Provides a sample list of runner dictionaries."""
    return [
        {"num": 1, "nom": "Horse A", "odds": 5.0, "p_finale": 0.4},
        {"num": 2, "nom": "Horse B", "odds": 8.0, "p_finale": 0.2},
        {"num": 3, "nom": "Horse C", "odds": 12.0, "p_finale": 0.1},
    ]

@pytest.mark.parametrize(
    "p_val, num, p5_map, p30_map, fav30, expected",
    [
        (0.5, 1, {"1": 0.5}, {"1": 0.4}, 2, 0.5 * 1.03),  # Steam
        (0.5, 1, {"1": 0.4}, {"1": 0.5}, 1, 0.5 * 0.97),  # Drift on favorite
        (0.5, 1, {"1": 0.4}, {"1": 0.5}, 2, 0.5),          # Drift on non-favorite
        (0.5, 1, {"1": 0.4}, {"1": 0.4}, 1, 0.5),          # No change
        (0.5, 1, None, {"1": 0.4}, 1, 0.5),               # Missing p5_map
        (0.5, 1, {"1": 0.4}, None, 1, 0.5),               # Missing p30_map
        (None, 1, {"1": 0.4}, {"1": 0.4}, 1, 0.0),        # p_val is None
    ],
)
def test_apply_drift_steam(p_val, num, p5_map, p30_map, fav30, expected):
    """Tests the apply_drift_steam function with various scenarios."""
    adjusted_p = p_finale.apply_drift_steam(p_val, num, p5_map, p30_map, fav30)
    assert adjusted_p == pytest.approx(expected)

def test_generate_p_finale_data_basic(sample_runners_data, sample_gpi_config):
    """
    Tests basic functionality of generate_p_finale_data, including the call to apply_drift_steam.
    """
    analysis_data = {"runners": sample_runners_data}
    p30_map = {"1": 0.35, "2": 0.2, "3": 0.1}
    p5_map = {"1": 0.45, "2": 0.15, "3": 0.1} # Horse A steams, Horse B drifts
    fav30 = "1"

    processed_runners = p_finale.generate_p_finale_data(
        analysis_data, p30_map, p5_map, fav30
    )

    assert len(processed_runners) == 3
    
    # Check Horse A (steam)
    assert processed_runners[0]['p_finale'] == pytest.approx(0.4 * 1.03) 
    
    # Check Horse B (drift but not favorite)
    assert processed_runners[1]['p_finale'] == pytest.approx(0.2)
    
    # Check Horse C (no change)
    assert processed_runners[2]['p_finale'] == pytest.approx(0.1)

def test_generate_p_finale_data_empty_runners():
    """Tests that generate_p_finale_data returns an empty list if there are no runners."""
    processed_runners = p_finale.generate_p_finale_data({})
    assert processed_runners == []

def test_generate_p_finale_data_no_drift_config(sample_runners_data):
    """Tests that no drift/steam is applied if maps are not provided."""
    analysis_data = {"runners": sample_runners_data}
    
    # No drift maps provided
    processed_runners = p_finale.generate_p_finale_data(analysis_data)
    
    assert len(processed_runners) == 3
    assert processed_runners[0]['p_finale'] == 0.4
    assert processed_runners[1]['p_finale'] == 0.2
    assert processed_runners[2]['p_finale'] == 0.1