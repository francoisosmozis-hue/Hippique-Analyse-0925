
"""
tests/test_plan.py - Unit tests for plan module
"""
import json
import sys

import pytest

sys.path.insert(0, 'src')

from src import plan
from src.plan import build_plan_async

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
    """Test complete plan building"""

    def mock_call_discover_geny():
        return json.loads(GENY_HTML)

    async def mock_fetch_start_time_async(session, course_url):
        if "R1C3" in course_url:
            return "15:20"
        if "R1C5" in course_url:
            return "16:45"
        if "R2C1" in course_url:
            return "14:10"
        return None

    monkeypatch.setattr("src.plan._call_discover_geny", mock_call_discover_geny)
    monkeypatch.setattr("src.plan._fetch_start_time_async", mock_fetch_start_time_async)

    plan = await build_plan_async("2025-10-15")

    assert len(plan) == 3

    # Check all races have times
    for race in plan:
        assert race["time_local"] is not None

    # Check sorting by time
    times = [race["time_local"] for race in plan]
    assert times == sorted(times)

    # Check first race (earliest)
    assert plan[0]["r_label"] == "R2"
    assert plan[0]["c_label"] == "C1"
    assert plan[0]["time_local"] == "14:10"

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
    assert race1["course_url"] == "https://www.zeturf.fr/fr/course/2025-01-01/R1C1"
    assert race1["reunion_url"] == "https://www.zeturf.fr/fr/reunion/2025-01-01/R1"

def test_call_discover_geny_subprocess_error(mocker):
    """Tests that _call_discover_geny handles a subprocess error."""
    # Mock subprocess.run to simulate a failure
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Subprocess failed"

    # Mock the logger to capture error messages
    mock_logger = mocker.patch("src.plan.logger")

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

    mock_logger = mocker.patch("src.plan.logger")

    result = plan._call_discover_geny()

    assert result["meetings"] == []
    # Check that an error was logged with exception info
    assert mock_logger.error.call_count == 1
    call_args, call_kwargs = mock_logger.error.call_args
    assert "Failed to call discover_geny_today.py" in call_args[0]
    assert call_kwargs["exc_info"]

@pytest.mark.parametrize(
    "html_snippet, expected_time",
    [
        ("blabla 14h30 blabla", "14:30"),
        ("blabla 9:05 blabla", "09:05"),
        ("<time datetime='T18:45:00'>", "18:45"),
        ('{"startDate": "2025-01-01T08:15"}', "08:15"),
        ("No time here", None),
        ("", None),
    ],
)
def test_extract_start_time_fallback(html_snippet, expected_time):
    """Tests the fallback time extraction logic with various formats."""
    assert plan._extract_start_time_fallback(html_snippet) == expected_time

def test_build_plan_sync_wrapper(mocker):
    """Tests the synchronous build_plan wrapper."""
    # Mock the async function it calls
    mock_build_plan_async = mocker.patch("src.plan.build_plan_async", new_callable=mocker.AsyncMock)
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
    mock_logger = mocker.patch("src.plan.logger")

    with pytest.raises(RuntimeError, match="Use build_plan_async\\(\\) in async context"):
        plan.build_plan("2025-01-01")

    # Verify that the specific error was logged
    mock_logger.error.assert_called_once_with(
        "Cannot use build_plan() from within event loop. Use build_plan_async() instead."
    )
