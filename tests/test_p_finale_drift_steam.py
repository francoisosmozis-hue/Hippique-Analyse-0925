import pytest

# TODO: Réécrire ce test pour utiliser la nouvelle logique de p_true dans ev_calculator.py
@pytest.mark.skip(reason="La fonction apply_drift_steam a été supprimée après refactoring.")
def test_apply_drift_steam_bonus():
    p0 = 0.20
    p = apply_drift_steam(p0, "3", {"3": 0.30}, {"3": 0.25}, fav30=None)
    assert p > p0


def test_apply_drift_steam_malus_fav30():
    p0 = 0.30
    p = apply_drift_steam(p0, "1", {"1": 0.20}, {"1": 0.26}, fav30="1")
    assert p < p0


def test_apply_drift_steam_neutre():
    p0 = 0.15
    p = apply_drift_steam(p0, "7", {"7": 0.18}, {"7": 0.17}, fav30="1")
    assert abs(p - p0) < 1e-12
