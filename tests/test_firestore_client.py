
import pytest
from unittest.mock import MagicMock, patch
from google.cloud.firestore import DocumentSnapshot

# We need to patch the client at the source, where it's looked up.
FIRESTORE_CLIENT_PATH = "hippique_orchestrator.firestore_client.db"


@pytest.fixture
def mock_db():
    """Fixture to mock the global firestore client."""
    with patch(FIRESTORE_CLIENT_PATH, MagicMock()) as mock_client:
        yield mock_client


def test_update_race_document_success(mock_db):
    """Test that `update_race_document` calls firestore `set` with merge=True."""
    from hippique_orchestrator import firestore_client

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
    from hippique_orchestrator import firestore_client

    mock_db.collection.side_effect = Exception("Firestore unavailable")

    firestore_client.update_race_document("some_id", {"data": "value"})

    assert "Failed to update document some_id" in caplog.text
    assert "Firestore unavailable" in caplog.text


@patch(FIRESTORE_CLIENT_PATH, None)
def test_update_race_document_skips_if_db_not_available(caplog):
    """Test that updates are skipped if the db client is None."""
    from hippique_orchestrator import firestore_client

    firestore_client.update_race_document("any_id", {})
    assert "Firestore is not available, skipping update" in caplog.text


def test_get_races_for_date_success(mock_db):
    """Test `get_races_for_date` returns a list of document snapshots."""
    from hippique_orchestrator import firestore_client

    # Create mock documents
    doc1_mock = MagicMock(spec=DocumentSnapshot)
    doc2_mock = MagicMock(spec=DocumentSnapshot)
    
    mock_query = MagicMock()
    mock_query.stream.return_value = [doc1_mock, doc2_mock]
    
    mock_db.collection.return_value.order_by.return_value.start_at.return_value.end_at.return_value = mock_query

    date_str = "2025-12-30"
    results = firestore_client.get_races_for_date(date_str)

    assert len(results) == 2
    assert results[0] == doc1_mock
    mock_db.collection.assert_called_once_with("races-test")
    mock_db.collection.return_value.order_by.assert_called_with("__name__")


def test_get_races_for_date_empty(mock_db):
    """Test `get_races_for_date` returns an empty list when no documents are found."""
    from hippique_orchestrator import firestore_client

    mock_query = MagicMock()
    mock_query.stream.return_value = []
    
    mock_db.collection.return_value.order_by.return_value.start_at.return_value.end_at.return_value = mock_query
    
    results = firestore_client.get_races_for_date("2025-12-30")
    
    assert results == []


def test_get_races_for_date_handles_exception(mock_db, caplog):
    """Test that exceptions during race query are logged and return an empty list."""
    from hippique_orchestrator import firestore_client

    mock_db.collection.side_effect = Exception("Query failed")

    results = firestore_client.get_races_for_date("2025-12-30")

    assert "Failed to query races by date 2025-12-30" in caplog.text
    assert "Query failed" in caplog.text
    assert results == []


@pytest.mark.parametrize(
    "url, date, expected",
    [
        ("https://www.zeturf.fr/fr/course/2025-12-25/R1C2-test-pmu", "2025-12-25", "2025-12-25_R1C2"),
        ("https://turf.fr/R5C3/details", "2025-12-25", "2025-12-25_R5C3"),
        ("R3C8", "2025-12-25", "2025-12-25_R3C8"),
        ("some-string-r4c1-other", "2025-12-25", "2025-12-25_R4C1"),
        ("invalid-url", "2025-12-25", None),
        ("", "2025-12-25", None),
    ],
)
def test_get_doc_id_from_url(url, date, expected):
    """Test `get_doc_id_from_url` correctly parses various URL formats."""
    from hippique_orchestrator import firestore_client
    assert firestore_client.get_doc_id_from_url(url, date) == expected

