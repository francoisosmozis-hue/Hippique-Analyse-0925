from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from google.api_core import exceptions
from hippique_orchestrator import gcs_utils


@pytest.fixture(autouse=True)
def mock_gcs_client():
    """Clear the GCS client singleton before each test."""
    gcs_utils._gcs_client = None


def test_is_gcs_enabled(monkeypatch):
    monkeypatch.setattr(gcs_utils.config, "BUCKET_NAME", "my-bucket")
    assert gcs_utils.is_gcs_enabled() is True


def test_is_gcs_disabled(monkeypatch):
    monkeypatch.setattr(gcs_utils.config, "BUCKET_NAME", None)
    assert gcs_utils.is_gcs_enabled() is False


def test_disabled_reason_when_disabled(monkeypatch):
    monkeypatch.setattr(gcs_utils.config, "BUCKET_NAME", None)
    assert gcs_utils.disabled_reason() == "GCS_BUCKET_not_set"


def test_disabled_reason_when_enabled(monkeypatch):
    monkeypatch.setattr(gcs_utils.config, "BUCKET_NAME", "my-bucket")
    assert gcs_utils.disabled_reason() is None


@patch("hippique_orchestrator.gcs_utils.storage.Client")
def test_get_gcs_client_initialization_success(mock_client_constructor):
    client = gcs_utils._get_gcs_client()
    assert client is not None
    mock_client_constructor.assert_called_once()
    # Test singleton behavior
    client2 = gcs_utils._get_gcs_client()
    assert client2 is client
    mock_client_constructor.assert_called_once()  # Still called only once


@patch(
    "hippique_orchestrator.gcs_utils.storage.Client",
    side_effect=Exception("Auth failure"),
)
def test_get_gcs_client_initialization_failure(mock_client_constructor, caplog):
    with caplog.at_level(logging.ERROR):
        client = gcs_utils._get_gcs_client()

    assert client is None
    assert "Failed to initialize GCS client: Auth failure" in caplog.text


def test_upload_file_gcs_disabled(monkeypatch, caplog):
    monkeypatch.setattr(gcs_utils.config, "BUCKET_NAME", None)
    with caplog.at_level(logging.DEBUG):
        gcs_utils.upload_file("any/path.json")
    assert not caplog.text


@patch("hippique_orchestrator.gcs_utils._get_gcs_client", return_value=None)
def test_upload_file_client_is_none(mock_get_client, monkeypatch):
    monkeypatch.setattr(gcs_utils.config, "BUCKET_NAME", "my-bucket")
    gcs_utils.upload_file("any/path.json")
    mock_get_client.assert_called_once()


def test_upload_file_local_file_not_found(monkeypatch, caplog):
    monkeypatch.setattr(gcs_utils.config, "BUCKET_NAME", "my-bucket")
    mock_local_file = MagicMock(spec=Path)
    mock_local_file.exists.return_value = False

    with patch("hippique_orchestrator.gcs_utils.Path", return_value=mock_local_file):
        with caplog.at_level(logging.WARNING):
            gcs_utils.upload_file("nonexistent/file.json")

    assert "Local file not found" in caplog.text


@pytest.mark.parametrize(
    "local_path, expected_gcs_path",
    [
        ("data/snapshots/R1C1/file.json", "prod/snapshots/R1C1/file.json"),
        ("snapshots/R1C2/file.json", "prod/snapshots/R1C2/file.json"),
        ("analyses/R1C3/file.json", "prod/analyses/R1C3/file.json"),
        ("some/other/path/data/analyses/R1/file.json", "prod/analyses/R1/file.json"),
        # Case where no known folder is found
        ("unknown/path/file.json", "prod/unknown/path/file.json"),
    ],
)
@patch("hippique_orchestrator.gcs_utils.storage.Client")
def test_upload_file_path_construction(
    mock_client_constructor, monkeypatch, local_path, expected_gcs_path
):
    monkeypatch.setattr(gcs_utils.config, "BUCKET_NAME", "my-bucket")
    mock_blob = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket
    mock_client_constructor.return_value = mock_client

    mock_local_file = MagicMock(spec=Path)
    mock_local_file.exists.return_value = True
    mock_local_file.parts = Path(local_path).parts
    mock_local_file.__str__.return_value = local_path

    with patch("hippique_orchestrator.gcs_utils.Path", return_value=mock_local_file):
        gcs_utils.upload_file(local_path)

    mock_client.bucket.assert_called_once_with("my-bucket")
    mock_bucket.blob.assert_called_once_with(expected_gcs_path)
    mock_blob.upload_from_filename.assert_called_once_with(local_path)


@patch("hippique_orchestrator.gcs_utils.storage.Client")
def test_upload_file_gcs_api_error(mock_client_constructor, monkeypatch, caplog):
    monkeypatch.setattr(gcs_utils.config, "BUCKET_NAME", "my-bucket")
    mock_blob = MagicMock()
    mock_blob.upload_from_filename.side_effect = exceptions.Forbidden("Permission denied")
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket
    mock_client_constructor.return_value = mock_client

    mock_local_file = MagicMock(spec=Path)
    mock_local_file.exists.return_value = True
    mock_local_file.parts = Path("data/snapshots/R1C1/file.json").parts

    with patch("hippique_orchestrator.gcs_utils.Path", return_value=mock_local_file):
        with caplog.at_level(logging.ERROR):
            gcs_utils.upload_file("data/snapshots/R1C1/file.json")

    assert "Failed to upload" in caplog.text
    assert "Permission denied" in caplog.text
