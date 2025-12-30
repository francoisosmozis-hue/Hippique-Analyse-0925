import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import asyncio
from datetime import datetime

from hippique_orchestrator import plan

# Sample data returned by a successful scraper call
MOCK_PROGRAMME_DATA = {
    "races": [
        {
            "rc": "R1 C2",
            "name": "PRIX DE TEST",
            "start_time": "14:30",
            "url": "http://example.com/r1c2",
        },
        {
            "rc": "R1 C1",
            "name": "PRIX D'OUVERTURE",
            "start_time": "13:50",
            "url": "http://example.com/r1c1",
        },
    ]
}

# Sample data with malformed entries
MOCK_MALFORMED_DATA = {
    "races": [
        {"rc": "R1 C1", "name": "Course Valide", "start_time": "10:00", "url": "http://example.com/r1c1"},
        {"rc": "invalid", "name": "RC non valide", "start_time": "11:00", "url": "http://example.com/r2c2"}, # Truly malformed RC
        {"rc": "R3 C3", "name": "Heure manquante", "url": "http://example.com/r3c3"}, # Missing start_time
    ]
}


@pytest.mark.asyncio
@patch("hippique_orchestrator.data_source.fetch_programme", new_callable=AsyncMock)
async def test_build_plan_nominal_case(mock_fetch_programme):
    """
    Tests the happy path: the scraper returns valid data, and the plan is built and sorted correctly.
    """
    # Arrange
    mock_fetch_programme.return_value = MOCK_PROGRAMME_DATA
    test_date = "2025-12-20"

    # Act
    result_plan = await plan.build_plan_async(test_date)

    # Assert
    assert len(result_plan) == 2
    mock_fetch_programme.assert_called_once_with(
        f"https://www.boturfers.fr/courses/{test_date}"
    )

    # Check content and sorting (13:50 should be first)
    assert result_plan[0]["c_label"] == "C1"
    assert result_plan[0]["time_local"] == "13:50"
    assert result_plan[0]["date"] == test_date

    assert result_plan[1]["c_label"] == "C2"
    assert result_plan[1]["time_local"] == "14:30"
    assert result_plan[1]["course_url"] == "http://example.com/r1c2"


@pytest.mark.asyncio
@patch("hippique_orchestrator.data_source.fetch_programme", new_callable=AsyncMock)
async def test_build_plan_scraper_fails(mock_fetch_programme, caplog):
    """
    Tests that an empty plan is returned if the scraper fails (returns None).
    """
    # Arrange
    mock_fetch_programme.return_value = None

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    assert result_plan == []
    assert "Failed to fetch programme from Boturfers or it was empty." in caplog.text


@pytest.mark.asyncio
@patch("hippique_orchestrator.data_source.fetch_programme", new_callable=AsyncMock)
async def test_build_plan_handles_malformed_data(mock_fetch_programme, caplog):
    """
    Tests that entries with malformed RC format or missing start_time are skipped.
    """
    # Arrange
    mock_fetch_programme.return_value = MOCK_MALFORMED_DATA

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")

    # Assert
    # Only the one valid race should be in the plan
    assert len(result_plan) == 1
    assert result_plan[0]["r_label"] == "R1"
    assert result_plan[0]["c_label"] == "C1"

    # Check that warnings were logged for the skipped races
    assert "Could not parse R/C from 'invalid'" in caplog.text
    # The entry with missing start_time is filtered out before the RC parsing, so no log is expected for it.

@pytest.mark.asyncio
@patch("hippique_orchestrator.data_source.fetch_programme", new_callable=AsyncMock)
async def test_build_plan_today_string(mock_fetch_programme):
    """
    Tests that passing "today" uses the correct URL for the current day's programme.
    """
    mock_fetch_programme.return_value = {"races": []}
    today_str = datetime.now().strftime("%Y-%m-%d")

    await plan.build_plan_async("today")

    mock_fetch_programme.assert_called_once_with("https://www.boturfers.fr/programme-pmu-du-jour")

@pytest.mark.asyncio
@patch("hippique_orchestrator.data_source.fetch_programme", new_callable=AsyncMock)
async def test_build_plan_empty_enriched_plan(mock_fetch_programme):
    """
    Tests that sorting is skipped if the enriched plan is empty, covering the `if enriched_plan:` branch.
    """
    # Arrange: return races that will all be filtered out
    mock_fetch_programme.return_value = { "races": [ {"rc": "invalid", "start_time": "10:00"} ] }

    # Act
    result_plan = await plan.build_plan_async("2025-12-20")
    
    # Assert
    assert result_plan == []


def test_build_plan_sync_wrapper():
    """
    Tests the synchronous wrapper `build_plan`.
    """
    with patch("hippique_orchestrator.plan.build_plan_async", new_callable=AsyncMock) as mock_async:
        mock_async.return_value = ["mock_result"]
        
        result = plan.build_plan("2025-12-20")
        
        assert result == ["mock_result"]
        mock_async.assert_called_once_with("2025-12-20")

def test_build_plan_sync_raises_in_event_loop():
    """
    Tests that the synchronous wrapper raises a RuntimeError if called from within an existing event loop.
    """
    async def main():
        with pytest.raises(RuntimeError) as excinfo:
            plan.build_plan("2025-12-20")
        assert "cannot be called from a running event loop" in str(excinfo.value)

    # To test this, we need to run our test function inside a running event loop
    with patch("hippique_orchestrator.plan.build_plan_async", new_callable=AsyncMock):
        asyncio.run(main())