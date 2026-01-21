"""
Tests for the analysis pipeline's drift calculation and quality gates.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import date, datetime

from hippique_orchestrator.analysis_pipeline import run_analysis_for_race
from hippique_orchestrator.providers.base import Provider
from hippique_orchestrator.contracts.models import Race, Runner, OddsSnapshot, GPIOutput

# A concrete, minimal mock provider for testing purposes
class MockProvider(Provider):
    def __init__(self):
        self.mock_data = {}

    @property
    def name(self) -> str:
        return "MockProvider"

    def set_mock_data(self, phase: str, runners: list[Runner], snapshot: OddsSnapshot):
        self.mock_data[phase] = (runners, snapshot)

    def fetch_programme(self, for_date: date) -> list[Race]:
        return []

    def fetch_race_details(self, race: Race, phase: str) -> tuple[list[Runner], OddsSnapshot | None]:
        return self.mock_data.get(phase, ([], None))
    
    # Required abstract methods
    def get_programme_for_date(self, for_date: date) -> dict:
        return {}
    
    def fetch_race_page_content(self, race_url: str) -> str:
        return ""


@pytest.fixture
def sample_race():
    """Provides a default Race object for tests."""
    return Race(
        race_uid="TEST_R1C1",
        meeting_ref="TEST_M1",
        race_number=1,
        scheduled_time_local=datetime.now(),
        discipline="Plat",
        distance_m=2400,
        runners_count=3
    )

@pytest.fixture
def sample_runners(sample_race):
    """Provides a default list of Runner objects."""
    return [
        Runner(runner_uid="R1C1-1", race_uid=sample_race.race_uid, program_number=1, name_norm="HORSE A"),
        Runner(runner_uid="R1C1-2", race_uid=sample_race.race_uid, program_number=2, name_norm="HORSE B"),
        Runner(runner_uid="R1C1-3", race_uid=sample_race.race_uid, program_number=3, name_norm="HORSE C"),
    ]

def test_run_analysis_for_race_calculates_drift(sample_race, sample_runners):
    """
    Ensures the pipeline correctly calculates drift between H-30 and H-5 snapshots.
    """
    # 1. Setup
    provider = MockProvider()
    gpi_config = {"budget": 10} # Minimal config

    # H-30 Snapshot
    h30_snapshot = OddsSnapshot(
        snapshot_uid="SNAP_H30",
        race_uid=sample_race.race_uid,
        source="TestProvider",
        phase="H30",
        odds_place={
            "R1C1-1": 3.0,
            "R1C1-2": 8.0,
            "R1C1-3": 12.0
        }
    )
    provider.set_mock_data("H30", sample_runners, h30_snapshot)

    # H-5 Snapshot
    h5_snapshot = OddsSnapshot(
        snapshot_uid="SNAP_H5",
        race_uid=sample_race.race_uid,
        source="TestProvider",
        phase="H5",
        odds_place={
            "R1C1-1": 3.2,  # Drifted
            "R1C1-2": 5.5,  # Drifted significantly
            "R1C1-3": 12.0 # Stable
        }
    )
    provider.set_mock_data("H5", sample_runners, h5_snapshot)
    
    # Mock quality gate and legacy GPI logic to isolate drift calculation
    with patch("hippique_orchestrator.analysis_pipeline.is_playable", return_value=(True, [])), \
         patch("hippique_orchestrator.analysis_pipeline.legacy_gpi_logic", return_value={"gpi_decision": "Play"}):
        # 2. Execute
        result: GPIOutput = run_analysis_for_race(sample_race, provider, gpi_config)

    # 3. Assert
    assert result.playable is True
    assert result.derived_data is not None
    assert result.derived_data.drift is not None
    
    # Check drift values (floats require approx)
    assert result.derived_data.drift["R1C1-1"] == pytest.approx(3.2 - 3.0)
    assert result.derived_data.drift["R1C1-2"] == pytest.approx(5.5 - 8.0)
    assert result.derived_data.drift["R1C1-3"] == pytest.approx(12.0 - 12.0)
    assert len(result.derived_data.drift) == 3


def test_run_analysis_abstains_if_data_is_missing(sample_race):
    """
    Ensures the pipeline abstains when the provider fails to return data.
    """
    # 1. Setup
    provider = MockProvider() # No data is set
    gpi_config = {}

    # 2. Execute
    result: GPIOutput = run_analysis_for_race(sample_race, provider, gpi_config)

    # 3. Assert
    assert result.playable is False
    assert result.abstention_reasons is not None
    # We expect the quality gate to be the reason for abstention
    assert any("no_data_collected" in reason for reason in result.abstention_reasons)
    assert result.derived_data is None # No data, no drift


def test_run_analysis_abstains_if_quality_gate_fails(sample_race, sample_runners):
    """
    Ensures the pipeline abstains if the quality gate explicitly fails,
    even if data is present.
    """
    # 1. Setup
    provider = MockProvider()
    gpi_config = {}
    
    # Provide H5 data, but the quality gate will fail it
    h5_snapshot = OddsSnapshot(
        snapshot_uid="SNAP_H5",
        race_uid=sample_race.race_uid,
        source="TestProvider",
        phase="H5",
        odds_place={"R1C1-1": 3.2}
    )
    provider.set_mock_data("H5", sample_runners, h5_snapshot)

    # Mock the quality gate to fail
    with patch("hippique_orchestrator.analysis_pipeline.is_playable", return_value=(False, ["custom_reason"])):
        # 2. Execute
        result: GPIOutput = run_analysis_for_race(sample_race, provider, gpi_config)

    # 3. Assert
    assert result.playable is False
    assert result.abstention_reasons == ["custom_reason"]
