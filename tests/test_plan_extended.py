from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest

from hippique_orchestrator import plan
from hippique_orchestrator.data_contract import Programme, Race


@pytest.mark.asyncio
@patch("hippique_orchestrator.plan.run_in_threadpool", new_callable=AsyncMock)
async def test_build_plan_handles_various_invalid_rc_formats(mock_run_in_threadpool, caplog):
    """
    Tests that various invalid RC formats are skipped.
    """
    # Arrange
    mock_programme_data = Programme(
        date=date(2025, 12, 20),
        races=[
            Race(
                race_id="R1C1_invalid_rc1",
                rc="R C",
                name="Invalid RC 1",
                start_time="10:00",
                url="http://example.com/r1c1",
                reunion_id=1,
                course_id=1,
                hippodrome="TEST",
                country_code="FR",
                date=date(2025, 12, 20),
            ),
            Race(
                race_id="R1C2_invalid_rc2",
                rc="R1C",
                name="Invalid RC 2",
                start_time="11:00",
                url="http://example.com/r1c2",
                reunion_id=1,
                course_id=2,
                hippodrome="TEST",
                country_code="FR",
                date=date(2025, 12, 20),
            ),
            Race(
                race_id="R1C3_invalid_rc3",
                rc="RC1",
                name="Invalid RC 3",
                start_time="12:00",
                url="http://example.com/r1c3",
                reunion_id=1,
                course_id=3,
                hippodrome="TEST",
                country_code="FR",
                date=date(2025, 12, 20),
            ),
            Race(
                race_id="R1C4_valid_rc",
                rc="R1 C1",
                name="Valid RC",
                start_time="13:00",
                url="http://example.com/r1c4",
                reunion_id=1,
                course_id=4,
                hippodrome="TEST",
                country_code="FR",
                date=date(2025, 12, 20),
            ),
        ],
    )
    mock_run_in_threadpool.return_value = mock_programme_data

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    assert len(result_plan) == 1
    assert result_plan[0]["r_label"] == "R1"
    assert result_plan[0]["c_label"] == "C1"


@pytest.mark.asyncio
@patch("hippique_orchestrator.plan.run_in_threadpool", new_callable=AsyncMock)
async def test_build_plan_data_types(mock_run_in_threadpool):
    """
    Tests that the data types in the returned plan are correct.
    """
    # Arrange
    mock_programme_data = Programme(
        date=date(2025, 12, 20),
        races=[
            Race(
                race_id="R1C1",
                rc="R1 C1",
                name="Test Race",
                start_time="10:00",
                url="http://example.com/r1c1",
                runners_count="10",  # runners_count is a string
                reunion_id=1,
                course_id=1,
                hippodrome="TEST",
                country_code="FR",
                date=date(2025, 12, 20),
            )
        ],
    )
    mock_run_in_threadpool.return_value = mock_programme_data

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    assert len(result_plan) == 1
    race = result_plan[0]
    assert isinstance(race["r_label"], str)
    assert isinstance(race["c_label"], str)
    assert isinstance(race["time_local"], str)
    assert race["date"] == date(2025, 12, 20).isoformat()
    assert isinstance(race["course_url"], str)
    assert isinstance(race["partants"], int)
    assert race["partants"] == 10


@pytest.mark.asyncio
@patch("hippique_orchestrator.plan.run_in_threadpool", new_callable=AsyncMock)
async def test_build_plan_invalid_runners_count(mock_run_in_threadpool):
    """
    Tests that `partants` is None when `runners_count` is not a valid integer.
    """
    # Arrange
    mock_programme_data = Programme(
        date=date(2025, 12, 20),
        races=[
            Race(
                race_id="R1C1",
                rc="R1 C1",
                name="Test Race",
                start_time="10:00",
                url="http://example.com/r1c1",
                runners_count="N/A",
                reunion_id=1,
                course_id=1,
                hippodrome="TEST",
                country_code="FR",
                date=date(2025, 12, 20),
            )
        ],
    )
    mock_run_in_threadpool.return_value = mock_programme_data

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    assert len(result_plan) == 1
    assert result_plan[0]["partants"] is None


@pytest.mark.asyncio
@patch("hippique_orchestrator.plan.run_in_threadpool", new_callable=AsyncMock)
async def test_build_plan_mandatory_keys(mock_run_in_threadpool):
    """
    Tests that all mandatory keys are present in the returned plan.
    """
    # Arrange
    mock_programme_data = Programme(
        date=date(2025, 12, 20),
        races=[
            Race(
                race_id="R1C1",
                rc="R1 C1",
                name="Test Race",
                start_time="10:00",
                url="http://example.com/r1c1",
                runners_count="10",
                reunion_id=1,
                course_id=1,
                hippodrome="TEST",
                country_code="FR",
                date=date(2025, 12, 20),
            )
        ],
    )
    mock_run_in_threadpool.return_value = mock_programme_data

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    assert len(result_plan) == 1
    race = result_plan[0]
    mandatory_keys = ["r_label", "c_label", "time_local", "date", "course_url", "partants"]
    for key in mandatory_keys:
        assert key in race
