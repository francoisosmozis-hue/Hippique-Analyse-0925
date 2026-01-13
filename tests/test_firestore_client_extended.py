"""Extended tests for firestore_client.py to cover edge cases."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from google.cloud import firestore

from hippique_orchestrator import firestore_client


async def test_get_processing_status_for_date_processing_stalled(race_document_factory):
    """
    Covers the 'PROCESSING_STALLED' case in get_processing_status_for_date.
    This happens when there are no races for the given date, but there are races
    from other dates in the database.
    """
    # Arrange
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_db.collection.return_value = mock_collection

    mock_latest_doc_query = MagicMock()
    mock_collection.order_by.return_value.limit.return_value = mock_latest_doc_query

    # Simulate a non-empty database, but with no races for the given date
    update_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    mock_doc = race_document_factory(
        "2025-01-01_R1C1",
        {
            "gpi_decision": "PLAY",
            "last_modified_at": update_time.isoformat(),
        },
    )
    mock_doc.update_time = update_time  # Set update_time separately if needed

    mock_latest_doc_query.stream.return_value = [mock_doc]

    daily_plan = [
        {"rc_key": "R1C1", "race_url": "http://example.com/R1C1"},
        {"rc_key": "R1C2", "race_url": "http://example.com/R1C2"},
    ]

    # Act
    with (
        patch("hippique_orchestrator.firestore_client._get_firestore_client", return_value=mock_db),
        patch("hippique_orchestrator.firestore_client.get_races_for_date", return_value=[]),
    ):
        status = await firestore_client.get_processing_status_for_date("2025-01-02", daily_plan)

    # Assert
    assert status["reason_if_empty"] == "PROCESSING_STALLED"
    assert status["counts"]["total_in_plan"] == 2
    assert status["counts"]["total_processed"] == 0
    assert status["firestore_metadata"]["last_update_ts"] is not None


async def test_get_processing_status_for_date_db_empty():
    """
    Tests get_processing_status_for_date when the database is completely empty.
    """
    # Arrange
    mock_db = MagicMock()
    mock_collection = MagicMock()
    mock_db.collection.return_value = mock_collection

    mock_latest_doc_query = MagicMock()
    mock_collection.order_by.return_value.limit.return_value = mock_latest_doc_query
    mock_latest_doc_query.stream.return_value = []

    # a daily plan with races
    daily_plan = [
        {"rc_key": "R1C1", "race_url": "http://example.com/R1C1"},
    ]

    # Act
    with (
        patch("hippique_orchestrator.firestore_client._get_firestore_client", return_value=mock_db),
        patch("hippique_orchestrator.firestore_client.get_races_for_date", return_value=[]),
    ):
        status = await firestore_client.get_processing_status_for_date("2025-01-01", daily_plan)

    # Assert
    assert status["reason_if_empty"] == "NO_TASKS_PROCESSED_OR_FIRESTORE_EMPTY"
    assert status["counts"]["total_in_plan"] == 1
    assert status["counts"]["total_processed"] == 0
    assert status["firestore_metadata"]["docs_count_for_date"] == 0
    assert status["firestore_metadata"]["last_update_ts"] is None
