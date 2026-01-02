# tests/scripts/test_simulate_wrapper_script.py
import pytest
import yaml
import time
from unittest.mock import MagicMock
from pathlib import Path

from hippique_orchestrator.scripts import simulate_wrapper
from hippique_orchestrator.scripts.simulate_wrapper import _combo_key

# On réinitialise les caches globaux du module avant chaque test
@pytest.fixture(autouse=True)
def reset_wrapper_cache():
    simulate_wrapper._calibration_cache.clear()
    simulate_wrapper._calibration_mtime = 0.0
    simulate_wrapper._correlation_settings.clear()
    simulate_wrapper._correlation_mtime = 0.0

@pytest.fixture
def mock_fs(monkeypatch):
    """Fixture to robustly mock file system for calibration files."""
    files = {}

    class MockStat:
        def __init__(self, mtime):
            self.st_mtime = mtime

    def mock_stat(self, *args, **kwargs):
        path_str = str(self)
        if path_str in files:
            return MockStat(files[path_str]['mtime'])
        raise FileNotFoundError(path_str)

    def mock_open(self, mode='r', encoding=None):
        path_str = str(self)
        if path_str in files:
            from io import StringIO
            return StringIO(files[path_str]['content'])
        raise FileNotFoundError(path_str)

    monkeypatch.setattr(Path, "stat", mock_stat)
    monkeypatch.setattr(Path, "open", mock_open)

    # Permet aux tests de définir le contenu des fichiers
    def set_file(path, content, mtime=None):
        path_str = str(Path(path))
        files[path_str] = {
            'content': content,
            'mtime': mtime or time.time()
        }
    
    return set_file

def test_simulate_wrapper_uses_calibrated_probability(mock_fs):
    """
    Vérifie que simulate_wrapper retourne la probabilité du fichier de calibration
    lorsqu'une combinaison est trouvée.
    """
    combo_key = _combo_key([{"id": "1"}, {"id": "3"}])
    calib_data = {combo_key: {"p": 0.25}}
    mock_fs("calibration/probabilities.yaml", yaml.dump(calib_data))

    legs = [{"id": "1"}, {"id": "3"}]
    prob = simulate_wrapper.simulate_wrapper(legs)
    assert prob == 0.25

def test_simulate_wrapper_fallback_no_correlation(mock_fs):
    """
    Vérifie le fallback sur le produit des probabilités individuelles
    quand la combinaison n'est pas dans la calibration.
    """
    mock_fs("calibration/probabilities.yaml", yaml.dump({})) # Fichier vide
    mock_fs("config/payout_calibration.yaml", yaml.dump({})) # Fichier vide

    legs = [
        {"id": "1", "p": 0.5},
        {"id": "2", "p_true": 0.4},
        {"id": "3", "odds": 5.0}
    ]

    prob = simulate_wrapper.simulate_wrapper(legs)

    expected_prob = 0.5 * 0.4 * (1.0 / 5.0)
    assert prob == pytest.approx(expected_prob)
def test_correlation_penalty_defaults_gracefully(mock_fs):
    """
    Vérifie que la pénalité par défaut est utilisée si la calibration de gains est vide.
    """
    mock_fs("calibration/probabilities.yaml", yaml.dump({}))
    mock_fs("config/payout_calibration.yaml", yaml.dump({}))

    legs = [
        {"id": "1", "p": 0.5, "rc": "R1C1"},
        {"id": "2", "p": 0.4, "rc": "R1C1"}
    ]
    
    # On s'assure que le cache est vide et que la valeur par défaut sera utilisée
    simulate_wrapper._correlation_mtime = 0.0
    default_penalty = simulate_wrapper.CORRELATION_PENALTY

    prob = simulate_wrapper.simulate_wrapper(legs)
    
    base_prob = 0.5 * 0.4
    expected_prob = base_prob * default_penalty
    assert prob == pytest.approx(expected_prob)

def test_simulate_wrapper_applies_correlation_penalty(mock_fs):
    """
    Vérifie que la pénalité de corrélation est appliquée lorsque les 'legs'
    partagent un identifiant commun (ex: même course).
    """
    # 1. Fichier de calibration de probabilités vide pour forcer le calcul
    mock_fs("calibration/probabilities.yaml", yaml.dump({}))
    
    # 2. Fichier de calibration des gains avec une pénalité pour le type 'rc'
    payout_calib = {
        "correlations": {
            "rc": {"penalty": 0.7}
        }
    }
    mock_fs("config/payout_calibration.yaml", yaml.dump(payout_calib))

    # 3. 'legs' qui sont dans la même course "R1C1"
    legs = [
        {"id": "1", "p": 0.5, "rc": "R1C1"},
        {"id": "2", "p": 0.4, "rc": "R1C1"}
    ]

    # 4. Exécuter la fonction
    # On doit réinitialiser le cache de corrélation pour être sûr que le mock est lu
    simulate_wrapper._correlation_mtime = 0.0
    prob = simulate_wrapper.simulate_wrapper(legs)

    # 5. Vérifier le résultat
    base_prob = 0.5 * 0.4
    expected_prob_after_penalty = base_prob * 0.7
    assert prob == pytest.approx(expected_prob_after_penalty)
