import logging
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from google.cloud.firestore import DocumentSnapshot

from hippique_orchestrator import firestore_client

# We need to patch the client at the source, where it's looked up.
FIRESTORE_CLIENT_PATH = "hippique_orchestrator.firestore_client._get_firestore_client"

@pytest.fixture(autouse=True)
def reset_firestore_client():
    """Resets the internal _db_client state before each test."""
    original_db_client = firestore_client._db_client
    firestore_client._db_client = None
    yield
    firestore_client._db_client = original_db_client

@pytest.fixture
def mock_db():
    """Fixture to mock the firestore client returned by _get_firestore_client."""
    # Import firestore here to ensure it's defined in the fixture's scope
    mock_firestore_client = MagicMock()
    with patch(FIRESTORE_CLIENT_PATH, return_value=mock_firestore_client):
        yield mock_firestore_client


def test_update_race_document_success(mock_db):
    """Test that `update_race_document` calls firestore `set` with merge=True."""

    doc_ref_mock = MagicMock()
    mock_db.collection.return_value.document.return_value = doc_ref_mock

    document_id = "2025-12-30_R1C1"
    data = {"status": "processed"}
    firestore_client.update_race_document(document_id, data)

    mock_db.collection.assert_called_once_with("races-test")
    mock_db.collection.return_value.document.assert_called_once_with(document_id)
    doc_ref_mock.set.assert_called_once_with(data, merge=True)


def test_update_race_document_handles_exception(mock_db, caplog):
    """Test that exceptions during firestore update are logged as errors."""

    mock_db.collection.side_effect = Exception("Firestore unavailable")

    firestore_client.update_race_document("some_id", {"data": "value"})

    assert "Failed to update document some_id" in caplog.text
    assert "Firestore unavailable" in caplog.text



# ... (rest of the file)

@patch("hippique_orchestrator.firestore_client._get_firestore_client", return_value=None)
@patch("hippique_orchestrator.firestore_client.logger.warning")
def test_update_race_document_skips_if_db_not_available(mock_warning, mock_get_firestore_client):
    """Test that updates are skipped if the db client is None."""

    firestore_client.update_race_document("any_id", {})
    mock_warning.assert_called_once_with("Firestore is not available, skipping update.")


async def test_get_races_for_date_success(mock_db):
    """Test `get_races_for_date` returns a list of document snapshots."""

    # Create mock documents
    doc1_mock = MagicMock(spec=DocumentSnapshot)
    doc2_mock = MagicMock(spec=DocumentSnapshot)

    mock_query = MagicMock()
    mock_query.stream.return_value = [doc1_mock, doc2_mock]

    mock_db.collection.return_value.order_by.return_value.start_at.return_value.end_at.return_value = mock_query

    date_str = "2025-12-30"
    results = await firestore_client.get_races_for_date(date_str)

    assert len(results) == 2
    assert results[0] == doc1_mock
    mock_db.collection.assert_called_once_with("races-test")
    mock_db.collection.return_value.order_by.assert_called_with("__name__")


async def test_get_races_for_date_empty(mock_db):
    """Test `get_races_for_date` returns an empty list when no documents are found."""

    mock_query = MagicMock()
    mock_query.stream.return_value = []

    mock_db.collection.return_value.order_by.return_value.start_at.return_value.end_at.return_value = mock_query

    results = await firestore_client.get_races_for_date("2025-12-30")

    assert results == []


async def test_get_races_for_date_handles_exception(mock_db, caplog):
    """Test that exceptions during race query are logged and return an empty list."""

    mock_db.collection.side_effect = Exception("Query failed")

    results = await firestore_client.get_races_for_date("2025-12-30")

    assert "Failed to query races by date 2025-12-30" in caplog.text
    assert "Query failed" in caplog.text
    assert results == []


