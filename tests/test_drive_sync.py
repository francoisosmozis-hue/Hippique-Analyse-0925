import io
import json
from unittest.mock import MagicMock, patch, ANY

import pytest
from googleapiclient.errors import HttpError
from httplib2 import Response

from scripts import drive_sync


def _http_error(status: str = "403", msg: bytes = b"error") -> HttpError:
    return HttpError(Response({"status": status}), msg)


def test_upload_file_calls_create(tmp_path):
    path = tmp_path / "example.txt"
    path.write_text("data", encoding="utf-8")
    service = MagicMock()
    service.files.return_value.create.return_value.execute.return_value = {"id": "123"}
    with patch("scripts.drive_sync.MediaFileUpload") as media_mock:
        drive_sync.upload_file(path, folder_id="FOLDER", service=service)
    service.files.return_value.create.assert_called_once()
    args, kwargs = service.files.return_value.create.call_args
    assert kwargs["fields"] == "id"
    assert kwargs["body"] == {"name": "example.txt", "parents": ["FOLDER"]}
    media_mock.assert_called_once_with(str(path), resumable=True)


def test_download_file_calls_get_media(tmp_path):
    dest = tmp_path / "out.txt"
    service = MagicMock()
    service.files.return_value.get_media.return_value = "request"
    downloader = MagicMock()
    downloader.next_chunk.side_effect = [(None, True)]
    with patch("scripts.drive_sync.MediaIoBaseDownload", return_value=downloader) as dl_mock:
        drive_sync.download_file("FILEID", dest, service=service)
    service.files.return_value.get_media.assert_called_once_with(fileId="FILEID")
    dl_mock.assert_called_once_with(ANY, "request")
    assert downloader.next_chunk.call_count == 1


def test_upload_file_uses_env_folder(tmp_path, monkeypatch):
    path = tmp_path / "env.txt"
    path.write_text("ok", encoding="utf-8")
    service = MagicMock()
    service.files.return_value.create.return_value.execute.return_value = {"id": "x"}
    monkeypatch.setenv("DRIVE_FOLDER_ID", "ENV_FOLDER")
    drive_sync.upload_file(path, service=service)
    body = service.files.return_value.create.call_args.kwargs["body"]
    assert body["parents"] == ["ENV_FOLDER"]


def test_upload_file_missing_folder(tmp_path, monkeypatch):
    path = tmp_path / "missing.txt"
    path.write_text("x", encoding="utf-8")
    service = MagicMock()
    monkeypatch.delenv("DRIVE_FOLDER_ID", raising=False)
    with pytest.raises(EnvironmentError):
        drive_sync.upload_file(path, service=service)


def test_build_service_env(monkeypatch):
    creds_data = {"type": "service_account"}
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", json.dumps(creds_data))
    with patch("scripts.drive_sync.service_account.Credentials.from_service_account_info") as cred_mock, patch("scripts.drive_sync.build") as build_mock:
        cred_mock.return_value = "creds"
        build_mock.return_value = "service"
        service = drive_sync._build_service()
    cred_mock.assert_called_once_with(creds_data, scopes=drive_sync.SCOPES)
    build_mock.assert_called_once_with("drive", "v3", credentials="creds")
    assert service == "service"


def test_build_service_missing_env(monkeypatch):
    monkeypatch.delenv("GOOGLE_CREDENTIALS_JSON", raising=False)
    with pytest.raises(EnvironmentError):
        drive_sync._build_service()


def test_upload_file_quota_error(tmp_path):
    path = tmp_path / "quota.txt"
    path.write_text("1", encoding="utf-8")
    service = MagicMock()
    service.files.return_value.create.side_effect = _http_error()
    with pytest.raises(HttpError):
        drive_sync.upload_file(path, folder_id="FOLDER", service=service)


def test_download_file_permission_error(tmp_path):
    dest = tmp_path / "perm.txt"
    service = MagicMock()
    service.files.return_value.get_media.side_effect = _http_error()
    with pytest.raises(HttpError):
        drive_sync.download_file("ID", dest, service=service)
