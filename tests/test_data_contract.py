import datetime
from hippique_orchestrator.data_contract import (
    RaceData,
    RunnerData,
    RaceSnapshotNormalized,
    calculate_quality_score,
)

# Fonctions utilitaires pour créer des données de test
def create_test_runner(
    num: int, with_odds: bool = True, with_musique: bool = True, with_stats: bool = False
) -> RunnerData:
    runner = RunnerData(
        num=num,
        name=f"Cheval {num}",
        odds_place=1.5 + num * 0.1 if with_odds else None,
        musique="1p2p3p" if with_musique else None,
    )
    if with_stats:
        runner.stats.driver_rate = 0.15
        runner.stats.trainer_rate = 0.20
    return runner


def create_test_snapshot(
    num_runners: int,
    runners_with_odds: int,
    runners_with_musique: int,
    runners_with_stats: int = 0,
) -> RaceSnapshotNormalized:
    
    runners = []
    for i in range(1, num_runners + 1):
        has_odds = i <= runners_with_odds
        has_musique = i <= runners_with_musique
        has_stats = i <= runners_with_stats
        runners.append(
            create_test_runner(i, with_odds=has_odds, with_musique=has_musique, with_stats=has_stats)
        )

    return RaceSnapshotNormalized(
        race=RaceData(
            date=datetime.date.today(),
            rc_label="R1C1",
            discipline="Trot Attelé",
        ),
        runners=runners,
        source_snapshot="test_provider",
    )


def test_quality_score_ok():
    """
    Scénario idéal : toutes les données sont présentes, y compris les stats.
    Le score doit être 1.0 et le statut 'OK'.
    """
    snapshot = create_test_snapshot(
        num_runners=10, runners_with_odds=10, runners_with_musique=10, runners_with_stats=10
    )
    quality = calculate_quality_score(snapshot)
    
    assert quality["score"] == 1.0
    assert quality["status"] == "OK"

    assert quality["score"] >= 0.85 # (0.6 * 1.0) + (0.2 * 1.0) = 0.8

def test_quality_score_degraded_missing_odds():
    """
    Scénario dégradé : il manque des cotes, qui ont le plus de poids.
    Le statut doit être 'DEGRADED'.
    """
    # 7/10 runners have odds, 10/10 have musique.
    # Score = 0.6 * 0.7 + 0.2 * 1.0 = 0.42 + 0.2 = 0.62
    snapshot = create_test_snapshot(num_runners=10, runners_with_odds=7, runners_with_musique=10)
    quality = calculate_quality_score(snapshot)
    
    assert quality["status"] == "DEGRADED"
    assert 0.5 <= quality["score"] < 0.85

def test_quality_score_failed_too_many_missing_odds():
    """
    Scénario échoué : trop de données critiques (cotes) sont manquantes.
    Le statut doit être 'FAILED'.
    """
    # 4/10 runners have odds, 10/10 have musique
    # Score = 0.6 * 0.4 + 0.2 * 1.0 = 0.24 + 0.2 = 0.44
    snapshot = create_test_snapshot(num_runners=10, runners_with_odds=4, runners_with_musique=10)
    quality = calculate_quality_score(snapshot)
    
    assert quality["status"] == "FAILED"
    assert quality["score"] < 0.5

def test_quality_score_failed_no_runners():
    """
    Scénario échoué : le snapshot n'a pas de partants.
    """
    snapshot = RaceSnapshotNormalized(
        race=RaceData(date=datetime.date.today(), rc_label="R1C1"),
        runners=[],
        source_snapshot="test_provider",
    )
    quality = calculate_quality_score(snapshot)
    
    assert quality["status"] == "FAILED"
    assert quality["score"] == 0.0

def test_quality_score_degraded_missing_musique():
    """
    Scénario dégradé : il manque des données secondaires (musique).
    Le statut doit être 'DEGRADED' mais le score reste acceptable.
    """
    # 10/10 runners have odds, 5/10 have musique
    # Score = 0.6 * 1.0 + 0.2 * 0.5 = 0.6 + 0.1 = 0.7
    snapshot = create_test_snapshot(num_runners=10, runners_with_odds=10, runners_with_musique=5)
    quality = calculate_quality_score(snapshot)
    
    assert quality["status"] == "DEGRADED"
    assert 0.5 <= quality["score"] < 0.85
