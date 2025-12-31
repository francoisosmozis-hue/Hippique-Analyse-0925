
import pytest
from unittest.mock import patch, MagicMock
from hippique_orchestrator import gcs_client
from hippique_orchestrator import config

@pytest.fixture
def gcs_manager(monkeypatch):
    monkeypatch.setattr(config, "BUCKET_NAME", "test-bucket")
    gcs_client.get_gcs_manager.cache_clear()
    gcs_client.get_gcs_fs.cache_clear()
    return gcs_client.get_gcs_manager()

def test_gcs_manager_init(monkeypatch):
    monkeypatch.setattr(config, "BUCKET_NAME", "test-bucket")
    manager = gcs_client.GCSManager()
    assert manager.bucket_name == "test-bucket"

    manager_with_arg = gcs_client.GCSManager(bucket_name="another-bucket")
    assert manager_with_arg.bucket_name == "another-bucket"

def test_gcs_manager_init_no_bucket(monkeypatch):
    monkeypatch.setattr(config, "BUCKET_NAME", None)
    with pytest.raises(ValueError, match="GCS_BUCKET must be set"):
        gcs_client.GCSManager()

def test_gcs_manager_lazy_init(gcs_manager, mocker):
    mock_storage_client = mocker.patch("google.cloud.storage.Client")
    mock_gcsfs = mocker.patch("gcsfs.GCSFileSystem")

    assert gcs_manager._client is None
    assert gcs_manager._fs is None

    _ = gcs_manager.client
    mock_storage_client.assert_called_once()
    assert gcs_manager._client is not None

    _ = gcs_manager.fs
    mock_gcsfs.assert_called_once()
    assert gcs_manager._fs is not None

def test_get_gcs_path(gcs_manager):
    assert gcs_manager.get_gcs_path("test/path") == "gs://test-bucket/test/path"

def test_file_exists(gcs_manager, mocker):
    mock_gcsfs = mocker.patch("gcsfs.GCSFileSystem")
    mock_fs_instance = mock_gcsfs.return_value
    
    mock_fs_instance.exists.return_value = True
    assert gcs_manager.file_exists("gs://test-bucket/test/path") is True
    mock_fs_instance.exists.assert_called_with("gs://test-bucket/test/path")

    mock_fs_instance.exists.return_value = False
    assert gcs_manager.file_exists("gs://test-bucket/test/path") is False

def test_get_gcs_fs(gcs_manager, mocker):
    mock_gcsfs = mocker.patch("gcsfs.GCSFileSystem")
    mock_fs_instance = mock_gcsfs.return_value
    
    fs = gcs_manager.fs
    assert fs is mock_fs_instance


def test_get_gcs_manager_no_bucket(monkeypatch):
    monkeypatch.setattr(config, "BUCKET_NAME", None)
    gcs_client.get_gcs_manager.cache_clear()
    assert gcs_client.get_gcs_manager() is None

def test_get_gcs_manager_singleton(monkeypatch):
    monkeypatch.setattr(config, "BUCKET_NAME", "test-bucket")
    gcs_client.get_gcs_manager.cache_clear()
    manager1 = gcs_client.get_gcs_manager()
    manager2 = gcs_client.get_gcs_manager()
    assert manager1 is manager2

def test_get_gcs_fs(gcs_manager, mocker):
    mock_gcsfs = mocker.patch("gcsfs.GCSFileSystem")
    mock_fs_instance = mock_gcsfs.return_value
    
    fs = gcs_manager.fs
    assert fs is mock_fs_instance

def test_get_gcs_fs_no_manager(monkeypatch):
    monkeypatch.setattr(config, "BUCKET_NAME", None)
    gcs_client.get_gcs_manager.cache_clear()
    gcs_client.get_gcs_fs.cache_clear()
    assert gcs_client.get_gcs_fs() is None

def test_build_gcs_path(gcs_manager):
    assert gcs_client.build_gcs_path("test/path") == "gs://test-bucket/test/path"

def test_build_gcs_path_no_manager(monkeypatch):
    monkeypatch.setattr(config, "BUCKET_NAME", None)
    gcs_client.get_gcs_manager.cache_clear()
    assert gcs_client.build_gcs_path("test/path") is None
