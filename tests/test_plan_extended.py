from unittest.mock import AsyncMock, patch

import pytest

from hippique_orchestrator import plan


@pytest.mark.asyncio
@patch("hippique_orchestrator.data_source.fetch_programme", new_callable=AsyncMock)
async def test_build_plan_handles_various_invalid_rc_formats(mock_fetch_programme, caplog):
    """
    Tests that various invalid RC formats are skipped.
    """
    # Arrange
    mock_programme_data = {
        "races": [
            {
                "rc": "R C",
                "name": "Invalid RC 1",
                "start_time": "10:00",
                "url": "http://example.com/r1c1",
            },
            {
                "rc": "R1C",
                "name": "Invalid RC 2",
                "start_time": "11:00",
                "url": "http://example.com/r1c2",
            },
            {
                "rc": "RC1",
                "name": "Invalid RC 3",
                "start_time": "12:00",
                "url": "http://example.com/r1c3",
            },
            {
                "rc": "R1 C1",
                "name": "Valid RC",
                "start_time": "13:00",
                "url": "http://example.com/r1c4",
            },
        ]
    }
    mock_fetch_programme.return_value = mock_programme_data

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    assert len(result_plan) == 1
    assert result_plan[0]["r_label"] == "R1"
    assert "Could not parse R/C from 'R C'" in caplog.text
    assert "Could not parse R/C from 'R1C'" in caplog.text
    assert "Could not parse R/C from 'RC1'" in caplog.text


@pytest.mark.asyncio
@patch("hippique_orchestrator.data_source.fetch_programme", new_callable=AsyncMock)
async def test_build_plan_data_types(mock_fetch_programme):
    """
    Tests that the data types in the returned plan are correct.
    """
    # Arrange
    mock_programme_data = {
        "races": [
            {
                "rc": "R1 C1",
                "name": "Test Race",
                "start_time": "10:00",
                "url": "http://example.com/r1c1",
                "runners_count": "10",  # runners_count is a string
            }
        ]
    }
    mock_fetch_programme.return_value = mock_programme_data

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    assert len(result_plan) == 1
    race = result_plan[0]
    assert isinstance(race["r_label"], str)
    assert isinstance(race["c_label"], str)
    assert isinstance(race["time_local"], str)
    assert isinstance(race["date"], str)
    assert isinstance(race["course_url"], str)
    assert isinstance(race["partants"], int)
    assert race["partants"] == 10


@pytest.mark.asyncio
@patch("hippique_orchestrator.data_source.fetch_programme", new_callable=AsyncMock)
async def test_build_plan_invalid_runners_count(mock_fetch_programme):
    """
    Tests that `partants` is None when `runners_count` is not a valid integer.
    """
    # Arrange
    mock_programme_data = {
        "races": [
            {
                "rc": "R1 C1",
                "name": "Test Race",
                "start_time": "10:00",
                "url": "http://example.com/r1c1",
                "runners_count": "N/A",
            }
        ]
    }
    mock_fetch_programme.return_value = mock_programme_data

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    assert len(result_plan) == 1
    assert result_plan[0]["partants"] is None


@pytest.mark.asyncio
@patch("hippique_orchestrator.data_source.fetch_programme", new_callable=AsyncMock)
async def test_build_plan_mandatory_keys(mock_fetch_programme):
    """
    Tests that all mandatory keys are present in the returned plan.
    """
    # Arrange
    mock_programme_data = {
        "races": [
            {
                "rc": "R1 C1",
                "name": "Test Race",
                "start_time": "10:00",
                "url": "http://example.com/r1c1",
                "runners_count": "10",
            }
        ]
    }
    mock_fetch_programme.return_value = mock_programme_data

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    assert len(result_plan) == 1
    race = result_plan[0]
    mandatory_keys = ["r_label", "c_label", "time_local", "date", "course_url", "partants"]
    for key in mandatory_keys:
        assert key in race
