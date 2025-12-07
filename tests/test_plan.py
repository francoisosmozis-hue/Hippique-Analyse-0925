
"""
tests/test_plan.py - Unit tests for plan module
"""
import json
import sys

import pytest



from hippique_orchestrator import plan
from hippique_orchestrator.plan import build_plan_async

# Mock HTML fixtures
GENY_HTML = """
{
    "date": "2025-10-15",
    "meetings": [
        {
            "r": "R1",
            "hippo": "Paris Vincennes",
            "slug": "paris-vincennes",
            "courses": [
                {"c": "C2", "id_course": "12345"}
            ]
        },
        {
            "r": "R2",
            "hippo": "Deauville",
            "slug": "deauville",
            "courses": [
                {"c": "C3", "id_course": "12346"}
            ]
        },
        {
            "r": "R3",
            "hippo": "Chantilly",
            "slug": "chantilly",
            "courses": [
                {"c": "C2", "id_course": "12347"}
            ]
        }
    ]
}
"""

ZETURF_HTML_R1C3 = """
<html><body><time datetime='2025-10-15T15:20:00+02:00'>15h20</time></body></html>
"""

ZETURF_HTML_R1C5 = """
<html><body><time datetime='2025-10-15T16:45:00+02:00'>16h45</time></body></html>
"""

ZETURF_HTML_R2C1 = """
<html><body><time datetime='2025-10-15T14:10:00+02:00'>14h10</time></body></html>
"""

@pytest.mark.asyncio
async def test_build_plan_async(mocker): # Use mocker instead of monkeypatch for patching functions
    """Test complete plan building with Boturfers data."""

    # Mock fetch_geny_programme
    mocker.patch(
        "hippique_orchestrator.plan.fetch_geny_programme",
        return_value=json.loads(GENY_HTML)
    )

    # Mock data_source.fetch_programme
    mocker.patch(
        "hippique_orchestrator.data_source.fetch_programme",
        return_value={
            "source": "boturfers",
            "type": "programme",
            "url": "https://www.boturfers.fr/programme-pmu-du-jour",
            "scraped_at": "2025-10-15T12:00:00",
            "races": [
                {
                    "rc": "R1 C2",
                    "reunion": "R1",
                    "name": "Prix Test C2",
                    "url": "https://www.boturfers.fr/course/12345-r1c2-prix-test-c2",
                    "runners_count": 10,
                    "start_time": "15:20"
                },
                {
                    "rc": "R2 C3",
                    "reunion": "R2",
                    "name": "Prix Test C3",
                    "url": "https://www.boturfers.fr/course/12346-r2c3-prix-test-c3",
                    "runners_count": 12,
                    "start_time": "16:45"
                },
                {
                    "rc": "R3 C2",
                    "reunion": "R3",
                    "name": "Prix Test C2",
                    "url": "https://www.boturfers.fr/course/12347-r3c2-prix-test-c2",
                    "runners_count": 8,
                    "start_time": "14:10"
                }
            ]
        }
    )

    plan_result = await build_plan_async("2025-10-15")

    assert len(plan_result) == 3

    # Check all races have times and Boturfers URLs
    for race in plan_result:
        assert race["time_local"] is not None
        assert "boturfers.fr" in race["course_url"]

    # Check sorting by time
    times = [race["time_local"] for race in plan_result]
    assert times == sorted(times)

    # Check first race (earliest)
    assert plan_result[0]["r_label"] == "R3"
    assert plan_result[0]["c_label"] == "C2"
    assert plan_result[0]["time_local"] == "14:10"
    assert plan_result[0]["course_url"] == "https://www.boturfers.fr/course/12347-r3c2-prix-test-c2"

    # Check second race
    assert plan_result[1]["r_label"] == "R1"
    assert plan_result[1]["c_label"] == "C2"
    assert plan_result[1]["time_local"] == "15:20"
    assert plan_result[1]["course_url"] == "https://www.boturfers.fr/course/12345-r1c2-prix-test-c2"

    # Check third race
    assert plan_result[2]["r_label"] == "R2"
    assert plan_result[2]["c_label"] == "C3"
    assert plan_result[2]["time_local"] == "16:45"
    assert plan_result[2]["course_url"] == "https://www.boturfers.fr/course/12346-r2c3-prix-test-c3"
def test_build_plan_structure():
    """Tests the construction of the plan from Geny data, including deduplication."""
    geny_data = {
        "meetings": [
            {
                "r": "R1", "hippo": "Hippo1",
                "courses": [
                    {"c": "C1", "id_course": "11"},
                    {"c": "C2", "id_course": "12"},
                ]
            },
            {
                "r": "R1", "hippo": "Hippo1", # Duplicate meeting, should be handled
                "courses": [
                    {"c": "C2", "id_course": "12_dup"}, # Duplicate course, should be skipped
                ]
            }
        ]
    }
    date = "2025-01-01"

    # Directly test the internal function
    result_plan = plan._build_plan_structure(geny_data, date)

    # Expect 2 unique races (R1C1, R1C2)
    assert len(result_plan) == 2

    # Verify the structure of the first race
    race1 = result_plan[0]
    assert race1["r_label"] == "R1"
    assert race1["c_label"] == "C1"
    assert race1.get("time_local") is None # Time is not added at this stage
    assert race1["course_url"] is None
    assert race1["reunion_url"] is None



def test_build_plan_sync_wrapper(mocker):
    """Tests the synchronous build_plan wrapper."""
    # Mock the async function it calls
    mock_build_plan_async = mocker.patch("hippique_orchestrator.plan.build_plan_async", new_callable=mocker.AsyncMock)
    mock_build_plan_async.return_value = ["race1", "race2"]

    result = plan.build_plan("2025-01-01")

    # Check that the async function was called and the result is passed through
    mock_build_plan_async.assert_called_once_with("2025-01-01")
    assert result == ["race1", "race2"]

def test_build_plan_sync_wrapper_raises_in_event_loop(mocker):
    """Tests that the sync wrapper raises an error if called inside an event loop."""
    # Mock asyncio.run to simulate the RuntimeError
    mock_asyncio_run = mocker.patch("asyncio.run")
    mock_asyncio_run.side_effect = RuntimeError("cannot run loop while another is running")

    # Mock the logger to check the error message
    mock_logger = mocker.patch("hippique_orchestrator.plan.logger")

    with pytest.raises(RuntimeError, match="Use build_plan_async\\(\\) in async context"):
        plan.build_plan("2025-01-01")

    # Verify that the specific error was logged
    mock_logger.error.assert_called_once_with(
        "Cannot use build_plan() from within event loop. Use build_plan_async() instead."
    )
