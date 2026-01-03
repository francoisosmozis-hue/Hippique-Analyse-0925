
from __future__ import annotations

import pytest
from hippique_orchestrator.p_finale import apply_drift_steam, generate_p_finale_data, F_STEAM, F_DRIFT_FAV

# --- Tests for apply_drift_steam ---

def test_apply_drift_steam_no_pval():
    """Should return 0.0 if p_val is None or 0.0."""
    assert apply_drift_steam(None, "1", {}, {}, "2") == 0.0
    assert apply_drift_steam(0.0, "1", {"1": 0.2}, {"1": 0.1}, "2") == 0.0

def test_apply_drift_steam_no_maps():
    """Should return original p_val if probability maps are missing."""
    assert apply_drift_steam(0.5, "1", None, None, "2") == 0.5
    assert apply_drift_steam(0.5, "1", {"1": 0.2}, None, "2") == 0.5
    assert apply_drift_steam(0.5, "1", None, {"1": 0.2}, "2") == 0.5

def test_apply_drift_steam_invalid_map_data():
    """Should return original p_val if map data is not a valid number."""
    p5_map = {"1": "invalid"}
    p30_map = {"1": 0.1}
    assert apply_drift_steam(0.5, "1", p5_map, p30_map, "2") == 0.5

def test_apply_drift_steam_applies_steam_bonus():
    """Should apply F_STEAM bonus when probability increases significantly."""
    p_val = 0.5
    p5_map = {"1": 0.2}
    p30_map = {"1": 0.1}  # Steam from 0.1 to 0.2
    assert apply_drift_steam(p_val, "1", p5_map, p30_map, "2") == pytest.approx(p_val * F_STEAM)

def test_apply_drift_steam_applies_drift_penalty_to_fav():
    """Should apply F_DRIFT_FAV penalty if the favorite's probability drops."""
    p_val = 0.5
    p5_map = {"1": 0.1}
    p30_map = {"1": 0.2}  # Drift from 0.2 to 0.1
    fav30 = "1"
    assert apply_drift_steam(p_val, "1", p5_map, p30_map, fav30) == pytest.approx(p_val * F_DRIFT_FAV)

def test_apply_drift_steam_no_penalty_for_drifting_non_favorite():
    """Should NOT apply penalty if a non-favorite drifts."""
    p_val = 0.5
    p5_map = {"2": 0.1}
    p30_map = {"2": 0.2}
    fav30 = "1" # Horse 2 is not the favorite
    assert apply_drift_steam(p_val, "2", p5_map, p30_map, fav30) == p_val

def test_apply_drift_steam_no_change_if_delta_not_met():
    """Should not change p_val if drift/steam is not significant."""
    p_val = 0.5
    # Steam not large enough
    assert apply_drift_steam(0.5, "1", {"1": 0.11}, {"1": 0.1}, "2") == p_val
    # Drift not large enough
    assert apply_drift_steam(0.5, "1", {"1": 0.1}, {"1": 0.11}, "1") == p_val


# --- Tests for generate_p_finale_data ---

@pytest.mark.parametrize("key", ["runners", "horses", "partants"])
def test_generate_p_finale_data_finds_runners_in_different_keys(key):
    """Test that it can find the list of runners under various common keys."""
    analysis_data = {key: [{"num": "1", "p_finale": 0.5}]}
    result = generate_p_finale_data(analysis_data)
    assert len(result) == 1
    assert result[0]["num"] == "1"

def test_generate_p_finale_data_empty_if_no_runners():
    """Should return an empty list if no runners list is found."""
    assert generate_p_finale_data({}) == []
    assert generate_p_finale_data({"runners": []}) == []

def test_generate_p_finale_data_extracts_all_fields_with_fallbacks():
    """Test extraction of all relevant fields, using fallbacks where needed."""
    analysis_data = {
        "runners": [
            {"num": "1", "nom": "A", "p_finale": 0.5, "odds": 2.0, "j_rate": 10},
            {"number": "2", "name": "B", "p": 0.3, "cote": 3.0, "jockey_rate": 12, "e_rate": 5},
            {"id": "3", "p_true": 0.2, "trainer_rate": 8},
        ]
    }
    result = generate_p_finale_data(analysis_data)
    assert len(result) == 3
    assert result[0] == {'num': '1', 'nom': 'A', 'p_finale': 0.5, 'odds': 2.0, 'j_rate': 10, 'e_rate': None}
    assert result[1] == {'num': '2', 'nom': 'B', 'p_finale': 0.3, 'odds': 3.0, 'j_rate': 12, 'e_rate': 5}
    assert result[2] == {'num': '3', 'nom': None, 'p_finale': 0.2, 'odds': None, 'j_rate': None, 'e_rate': 8}

def test_generate_p_finale_data_handles_non_dict_runners():
    """Should skip entries in the runners list that are not dictionaries."""
    analysis_data = {"runners": [{"num": "1"}, "not-a-dict", None]}
    result = generate_p_finale_data(analysis_data)
    assert len(result) == 1

def test_generate_p_finale_data_calls_apply_drift_steam():
    """Should apply drift/steam logic when probability maps are provided."""
    analysis_data = {"runners": [{"num": "1", "p_finale": 0.5}]}
    p5_map = {"1": 0.2}
    p30_map = {"1": 0.1}
    
    result = generate_p_finale_data(analysis_data, p30_map, p5_map, "2")
    assert len(result) == 1
    # Check that the steam bonus was applied
    assert result[0]["p_finale"] == pytest.approx(0.5 * F_STEAM)

def test_generate_p_finale_data_no_drift_call_if_maps_missing():
    """Should not attempt to apply drift if maps are not provided."""
    analysis_data = {"runners": [{"num": "1", "p_finale": 0.5}]}
    result = generate_p_finale_data(analysis_data)
    assert len(result) == 1
    assert result[0]["p_finale"] == 0.5  # Unchanged
