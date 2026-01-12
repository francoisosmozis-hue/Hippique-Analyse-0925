import datetime
from unittest.mock import MagicMock, patch

import pytest

from hippique_orchestrator import tickets_store


# Mock the GCS client and related objects
@pytest.fixture
def mock_gcs_client():
    with patch("hippique_orchestrator.tickets_store.storage.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client_cls.return_value = mock_client
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        yield mock_client_cls, mock_client, mock_bucket, mock_blob


@pytest.fixture(autouse=True)
def mock_tickets_bucket():
    # Patch TICKETS_BUCKET directly, as it's accessed at module level
    with patch("hippique_orchestrator.tickets_store.TICKETS_BUCKET", "test-bucket"):
        yield


def test_client_returns_storage_client(mock_gcs_client):
    mock_client_cls, _, _, _ = mock_gcs_client
    client = tickets_store._client()
    mock_client_cls.assert_called_once_with()
    assert isinstance(client, MagicMock)  # Ensure it's the mocked client


def test_blob_path_constructs_correct_path():
    date_str = "2025-12-31"
    rxcy = "R1C1"
    expected_path = f"{tickets_store.TICKETS_PREFIX}/{date_str}/{rxcy}.html"
    assert tickets_store._blob_path(date_str, rxcy) == expected_path


def test_index_path_constructs_correct_path():
    expected_path = f"{tickets_store.TICKETS_PREFIX}/index.html"
    assert tickets_store._index_path() == expected_path


def test_render_ticket_html_full_payload():
    payload = {
        "ev": 1.2,
        "roi": 0.15,
        "tickets": [{"runner": "Horse A", "odds": 5.0}],
        "some_other_data": "value",
    }
    reunion = "R1"
    course = "C1"
    phase = "h5"
    budget = 100.0

    html = tickets_store.render_ticket_html(
        payload, reunion=reunion, course=course, phase=phase, budget=budget
    )

    assert "<h1>Ticket R1C1</h1>" in html
    assert "<div><b>Réunion:</b> R1</div>" in html
    assert "<div><b>Course:</b> C1</div>" in html
    assert "<div><b>Budget:</b> 100.0 €</div>" in html
    assert "<div><b>EV estimée:</b> 1.2</div>" in html
    assert "<div><b>ROI estimé:</b> 0.15</div>" in html
    assert '"runner": "Horse A"' in html
    assert '"odds": 5.0' in html
    assert '"some_other_data": "value"' in html


def test_render_ticket_html_minimal_payload():
    payload = {}
    reunion = "R2"
    course = "C2"
    phase = "h30"
    budget = 50.0

    html = tickets_store.render_ticket_html(
        payload, reunion=reunion, course=course, phase=phase, budget=budget
    )

    assert "<h1>Ticket R2C2</h1>" in html
    assert "<div><b>Réunion:</b> R2</div>" in html
    assert "<div><b>Course:</b> C2</div>" in html
    assert "<div><b>Budget:</b> 50.0 €</div>" in html
    assert "<div><b>EV estimée:</b> n/a</div>" in html
    assert "<div><b>ROI estimé:</b> n/a</div>" in html
    # Adjusted assertion for empty list representation
    assert "<pre>[]</pre>" in html


def test_render_ticket_html_different_keys_for_ev_roi_tickets():
    payload = {
        "ev_global": 1.3,
        "roi_estime": 0.20,  # Will be rendered as 0.2
        "ticket": [{"runner": "Horse B", "odds": 3.0}],
    }
    reunion = "R3"
    course = "C3"
    phase = "h1"
    budget = 75.0

    html = tickets_store.render_ticket_html(
        payload, reunion=reunion, course=course, phase=phase, budget=budget
    )

    assert "<div><b>EV estimée:</b> 1.3</div>" in html
    # Adjusted assertion for float representation
    assert "<div><b>ROI estimé:</b> 0.2</div>" in html
    assert '"runner": "Horse B"' in html
    assert '"odds": 3.0' in html


def test_save_ticket_html_success(mock_gcs_client):
    _, _, mock_bucket, mock_blob = mock_gcs_client
    html_content = "<html>test</html>"
    date_str = "2025-12-31"
    rxcy = "R1C1"

    tickets_store.save_ticket_html(html_content, date_str=date_str, rxcy=rxcy)

    mock_bucket.blob.assert_called_once_with(
        f"{tickets_store.TICKETS_PREFIX}/{date_str}/{rxcy}.html"
    )
    assert mock_blob.cache_control == "no-cache"
    assert mock_blob.content_type == "text/html; charset=utf-8"
    mock_blob.upload_from_string.assert_called_once_with(
        html_content, content_type="text/html; charset=utf-8"
    )


def test_save_ticket_html_no_bucket_env_var_raises_error():
    # Clear the patch for this specific test
    with patch("hippique_orchestrator.tickets_store.TICKETS_BUCKET", None):
        with pytest.raises(AssertionError, match="TICKETS_BUCKET non défini"):
            tickets_store.save_ticket_html("<html></html>", date_str="2025-12-31", rxcy="R1C1")


def test_build_and_save_ticket_success(mock_gcs_client):
    _, _, _, _ = mock_gcs_client
    payload = {"ev": 1.2, "roi": 0.15, "tickets": []}
    reunion = "R1"
    course = "C1"
    phase = "h5"
    budget = 100.0

    # Mock render_ticket_html as well to isolate build_and_save_ticket logic
    with patch(
        "hippique_orchestrator.tickets_store.render_ticket_html", return_value="mocked html"
    ) as mock_render:
        with patch("hippique_orchestrator.tickets_store.save_ticket_html") as mock_save:
            result = tickets_store.build_and_save_ticket(
                payload, reunion=reunion, course=course, phase=phase, budget=budget
            )
            mock_render.assert_called_once()
            mock_save.assert_called_once_with(
                "mocked html",
                date_str=datetime.datetime.now().strftime("%Y-%m-%d"),
                rxcy=f"{reunion}{course}",
            )
            assert (
                result == f"{datetime.datetime.now().strftime('%Y-%m-%d')}/{reunion}{course}.html"
            )


def test_list_ticket_objects_success(mock_gcs_client):
    mock_client_cls, mock_client, mock_bucket, mock_blob = mock_gcs_client

    # Simulate blob listing
    mock_blob1 = MagicMock()
    mock_blob1.name = "tickets/2025-12-30/R1C1.html"
    mock_blob1.size = 100
    mock_blob2 = MagicMock()
    mock_blob2.name = "tickets/2025-12-31/R1C2.html"
    mock_blob2.size = 200
    mock_blob_other = MagicMock()
    mock_blob_other.name = "tickets/some_other_file.txt"
    mock_blob_index = MagicMock()
    mock_blob_index.name = "tickets/index.html"

    mock_client.list_blobs.return_value = [mock_blob1, mock_blob2, mock_blob_other, mock_blob_index]

    items = tickets_store.list_ticket_objects()

    mock_client.list_blobs.assert_called_once_with(
        mock_bucket, prefix=f"{tickets_store.TICKETS_PREFIX}/", max_results=200
    )
    assert len(items) == 2
    assert items[0]["date"] == "2025-12-31"
    assert items[0]["key"] == "R1C2"
    assert items[0]["size"] == 200
    assert items[1]["date"] == "2025-12-30"
    assert items[1]["key"] == "R1C1"
    assert items[1]["size"] == 100


def test_list_ticket_objects_empty_list(mock_gcs_client):
    _, mock_client, mock_bucket, _ = mock_gcs_client
    mock_client.list_blobs.return_value = iter([])  # Explicitly return an empty iterator
    items = tickets_store.list_ticket_objects()
    assert items == []


def test_list_ticket_objects_no_bucket_env_var_raises_error():
    with patch("hippique_orchestrator.tickets_store.TICKETS_BUCKET", None):
        with pytest.raises(AssertionError, match="TICKETS_BUCKET non défini"):
            tickets_store.list_ticket_objects()


def test_rebuild_index_success(mock_gcs_client):
    _, mock_client, mock_bucket, mock_blob = mock_gcs_client

    mock_list_ticket_objects_return_value = [
        {"date": "2025-12-30", "key": "R1C1", "size": 100},
    ]

    with patch(
        "hippique_orchestrator.tickets_store.list_ticket_objects",
        return_value=mock_list_ticket_objects_return_value,
    ) as mock_list_ticket_objects:
        tickets_store.rebuild_index()

        mock_list_ticket_objects.assert_called_once()
        mock_bucket.blob.assert_called_once_with(f"{tickets_store.TICKETS_PREFIX}/index.html")
        assert mock_blob.cache_control == "no-cache"
        assert mock_blob.content_type == "text/html; charset=utf-8"
        mock_blob.upload_from_string.assert_called_once()
        uploaded_content = mock_blob.upload_from_string.call_args[0][0]
        assert "<h1>Tickets disponibles</h1>" in uploaded_content
        assert (
            '<li><a href="/tickets/2025-12-30/R1C1.html">2025-12-30 – R1C1</a>' in uploaded_content
        )


def test_rebuild_index_no_bucket_env_var_raises_error():
    with patch("hippique_orchestrator.tickets_store.TICKETS_BUCKET", None):
        with pytest.raises(AssertionError, match="TICKETS_BUCKET non défini"):
            tickets_store.rebuild_index()


def test_load_ticket_html_success(mock_gcs_client):
    _, _, mock_bucket, mock_blob = mock_gcs_client
    mock_blob.download_as_text.return_value = "mocked ticket html"
    date_str = "2025-12-31"
    rxcy = "R1C1"

    html = tickets_store.load_ticket_html(date_str, rxcy)

    mock_bucket.blob.assert_called_once_with(
        f"{tickets_store.TICKETS_PREFIX}/{date_str}/{rxcy}.html"
    )
    mock_blob.download_as_text.assert_called_once_with(encoding="utf-8")
    assert html == "mocked ticket html"


def test_load_ticket_html_no_bucket_env_var_raises_error():
    with patch("hippique_orchestrator.tickets_store.TICKETS_BUCKET", None):
        with pytest.raises(AssertionError, match="TICKETS_BUCKET non défini"):
            tickets_store.load_ticket_html("2025-12-31", "R1C1")
