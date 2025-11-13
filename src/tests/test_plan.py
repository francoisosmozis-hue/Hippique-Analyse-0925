"""
tests/test_plan.py - Unit tests for plan module
"""
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, 'src')

from plan import build_plan, fill_times_from_geny, parse_zeturf_program

# Mock HTML fixtures
ZETURF_HTML = """
<html>
<body>
    <a href="/fr/course/2025-10-15/R1C3-paris-vincennes-trot">R1C3 - Paris Vincennes</a>
    <a href="/fr/course/2025-10-15/R1C5-paris-vincennes-trot">R1C5 - Paris Vincennes</a>
    <a href="/fr/course/2025-10-15/R2C1-deauville-plat">R2C1 - Deauville</a>
</body>
</html>
"""

GENY_HTML = """
<html>
<body>
    <div class="reunion" data-reunion="1">
        <h2 class="nom">Paris Vincennes</h2>
        <div class="course" data-reunion="1" data-course="3">
            <span class="time">15:20</span>
        </div>
        <div class="course" data-reunion="1" data-course="5">
            <span class="time">16:45</span>
        </div>
    </div>
    <div class="reunion" data-reunion="2">
        <h2 class="nom">Deauville</h2>
        <div class="course" data-reunion="2" data-course="1">
            <span class="time">14:10</span>
        </div>
    </div>
</body>
</html>
"""

class MockResponse:
    def __init__(self, content, status_code=200):
        self.content = content.encode('utf-8')
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code != 200:
            raise Exception(f"HTTP {self.status_code}")

@pytest.fixture
def mock_session():
    with patch('plan.session') as mock:
        yield mock

def test_parse_zeturf_program(mock_session):
    """Test ZEturf program parsing"""
    mock_session.get.return_value = MockResponse(ZETURF_HTML)

    races = parse_zeturf_program("2025-10-15")

    assert len(races) == 3
    assert races[0]["r_label"] == "R1"
    assert races[0]["c_label"] == "C3"
    assert "course/2025-10-15/R1C3" in races[0]["course_url"]
    assert races[0]["time_local"] is None  # Not filled yet

def test_parse_zeturf_deduplication(mock_session):
    """Test that duplicate races are removed"""
    html_with_dup = ZETURF_HTML + '<a href="/fr/course/2025-10-15/R1C3-duplicate">R1C3 Dup</a>'
    mock_session.get.return_value = MockResponse(html_with_dup)

    races = parse_zeturf_program("2025-10-15")

    # Should still be 3 unique races
    assert len(races) == 3
    r1c3_count = sum(1 for r in races if r["r_label"] == "R1" and r["c_label"] == "C3")
    assert r1c3_count == 1

def test_fill_times_from_geny(mock_session):
    """Test filling times from Geny"""
    mock_session.get.return_value = MockResponse(GENY_HTML)

    races = [
        {"r_label": "R1", "c_label": "C3", "time_local": None, "meeting": None},
        {"r_label": "R1", "c_label": "C5", "time_local": None, "meeting": None},
        {"r_label": "R2", "c_label": "C1", "time_local": None, "meeting": None}
    ]

    filled = fill_times_from_geny("2025-10-15", races)

    assert filled[0]["time_local"] == "15:20"
    assert filled[0]["meeting"] == "Paris Vincennes"
    assert filled[1]["time_local"] == "16:45"
    assert filled[2]["time_local"] == "14:10"
    assert filled[2]["meeting"] == "Deauville"

def test_fill_times_preserves_existing(mock_session):
    """Test that existing times are preserved"""
    mock_session.get.return_value = MockResponse(GENY_HTML)

    races = [
        {"r_label": "R1", "c_label": "C3", "time_local": "12:00", "meeting": "Custom"}
    ]

    filled = fill_times_from_geny("2025-10-15", races)

    # Should prefer Geny data
    assert filled[0]["time_local"] == "15:20"

def test_build_plan(mock_session):
    """Test complete plan building"""
    mock_session.get.side_effect = [
        MockResponse(ZETURF_HTML),  # First call for ZEturf
        MockResponse(GENY_HTML)      # Second call for Geny
    ]

    plan = build_plan("2025-10-15")

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

def test_build_plan_filters_no_time(mock_session):
    """Test that races without time are filtered"""
    incomplete_geny = """
    <html><body>
        <div class="reunion" data-reunion="1">
            <div class="course" data-reunion="1" data-course="3">
                <span class="time">15:20</span>
            </div>
            <!-- R1C5 missing time -->
            <div class="course" data-reunion="1" data-course="5">
            </div>
        </div>
    </body></html>
    """

    mock_session.get.side_effect = [
        MockResponse(ZETURF_HTML),
        MockResponse(incomplete_geny)
    ]

    plan = build_plan("2025-10-15")

    # Should only include races with times
    assert len(plan) < 3
    for race in plan:
        assert race["time_local"] is not None

def test_parse_zeturf_empty_page(mock_session):
    """Test handling of empty ZEturf page"""
    mock_session.get.return_value = MockResponse("<html><body></body></html>")

    races = parse_zeturf_program("2025-10-15")

    assert races == []

def test_parse_zeturf_network_error(mock_session):
    """Test handling of network errors"""
    mock_session.get.side_effect = Exception("Network error")

    races = parse_zeturf_program("2025-10-15")

    assert races == []

def test_fill_times_geny_error(mock_session):
    """Test graceful handling of Geny errors"""
    mock_session.get.side_effect = Exception("Geny down")

    races = [{"r_label": "R1", "c_label": "C3", "time_local": None}]

    filled = fill_times_from_geny("2025-10-15", races)

    # Should return races unchanged
    assert filled == races
