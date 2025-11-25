
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
                {"c": "C3", "id_course": "12345"},
                {"c": "C5", "id_course": "12346"}
            ]
        },
        {
            "r": "R2",
            "hippo": "Deauville",
            "slug": "deauville",
            "courses": [
                {"c": "C1", "id_course": "12347"}
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
async def test_build_plan_async(monkeypatch):
    """Test complete plan building with Boturfers data."""

    def mock_call_discover_geny():
        return json.loads(GENY_HTML)

    def mock_fetch_boturfers_programme(url):
        # Simulate Boturfers data for the races in GENY_HTML
        return {
            "source": "boturfers",
            "type": "programme",
            "url": url,
            "scraped_at": "2025-10-15T12:00:00",
            "races": [
                {
                    "rc": "R1 C3",
                    "reunion": "R1",
                    "name": "Prix Test C3",
                    "url": "https://www.boturfers.fr/course/12345-r1c3-prix-test-c3",
                    "runners_count": 10,
                    "start_time": "15:20"
                },
                {
                    "rc": "R1 C5",
                    "reunion": "R1",
                    "name": "Prix Test C5",
                    "url": "https://www.boturfers.fr/course/12346-r1c5-prix-test-c5",
                    "runners_count": 12,
                    "start_time": "16:45"
                },
                {
                    "rc": "R2 C1",
                    "reunion": "R2",
                    "name": "Prix Test C1",
                    "url": "https://www.boturfers.fr/course/12347-r2c1-prix-test-c1",
                    "runners_count": 8,
                    "start_time": "14:10"
                }
            ]
        }

    monkeypatch.setattr("hippique_orchestrator.plan._call_discover_geny", mock_call_discover_geny)
    monkeypatch.setattr("hippique_orchestrator.plan.fetch_boturfers_programme", mock_fetch_boturfers_programme)

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
    assert plan_result[0]["r_label"] == "R2"
    assert plan_result[0]["c_label"] == "C1"
    assert plan_result[0]["time_local"] == "14:10"
    assert plan_result[0]["course_url"] == "https://www.boturfers.fr/course/12347-r2c1-prix-test-c1"

    # Check second race
    assert plan_result[1]["r_label"] == "R1"
    assert plan_result[1]["c_label"] == "C3"
    assert plan_result[1]["time_local"] == "15:20"
    assert plan_result[1]["course_url"] == "https://www.boturfers.fr/course/12345-r1c3-prix-test-c3"

    # Check third race
    assert plan_result[2]["r_label"] == "R1"
    assert plan_result[2]["c_label"] == "C5"
    assert plan_result[2]["time_local"] == "16:45"
    assert plan_result[2]["course_url"] == "https://www.boturfers.fr/course/12346-r1c5-prix-test-c5"
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

def test_call_discover_geny_subprocess_error(mocker):
    """Tests that _call_discover_geny handles a subprocess error."""
    # Mock subprocess.run to simulate a failure
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Subprocess failed"

    # Mock the logger to capture error messages
    mock_logger = mocker.patch("hippique_orchestrator.plan.logger")

    result = plan._call_discover_geny()

    # Should return a default structure with no meetings
    assert result["meetings"] == []
    # Should log the error
    mock_logger.error.assert_called_with("discover_geny_today.py failed: Subprocess failed")

def test_call_discover_geny_json_error(mocker):
    """Tests that _call_discover_geny handles invalid JSON output."""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "This is not JSON"

    mock_logger = mocker.patch("hippique_orchestrator.plan.logger")

    result = plan._call_discover_geny()

    assert result["meetings"] == []
    # Check that an error was logged with exception info
    assert mock_logger.error.call_count == 1
    call_args, call_kwargs = mock_logger.error.call_args
    assert "Failed to call discover_geny_today.py" in call_args[0]
    assert call_kwargs["exc_info"]



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
