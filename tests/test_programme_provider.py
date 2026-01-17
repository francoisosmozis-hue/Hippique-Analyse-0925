import datetime
import logging
from unittest.mock import patch, MagicMock

import pytest

from hippique_orchestrator.data_contract import Race, Meeting
from hippique_orchestrator.programme_provider import get_races_for_date, get_meetings_for_date
from hippique_orchestrator.source_registry import source_registry

# Sample data returned by a mock provider's get_programme method
MOCK_RACES_DATA = [
    {
        "race_id": "R1C1",
        "reunion_id": 1,
        "course_id": 1,
        "hippodrome": "VINCENNES",
        "date": "2024-01-01",
        "url": "http://example.com/r1c1"
    },
    {
        "race_id": "R1C2",
        "reunion_id": 1,
        "course_id": 2,
        "hippodrome": "VINCENNES",
        "date": "2024-01-01",
        "url": "http://example.com/r1c2"
    },
]

@pytest.fixture
def mock_primary_provider():
    """Mocks the primary programme provider in the source registry."""
    # We create a MagicMock that simulates an instantiated provider
    mock_provider = MagicMock()
    mock_provider.get_programme.return_value = MOCK_RACES_DATA
    
    # We patch the registry's method to return our mock provider
    with patch.object(source_registry, 'get_primary_programme_provider', return_value=mock_provider) as mock_method:
        yield mock_provider

def test_get_races_for_date_calls_primary_provider(mock_primary_provider):
    """
    Verify that get_races_for_date calls the get_programme method of the
    primary provider returned by the registry.
    """
    target_date = datetime.date(2024, 1, 1)
    
    races = get_races_for_date(target_date)

    # Check that the provider's method was called correctly
    mock_primary_provider.get_programme.assert_called_once_with(target_date.strftime("%Y-%m-%d"))
    
    # Check that the data returned is the mock data
    assert len(races) == 2
    assert races[0]["race_id"] == "R1C1"

def test_get_meetings_for_date_groups_races_correctly(mock_primary_provider):
    """
    Verify that get_meetings_for_date correctly groups races into meetings.
    """
    target_date = datetime.date(2024, 1, 1)
    
    meetings = get_meetings_for_date(target_date)

    # Check that the provider was called
    mock_primary_provider.get_programme.assert_called_once()
    
    # Check the meeting grouping logic
    assert len(meetings) == 1
    meeting = meetings[0]
    assert isinstance(meeting, Meeting)
    assert meeting.hippodrome == "VINCENNES"
    assert meeting.races_count == 2
    assert meeting.races[0].race_id == "R1C1"
    assert meeting.races[1].race_id == "R1C2"

def test_get_races_for_date_handles_provider_failure(caplog):
    """
    Verify that an empty list is returned if the provider fails (e.g., raises an exception).
    """
    caplog.set_level(logging.ERROR)
    target_date = datetime.date(2024, 1, 1)
    
    mock_provider = MagicMock()
    mock_provider.get_programme.side_effect = Exception("Provider connection failed")

    with patch.object(source_registry, 'get_primary_programme_provider', return_value=mock_provider):
        races = get_races_for_date(target_date)

    assert races == []
    assert "Provider 'MagicMock' failed to fetch race data" in caplog.text
    assert "Provider connection failed" in caplog.text

def test_get_races_for_date_handles_no_provider(caplog):
    """
    Verify that an empty list is returned if the registry has no primary provider.
    """
    caplog.set_level(logging.CRITICAL)
    target_date = datetime.date(2024, 1, 1)
    
    with patch.object(source_registry, 'get_primary_programme_provider', side_effect=ValueError("No provider configured")):
        races = get_races_for_date(target_date)
    
    assert races == []
    assert "Could not get a primary programme provider: No provider configured" in caplog.text