@patch("hippique_orchestrator.firestore_client._get_firestore_client", return_value=None)
@patch("hippique_orchestrator.firestore_client.logger.warning")
async def test_get_races_for_date_skips_if_db_not_available(mock_warning, mock_get_firestore_client):
    """Test that `get_races_for_date` skips if the db client is None."""

    date_str = "2025-12-30"
    results = await firestore_client.get_races_for_date(date_str)
    assert results == []
    mock_warning.assert_called_once_with("Firestore is not available, cannot query races.")


@pytest.mark.parametrize(
    "url, date, expected",
    [
        (
            "https://www.zeturf.fr/fr/course/2025-12-25/R1C2-test-pmu",
            "2025-12-25",
            "2025-12-25_R1C2",
        ),
        ("https://turf.fr/R5C3/details", "2025-12-25", "2025-12-25_R5C3"),
        ("R3C8", "2025-12-25", "2025-12-25_R3C8"),
        ("R1C1", "2025-12-25", "2025-12-25_R1C1"),
        ("some-string-r4c1-other", "2025-12-25", "2025-12-25_R4C1"),
        ("invalid-url", "2025-12-25", None),
        ("", "2025-12-25", None),
    ],
)
def test_get_doc_id_from_url(url, date, expected):
    """Test `get_doc_id_from_url` correctly parses various URL formats."""

    assert firestore_client.get_doc_id_from_url(url, date) == expected


def create_mock_doc(doc_id, update_time_str, data=None):
    """Helper to create a mock DocumentSnapshot."""
    mock_doc = MagicMock()
    mock_doc.id = doc_id
    mock_doc.update_time = datetime.fromisoformat(update_time_str)
    # Ensure to_dict includes id and update_time, mimicking real DocumentSnapshot behavior
    mock_data = data.copy() if data else {}
    mock_data["race_doc_id"] = doc_id  # Expected by _get_metadata_from_docs
    mock_data["last_modified_at"] = mock_doc.update_time.isoformat()  # Expected by _get_metadata_from_docs
    mock_doc.to_dict.return_value = mock_data
    return mock_doc


async def test_get_processing_status_for_date_success(mock_db):
    """Test `get_processing_status_for_date` for a nominal case with processed data."""

    date_str = "2025-12-30"
    daily_plan = [
        {"rc": "R1C1", "time": "10:00"},
        {"rc": "R1C2", "time": "10:30"},
        {"rc": "R1C3", "time": "11:00"},
    ]

    # Mock Firestore documents
    mock_docs = [
        create_mock_doc(
            "2025-12-30_R1C1",
            "2025-12-30T10:05:00+00:00",
            {"tickets_analysis": {"gpi_decision": "play"}},
        ),
        create_mock_doc(
            "2025-12-30_R1C2",
            "2025-12-30T10:35:00+00:00",
            {"tickets_analysis": {"gpi_decision": "abstain"}},
        ),
    ]
    mock_query = MagicMock()
    mock_query.stream.return_value = mock_docs
    mock_db.collection.return_value.order_by.return_value.start_at.return_value.end_at.return_value = mock_query

    status = await firestore_client.get_processing_status_for_date(date_str, daily_plan)

    assert status["date"] == date_str
    assert status["config"]["project_id"] == "test-project"
    assert status["counts"]["total_in_plan"] == 3
    assert status["counts"]["total_processed"] == 2
    assert status["counts"]["total_playable"] == 1
    assert status["counts"]["total_abstain"] == 1
    assert status["counts"]["total_error"] == 0
    assert status["counts"]["total_pending"] == 1
    assert status["firestore_metadata"]["docs_count_for_date"] == 2
    assert status["firestore_metadata"]["last_doc_id"] == "2025-12-30_R1C2"
    assert status["firestore_metadata"]["last_update_ts"] == "2025-12-30T10:35:00+00:00"
    assert status["reason_if_empty"] is None


