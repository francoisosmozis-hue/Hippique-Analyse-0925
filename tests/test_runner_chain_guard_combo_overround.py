import json

import pytest

from pipeline_run import run_pipeline


@pytest.fixture
def course_with_high_overround(tmp_path):
    """Crée une configuration de course avec un overround élevé."""
    course_dir = tmp_path / "R1C1"
    course_dir.mkdir()
    partants_path = course_dir / "partants.json"

    # Overround = 1/1.5 + 1/1.5 = 0.666... + 0.666... = 1.333... > 1.3
    partants_data = {
        "runners": [
            {"num": "1", "odds": 1.5},
            {"num": "2", "odds": 1.5},
        ],
        "market": {
            "discipline": "Trot",
            "n_partants": 2,
        },
    }
    partants_path.write_text(json.dumps(partants_data))
    return course_dir


def test_pipeline_rejects_on_high_overround(course_with_high_overround):
    """
    Vérifie que le pipeline rejette la course si l'overround du marché
    dépasse le seuil configuré.
    """
    outdir = course_with_high_overround / "out"
    outdir.mkdir()

    # Appeler le pipeline avec les chemins des fichiers de test
    result = run_pipeline(
        partants=str(course_with_high_overround / "partants.json"),
        outdir=str(outdir),
    )

    # Vérifier les métriques de sortie
    metrics = result.get("metrics", {})

    # La raison de l'abstention doit être l'overround élevé
    assert "overround_above_threshold" in metrics.get("abstention_reasons", [])

    # Le statut global doit être "abstain"
    assert metrics.get("status") == "abstain"

    # La décision pour les combos doit refléter le rejet pour cause d'overround
    combo_decision = metrics.get("combo", {}).get("decision")
    assert combo_decision == "reject:overround_above_threshold"

    # Vérifier que p_finale.json ne contient aucun ticket
    p_finale_path = outdir / "p_finale.json"
    assert p_finale_path.exists()
    p_finale_data = json.loads(p_finale_path.read_text())
    assert p_finale_data.get("tickets") == []
