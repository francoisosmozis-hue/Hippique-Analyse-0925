"""Unit tests for the refactored Programme Provider."""

import datetime
import logging
from unittest.mock import MagicMock, patch

import pytest

from hippique_orchestrator.data_contract import Programme
from hippique_orchestrator.programme_provider import get_programme_for_date


# Sample valid data structure for a programme
import datetime # Ensure datetime is imported

# Sample valid data structure for a programme
VALID_PROGRAMME_DATA = {
    "date": datetime.date(2024, 1, 1), # Added
    "races": [
        {
            "race_id": "R1C1",
            "reunion_id": 1, # Added
            "course_id": 1, # Added
            "hippodrome": "VINCENNES",
            "date": datetime.date(2024, 1, 1), # Converted to datetime.date object
            "start_time": datetime.time(13, 50), # Added
            "name": "Prix d'Essai", # Added
            "discipline": "Trot Attelé", # Added
            "country_code": "FR",
            "url": "http://example.com/r1c1",
        }
    ],
}

# Another valid programme from a different source
FALLBACK_PROGRAMME_DATA = {
    "date": datetime.date(2024, 1, 1), # Added
    "races": [
        {
            "race_id": "R1C1_fallback",
            "reunion_id": 1, # Added
            "course_id": 1, # Added
            "hippodrome": "ENGHIEN",
            "date": datetime.date(2024, 1, 1), # Converted to datetime.date object
            "start_time": datetime.time(14, 00), # Added
            "name": "Grand Prix Fallback", # Added
            "discipline": "Plat", # Added
            "country_code": "FR",
            "url": "http://fallback.com/r1c1",
        }
    ],
}


@patch("hippique_orchestrator.programme_provider.source_registry")
def test_get_programme_successful_from_primary(mock_registry):
    """
    Tests that the programme is returned from the primary provider if it succeeds.
    """
    primary_provider = MagicMock()
    primary_provider.get_programme.return_value = VALID_PROGRAMME_DATA
    primary_provider.__class__.__name__ = "MockPrimaryProvider"

    # Registry returns only the primary provider
    mock_registry.get_providers_by_capability.return_value = [primary_provider]

    target_date = datetime.date(2024, 1, 1)
    programme = get_programme_for_date(target_date)

    # Assertions
    mock_registry.get_providers_by_capability.assert_called_once()
    primary_provider.get_programme.assert_called_once_with(target_date.strftime("%Y-%m-%d"))
    
    assert programme is not None
    assert isinstance(programme, Programme)
    assert programme.races[0].race_id == "R1C1"


@patch("hippique_orchestrator.programme_provider.source_registry")
def test_get_programme_falls_back_on_primary_failure(mock_registry, caplog):
    """
    Tests that the system correctly falls back to the secondary provider
    if the primary one fails (e.g., raises an exception).
    """
    primary_provider = MagicMock()
    primary_provider.get_programme.side_effect = Exception("Connection Timeout")
    primary_provider.__class__.__name__ = "MockPrimaryProvider"

    fallback_provider = MagicMock()
    fallback_provider.get_programme.return_value = FALLBACK_PROGRAMME_DATA
    fallback_provider.__class__.__name__ = "MockFallbackProvider"

    # Registry returns both providers in order
    mock_registry.get_providers_by_capability.return_value = [primary_provider, fallback_provider]

    with caplog.at_level(logging.ERROR):
        target_date = datetime.date(2024, 1, 1)
        programme = get_programme_for_date(target_date)

        # Assertions
        assert "Provider 'MockPrimaryProvider' failed" in caplog.text
        primary_provider.get_programme.assert_called_once()
        fallback_provider.get_programme.assert_called_once()

        assert programme is not None
        assert isinstance(programme, Programme)
        assert programme.races[0].race_id == "R1C1_fallback"


@patch("hippique_orchestrator.programme_provider.source_registry")
def test_get_programme_falls_back_on_empty_data(mock_registry, caplog):
    """
    Tests that the system falls back if the primary provider returns empty or invalid data.
    """
    primary_provider = MagicMock()
    primary_provider.get_programme.return_value = {}  # Empty data
    primary_provider.__class__.__name__ = "MockPrimaryProvider"

    fallback_provider = MagicMock()
    fallback_provider.get_programme.return_value = FALLBACK_PROGRAMME_DATA
    fallback_provider.__class__.__name__ = "MockFallbackProvider"

    mock_registry.get_providers_by_capability.return_value = [primary_provider, fallback_provider]

    with caplog.at_level(logging.WARNING):
        target_date = datetime.date(2024, 1, 1)
        programme = get_programme_for_date(target_date)

        assert "Provider 'MockPrimaryProvider' returned no data" in caplog.text
        assert programme is not None
        assert programme.races[0].hippodrome == "ENGHIEN"


@patch("hippique_orchestrator.programme_provider.source_registry")
def test_get_programme_returns_none_if_all_providers_fail(mock_registry, caplog):
    """
    Tests that the function returns None if all configured providers fail.
    """
    primary_provider = MagicMock()
    primary_provider.get_programme.side_effect = Exception("Primary Failure")
    primary_provider.__class__.__name__ = "MockPrimaryProvider"

    fallback_provider = MagicMock()
    fallback_provider.get_programme.side_effect = Exception("Fallback Failure")
    fallback_provider.__class__.__name__ = "MockFallbackProvider"

    mock_registry.get_providers_by_capability.return_value = [primary_provider, fallback_provider]

    with caplog.at_level(logging.CRITICAL):
        target_date = datetime.date(2024, 1, 1)
        programme = get_programme_for_date(target_date)

        assert programme is None
        assert "All configured providers failed to deliver a programme" in caplog.text


@patch("hippique_orchestrator.programme_provider.source_registry")
def test_get_programme_handles_no_providers(mock_registry, caplog):
    """
    Tests that the function returns None if no providers are configured.
    """
    mock_registry.get_providers_by_capability.return_value = []

    with caplog.at_level(logging.CRITICAL):
        target_date = datetime.date(2024, 1, 1)
        programme = get_programme_for_date(target_date)

        assert programme is None
        assert "No programme providers are configured or loaded" in caplog.text