@patch(FIRESTORE_CLIENT_PATH, return_value=None)
async def test_get_processing_status_for_date_db_not_available(caplog):
    """Test `get_processing_status_for_date` when Firestore client is None."""
    with caplog.at_level(logging.WARNING):
        status = await firestore_client.get_processing_status_for_date("2025-12-30", [])
    assert status["error"] == "Firestore client is not available."
    assert status["reason_if_empty"] == "FIRESTORE_CONNECTION_FAILED"


async def test_get_processing_status_for_date_empty_daily_plan(mock_db):
    """Test `get_processing_status_for_date` with an empty daily plan."""

    date_str = "2025-12-30"
    daily_plan = []

    mock_query = MagicMock()
    mock_query.stream.return_value = []  # No races in DB
    mock_db.collection.return_value.order_by.return_value.start_at.return_value.end_at.return_value = mock_query

    status = await firestore_client.get_processing_status_for_date(date_str, daily_plan)
    assert status["counts"]["total_in_plan"] == 0
    assert status["counts"]["total_processed"] == 0
    assert status["reason_if_empty"] == "PLAN_SCRAPING_FAILED_OR_NO_RACES_TODAY"


async def test_get_processing_status_for_date_explicit_empty_plan_reason(mock_db):
    """Test `get_processing_status_for_date` explicitly covers the empty plan reason."""

    date_str = "2025-01-01"
    daily_plan = []

    mock_query = MagicMock()
    mock_query.stream.return_value = []
    mock_db.collection.return_value.order_by.return_value.start_at.return_value.end_at.return_value = mock_query

    status = await firestore_client.get_processing_status_for_date(date_str, daily_plan)
    assert status["reason_if_empty"] == "PLAN_SCRAPING_FAILED_OR_NO_RACES_TODAY"


async def test_get_processing_status_for_date_unprocessed_races(mock_db):
    """Test `get_processing_status_for_date` when daily plan has races but none are processed."""

    date_str = "2025-12-30"
    daily_plan = [
        {"rc": "R1C1", "time": "10:00"},
        {"rc": "R1C2", "time": "10:30"},
    ]

    mock_query = MagicMock()
    mock_query.stream.return_value = []  # No races in DB
    mock_db.collection.return_value.order_by.return_value.start_at.return_value.end_at.return_value = mock_query

    status = await firestore_client.get_processing_status_for_date(date_str, daily_plan)
    assert status["counts"]["total_in_plan"] == 2
    assert status["counts"]["total_processed"] == 0
    assert status["reason_if_empty"] == "NO_TASKS_PROCESSED_OR_FIRESTORE_EMPTY"


async def test_get_processing_status_for_date_error_decision(mock_db):
    """Test `get_processing_status_for_date` correctly counts error decisions."""

    date_str = "2025-12-30"
    daily_plan = [{"rc": "R1C1", "time": "10:00"}]
    mock_docs = [
        create_mock_doc(
            "2025-12-30_R1C1",
            "2025-12-30T10:05:00+00:00",
            {"tickets_analysis": {"gpi_decision": "error"}},
        ),
    ]
    mock_query = MagicMock()
    mock_query.stream.return_value = mock_docs
    mock_db.collection.return_value.order_by.return_value.start_at.return_value.end_at.return_value = mock_query

    status = await firestore_client.get_processing_status_for_date(date_str, daily_plan)
    assert status["counts"]["total_error"] == 1
    assert status["counts"]["total_playable"] == 0
    assert status["counts"]["total_abstain"] == 0


