import base64
import json
import sys
from unittest.mock import MagicMock, patch

import pytest
from google.auth.exceptions import DefaultCredentialsError

pytest.importorskip("google.cloud.storage")

from scripts import drive_sync


def test_upload_file_uses_bucket_env(tmp_path, monkeypatch):
    path = tmp_path / "example.txt"
    path.write_text("data", encoding="utf-8")
    monkeypatch.setenv("GCS_BUCKET", "my-bucket")
    client = MagicMock()
    bucket = MagicMock()
    blob = MagicMock()
    bucket.blob.return_value = blob
    client.bucket.return_value = bucket

    drive_sync.upload_file(path, folder_id="prefix", service=client)

    client.bucket.assert_called_once_with("my-bucket")
    bucket.blob.assert_called_once_with("prefix/example.txt")
    blob.upload_from_filename.assert_called_once_with(str(path))


def test_upload_file_uses_env_prefix(tmp_path, monkeypatch):
    path = tmp_path / "env.txt"
    path.write_text("ok", encoding="utf-8")
    monkeypatch.setenv("GCS_BUCKET", "bucket")
    monkeypatch.setenv("GCS_PREFIX", "base/prefix")
    client = MagicMock()
    bucket = MagicMock()
    blob = MagicMock()
    bucket.blob.return_value = blob
    client.bucket.return_value = bucket

    drive_sync.upload_file(path, service=client)

    bucket.blob.assert_called_once_with("base/prefix/env.txt")


def test_upload_file_missing_bucket(tmp_path, monkeypatch):
    path = tmp_path / "missing.txt"
    path.write_text("x", encoding="utf-8")
    monkeypatch.delenv("GCS_BUCKET", raising=False)
    with pytest.raises(EnvironmentError):
        drive_sync.upload_file(path, service=MagicMock())


def test_download_file_calls_blob(tmp_path, monkeypatch):
    dest = tmp_path / "out" / "file.txt"
    monkeypatch.setenv("GCS_BUCKET", "bucket")
    client = MagicMock()
    bucket = MagicMock()
    blob = MagicMock()
    bucket.blob.return_value = blob
    client.bucket.return_value = bucket

    result = drive_sync.download_file("object/name.json", dest, service=client)

    assert result == dest
    assert dest.parent.exists()
    bucket.blob.assert_called_once_with("object/name.json")
    blob.download_to_filename.assert_called_once_with(str(dest))


def test_push_tree_uploads_all_files(tmp_path, monkeypatch):
    (tmp_path / "sub").mkdir()
    (tmp_path / "root.txt").write_text("r", encoding="utf-8")
    (tmp_path / "sub" / "child.txt").write_text("c", encoding="utf-8")

    monkeypatch.setenv("GCS_BUCKET", "bucket")
    client = MagicMock()
    bucket = MagicMock()
    created: dict[str, MagicMock] = {}

    def _blob(name: str):
        created[name] = MagicMock()
        return created[name]

    bucket.blob.side_effect = _blob
    client.bucket.return_value = bucket

    drive_sync.push_tree(tmp_path, folder_id="prefix", service=client)

    assert set(created) == {"prefix/root.txt", "prefix/sub/child.txt"}
    for blob in created.values():
        blob.upload_from_filename.assert_called_once()


def test_main_honours_env_prefix(monkeypatch):
    monkeypatch.setenv("GCS_BUCKET", "bucket")
    monkeypatch.setenv("GCS_PREFIX", "env/prefix")
    monkeypatch.setattr(drive_sync, "is_gcs_enabled", lambda: True)
    client = MagicMock(name="client")
    monkeypatch.setattr(drive_sync, "_build_service", lambda *a, **k: client)
    push_mock = MagicMock()
    monkeypatch.setattr(drive_sync, "push_tree", push_mock)
    monkeypatch.setattr(drive_sync, "upload_file", MagicMock())
    monkeypatch.setattr(drive_sync, "download_file", MagicMock())
    monkeypatch.setattr(drive_sync, "_iter_uploads", lambda patterns: [])
    monkeypatch.setattr(sys, "argv", ["drive_sync.py", "--push", "data"])

    result = drive_sync.main()

    assert result == 0
    push_mock.assert_called_once_with(
        "data", folder_id="env/prefix", bucket="bucket", service=client
    )


def test_main_skips_when_credentials_missing(monkeypatch, capsys):
    monkeypatch.setattr(drive_sync, "is_gcs_enabled", lambda: True)
    monkeypatch.setattr(sys, "argv", ["drive_sync.py"])
    
    def _raise_missing(*_args, **_kwargs):
        raise DefaultCredentialsError("missing")

    monkeypatch.setattr(drive_sync, "_build_service", _raise_missing)
    result = drive_sync.main()

    captured = capsys.readouterr()
    assert result == 0
    assert (
        "[drive_sync] no Google Cloud credentials detected → skipping Google Cloud Storage synchronisation."
        in captured.out
    )


def test_build_service_env(monkeypatch):
    creds_data = {"type": "service_account"}
    encoded = base64.b64encode(json.dumps(creds_data).encode()).decode()
    monkeypatch.setenv("GCS_SERVICE_KEY_B64", encoded)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj-id")

    with patch(
        "scripts.drive_sync.service_account.Credentials.from_service_account_info"
    ) as cred_mock, patch("scripts.drive_sync.storage.Client") as client_mock:
        cred_mock.return_value = "creds"
        client_mock.return_value = "client"
        client = drive_sync._build_service()

    cred_mock.assert_called_once_with(creds_data, scopes=drive_sync.SCOPES)
    client_mock.assert_called_once_with(project="proj-id", credentials="creds")
    assert client == "client"


@pytest.mark.parametrize("project_env", [None, ""])
def test_build_service_missing_env(monkeypatch, project_env):
    monkeypatch.delenv("GCS_SERVICE_KEY_B64", raising=False)
    monkeypatch.delenv("GCS_SERVICE_KEY_JSON", raising=False)
    if project_env is None:
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    else:
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", project_env)
    with patch("scripts.drive_sync.storage.Client") as client_mock:
        client = drive_sync._build_service()
    client_mock.assert_called_once_with(project=None)
    assert client == client_mock.return_value
