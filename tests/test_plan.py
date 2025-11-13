"""
tests/test_plan.py - Unit tests for plan module
"""
import json
import sys

import pytest

sys.path.insert(0, 'src')

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
