
import pytest
from src import analysis_utils

@pytest.mark.parametrize(
    "value, expected",
    [
        (None, ""),
        ("  Écurie Spéciale  ", "ecurie speciale"),
        ("  ", ""),
        ("TROT", "trot"),
        ("handicap", "handicap"),
    ],
)
def test_normalise_text(value, expected):
    assert analysis_utils._normalise_text(value) == expected

@pytest.mark.parametrize(
    "value, expected",
    [
        (14, 14),
        (14.0, 14),
        ("14 partants", 14),
        ("environ 14", 14),
        (None, None),
        (True, None),
        ("N/A", None),
        (-5, None),
    ],
)
def test_coerce_partants(value, expected):
    assert analysis_utils._coerce_partants(value) == expected

def test_compute_overround_cap_default():
    """Tests that the default cap is returned when no special conditions apply."""
    cap = analysis_utils.compute_overround_cap("Trot", 10, default_cap=1.5)
    assert cap == 1.5

def test_compute_overround_cap_flat_handicap_large_field():
    """Tests that the special cap is applied for large flat handicap races."""
    cap = analysis_utils.compute_overround_cap("Plat Handicap", 16, default_cap=1.5)
    assert cap == analysis_utils._FLAT_HANDICAP_CAP

def test_compute_overround_cap_flat_large_field_from_label():
    """Tests that the special cap is applied for large flat races identified by label."""
    cap = analysis_utils.compute_overround_cap("Plat", 14, default_cap=1.5, course_label="Grand Handicap de Deauville")
    assert cap == analysis_utils._FLAT_HANDICAP_CAP

def test_compute_overround_cap_small_field_uses_default():
    """Tests that the default cap is used for small handicap races."""
    cap = analysis_utils.compute_overround_cap("Plat Handicap", 13, default_cap=1.5)
    assert cap == 1.5

def test_compute_overround_cap_updates_context():
    """Tests that the context dictionary is updated when a special cap is triggered."""
    context = {}
    analysis_utils.compute_overround_cap(
        "Plat", 15, default_cap=1.5, course_label="Prix du Jockey Club", context=context
    )
    assert context["triggered"] is True
    assert context["reason"] == "flat_large_field"
    assert context["partants"] == 15
    assert context["default_cap"] == 1.5
