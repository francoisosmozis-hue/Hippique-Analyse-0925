
import datetime
import pytest

from hippique_orchestrator.data_contract import (
    Race,
    Runner,
    Meeting,
    RaceSnapshot,
    QualityReport,
)

def test_runner_odds_validator():
    """
    Tests that the validator for odds in the new Runner model works correctly.
    """
    # Valid odds
    runner1 = Runner(num=1, nom="Good Horse", odds_win=2.5, odds_place=1.5)
    assert runner1.odds_win == 2.5
    assert runner1.odds_place == 1.5

    # Invalid odds (< 1.0) should be set to None
    runner2 = Runner(num=2, nom="Bad Odds Horse", odds_win=0.9, odds_place=-1.0)
    assert runner2.odds_win is None
    assert runner2.odds_place is None

    # Edge case: odds at 1.0
    runner3 = Runner(num=3, nom="Edge Case Horse", odds_win=1.0, odds_place=1.0)
    assert runner3.odds_win == 1.0
    assert runner3.odds_place == 1.0


def test_race_snapshot_quality_failed():
    """
    Tests the 'FAILED' status using the RaceSnapshot.from_race factory.
    """
    # Case 1: No runners
    race_no_runners = Race(
        race_id="R1C1",
        reunion_id=1,
        course_id=1,
        hippodrome="TEST",
        date=datetime.date.today(),
        runners=[],
    )
    snapshot = RaceSnapshot.from_race(race_no_runners, "test_provider")
    assert snapshot.quality.status == "FAILED"
    assert snapshot.quality.reason == "No runners in snapshot"
    assert snapshot.quality.score == 0.0

    # Case 2: Runners with very few data points (score < 0.4)
    race_low_data = Race(
        race_id="R1C2",
        reunion_id=1,
        course_id=2,
        hippodrome="TEST",
        date=datetime.date.today(),
        runners=[Runner(num=1, nom="Horse 1"), Runner(num=2, nom="Horse 2")],
    )
    snapshot_low_data = RaceSnapshot.from_race(race_low_data, "test_provider")
    assert snapshot_low_data.quality.status == "FAILED"
    assert snapshot_low_data.quality.score < 0.4


def test_race_snapshot_quality_degraded():
    """
    Tests the 'DEGRADED' status of the quality report.
    """
    # Case: Partial data, e.g., only odds for half the runners
    race = Race(
        race_id="R1C3",
        reunion_id=1,
        course_id=3,
        hippodrome="TEST",
        date=datetime.date.today(),
        runners=[
            Runner(num=1, nom="Horse 1", odds_win=2.0, odds_place=1.5),
            Runner(num=2, nom="Horse 2", odds_win=3.0, odds_place=1.8),
            Runner(num=3, nom="Horse 3", musique="1p2p"), # No odds
            Runner(num=4, nom="Horse 4", musique="3p4p"), # No odds
        ],
    )
    snapshot = RaceSnapshot.from_race(race, "test_provider")
    
    # Score should be 0.7 * (2/4) + 0.3 * (4/4) = 0.35 + 0.3 = 0.65
    assert snapshot.quality.status == "DEGRADED"
    assert snapshot.quality.score == 0.50
    assert "2/4 runners with complete odds" in snapshot.quality.reason


def test_race_snapshot_quality_ok():
    """
    Tests the 'OK' status of the quality report.
    """
    # Case: Rich data, most fields are filled
    race = Race(
        race_id="R1C4",
        reunion_id=1,
        course_id=4,
        hippodrome="TEST",
        date=datetime.date.today(),
        runners=[
            Runner(num=i, nom=f"Horse {i}", odds_win=2.0+i, odds_place=1.5+i, musique="1p2p3p")
            for i in range(1, 9)  # 8 runners
        ],
    )
    snapshot = RaceSnapshot.from_race(race, "test_provider")

    # Score should be high as all data is present
    # Score = 0.7 * (8/8) + 0.3 * (8/8) = 1.0
    assert snapshot.quality.status == "OK"
    assert snapshot.quality.score >= 0.8
    assert "8/8 runners with complete odds" in snapshot.quality.reason

def test_meeting_and_race_ids():
    """
    Tests the computed 'id' properties for Race and Meeting models.
    """
    the_date = datetime.date(2024, 5, 20)
    
    race = Race(
        race_id="R5C3",
        reunion_id=5,
        course_id=3,
        hippodrome="VINCENNES",
        country_code="FR",
        date=the_date,
    )
    assert race.id == "2024-05-20_R5C3"

    meeting = Meeting(
        hippodrome="SAINT-CLOUD",
        country_code="FR",
        date=the_date
    )
    assert meeting.id == "2024-05-20_SAINT-CLOUD"
