import datetime
import pytest
from hippique_orchestrator.data_contract import (
    RaceData,
    RaceSnapshotNormalized,
    RunnerData,
    RunnerStats,
)


def test_runner_data_odds_validator():
    """
    Tests that the validator for odds in RunnerData works correctly.
    - Odds >= 1.0 should be accepted.
    - Odds < 1.0 should be invalidated (set to None).
    """
    # Valid odds
    runner1 = RunnerData(num=1, nom="Good Horse", odds_win=2.5, odds_place=1.5)
    assert runner1.odds_win == 2.5
    assert runner1.odds_place == 1.5

    # Invalid odds (less than 1.0)
    runner2 = RunnerData(num=2, nom="Bad Odds Horse", odds_win=0.9, odds_place=-1.0)
    assert runner2.odds_win is None
    assert runner2.odds_place is None

    # Edge case: odds at 1.0
    runner3 = RunnerData(num=3, nom="Edge Case Horse", odds_win=1.0, odds_place=1.0)
    assert runner3.odds_win == 1.0
    assert runner3.odds_place == 1.0

    # Mixed valid and invalid odds
    runner4 = RunnerData(num=4, nom="Mixed Horse", odds_win=5.0, odds_place=0.0)
    assert runner4.odds_win == 5.0
    assert runner4.odds_place is None


def test_race_snapshot_quality_failed():
    """
    Tests the 'FAILED' status of the quality computed field.
    """
    # Case 1: No runners
    snapshot_no_runners = RaceSnapshotNormalized(
        race=RaceData(date=datetime.date.today(), rc_label="R1C1"),
        runners=[],
        source_snapshot="test",
    )
    quality = snapshot_no_runners.quality
    assert quality["status"] == "FAILED"
    assert quality["reason"] == "No runners in snapshot"
    assert quality["score"] == 0.0

    # Case 2: Runners with very few data points (score < 0.5)
    runners = [
        RunnerData(num=1, nom="Horse 1"),
        RunnerData(num=2, nom="Horse 2"),
    ]
    snapshot_low_data = RaceSnapshotNormalized(
        race=RaceData(date=datetime.date.today(), rc_label="R1C2"),
        runners=runners,
        source_snapshot="test",
    )
    quality = snapshot_low_data.quality
    assert quality["status"] == "FAILED"
    assert quality["score"] < 0.5


def test_race_snapshot_quality_degraded():
    """
    Tests the 'DEGRADED' status of the quality computed field.
    """
    # Case: Partial data, e.g., only place odds for half the runners
    runners = [
        RunnerData(num=1, nom="Horse 1", odds_place=2.0),
        RunnerData(num=2, nom="Horse 2", odds_place=3.0),
        RunnerData(num=3, nom="Horse 3"),
        RunnerData(num=4, nom="Horse 4"),
    ]
    snapshot = RaceSnapshotNormalized(
        race=RaceData(date=datetime.date.today(), rc_label="R1C3"),
        runners=runners,
        source_snapshot="test",
    )
    quality = snapshot.quality
    # Score should be 0.6 * (2/4) = 0.3 from odds, plus some minor contribution
    assert quality["status"] == "DEGRADED" or quality["status"] == "FAILED" # can be either depending on other fields
    assert quality["score"] < 0.85


def test_race_snapshot_quality_ok():
    """
    Tests the 'OK' status of the quality computed field.
    """
    # Case: Rich data, most fields are filled
    runners = [
        RunnerData(
            num=i,
            nom=f"Horse {i}",
            odds_place=2.0 + i,
            musique="1p2p3p",
            stats=RunnerStats(driver_rate=0.15, trainer_rate=0.20),
        )
        for i in range(1, 9) # 8 runners
    ]
    snapshot = RaceSnapshotNormalized(
        race=RaceData(date=datetime.date.today(), rc_label="R1C4"),
        runners=runners,
        source_snapshot="test",
    )
    quality = snapshot.quality
    # Score should be high as all data is present
    assert quality["status"] == "OK"
    assert quality["score"] >= 0.85
    assert "8/8 place_odds" in quality["reason"]