async def test_get_processing_status_for_date_unknown_decision(mock_db):
    """Test `get_processing_status_for_date` correctly handles unknown decisions (not counted in specific buckets)."""

    date_str = "2025-12-30"
    daily_plan = [{"rc": "R1C1", "time": "10:00"}]
    mock_docs = [
        create_mock_doc(
            "2025-12-30_R1C1",
            "2025-12-30T10:05:00+00:00",
            {"tickets_analysis": {"gpi_decision": "unknown_decision"}},
        ),
    ]
    mock_query = MagicMock()
    mock_query.stream.return_value = mock_docs
    mock_db.collection.return_value.order_by.return_value.start_at.return_value.end_at.return_value = mock_query

    status = await firestore_client.get_processing_status_for_date(date_str, daily_plan)
    assert status["counts"]["total_error"] == 0
    assert status["counts"]["total_playable"] == 0
    assert status["counts"]["total_abstain"] == 0
    assert status["counts"]["total_processed"] == 1  # Still processed


def test_get_document_success(mock_db):
    """Test get_document returns the document dictionary when it exists."""

    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {"foo": "bar"}
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    result = firestore_client.get_document("test_collection", "test_doc")

    assert result == {"foo": "bar"}
    mock_db.collection.assert_called_with("test_collection")
    mock_db.collection.return_value.document.assert_called_with("test_doc")
    mock_db.collection.return_value.document.return_value.get.assert_called_once()


def test_get_document_not_found(mock_db):
    """Test get_document returns None when the document does not exist."""

    mock_doc = MagicMock()
    mock_doc.exists = False
    mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

    result = firestore_client.get_document("test_collection", "test_doc")

    assert result is None
    mock_db.collection.assert_called_with("test_collection")


def test_get_document_exception(mock_db, caplog):
    """Test get_document handles exceptions and returns None."""

    mock_db.collection.return_value.document.return_value.get.side_effect = Exception(
        "Connection failed"
    )

    result = firestore_client.get_document("test_collection", "test_doc")

    assert result is None
    assert "Failed to get document 'test_doc'" in caplog.text


def test_set_document_success(mock_db):
    """Test set_document successfully calls the firestore client."""

    doc_ref_mock = MagicMock()
    mock_db.collection.return_value.document.return_value = doc_ref_mock

    data = {"key": "value"}
    firestore_client.set_document("test_collection", "test_doc", data)

    mock_db.collection.assert_called_once_with("test_collection")
    mock_db.collection.return_value.document.assert_called_once_with("test_doc")
    doc_ref_mock.set.assert_called_once_with(data)


def test_set_document_exception(mock_db, caplog):
    """Test that set_document handles exceptions."""

    mock_db.collection.side_effect = Exception("Permission denied")
    with caplog.at_level(logging.ERROR):
        firestore_client.set_document("test_collection", "test_doc", {"key": "value"})
    assert (
        "Failed to set document 'test_doc' in 'test_collection': Permission denied" in caplog.text
    )


@patch("hippique_orchestrator.firestore_client._get_firestore_client", return_value=None)
@patch("hippique_orchestrator.firestore_client.logger.warning")
async def test_get_races_for_date_db_unavailable(mock_warning, mock_get_firestore_client):
    """Test get_races_for_date when the database is unavailable."""

    races = await firestore_client.get_races_for_date("2025-12-30")
    assert races == []
    mock_warning.assert_called_once_with("Firestore is not available, cannot query races.")


@patch("hippique_orchestrator.firestore_client._get_firestore_client", return_value=None)
@patch("hippique_orchestrator.firestore_client.logger.warning")
def test_get_document_skips_if_db_not_available(mock_warning, mock_get_firestore_client):
    """Test that get_document skips if the db client is None."""

    result = firestore_client.get_document("test_collection", "test_doc")
    assert result is None
    mock_warning.assert_called_once_with("Firestore is not available, cannot get document.")


@patch("hippique_orchestrator.firestore_client._get_firestore_client", return_value=None)
@patch("hippique_orchestrator.firestore_client.logger.warning")
def test_set_document_skips_if_db_not_available(mock_warning, mock_get_firestore_client):
    """Test that set_document skips if the db client is None."""

    firestore_client.set_document("test_collection", "test_doc", {"key": "value"})
    # No return value to assert, just check logs
    mock_warning.assert_called_once_with("Firestore is not available, cannot set document.")
