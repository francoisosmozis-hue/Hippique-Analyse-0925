from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("google.cloud.storage")

from src import gcs


def test_upload_artifacts_uses_bucket_env(tmp_path, monkeypatch):
    # Arrange
    rc_dir = tmp_path / "R1C1"
    rc_dir.mkdir()
    artifact1 = rc_dir / "artifact1.txt"
    artifact1.write_text("data1")
    artifacts = [str(artifact1)]

    config_mock = MagicMock()
    config_mock.gcs_bucket = "my-bucket"
    config_mock.gcs_prefix = "my-prefix"

    client_mock = MagicMock()
    bucket_mock = MagicMock()
    blob_mock = MagicMock()

    client_mock.bucket.return_value = bucket_mock
    bucket_mock.blob.return_value = blob_mock

    with patch("src.gcs.Config", return_value=config_mock), \
         patch("google.cloud.storage.Client", return_value=client_mock) as storage_client_mock:
        # Act
        gcs.upload_artifacts(rc_dir, artifacts)

        # Assert
        storage_client_mock.assert_called_once_with()
        client_mock.bucket.assert_called_once_with("my-bucket")

        expected_gcs_path = f"my-prefix/{rc_dir.name}/{artifact1.name}"
        bucket_mock.blob.assert_called_once_with(expected_gcs_path)
        blob_mock.upload_from_filename.assert_called_once_with(str(artifact1))
