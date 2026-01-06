import logging

import pytest

from hippique_orchestrator import config, gcs_client


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


def test_gcs_manager_init_no_bucket(monkeypatch, caplog):
    monkeypatch.setattr(config, "BUCKET_NAME", None)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match="GCS_BUCKET must be set"):
            gcs_client.GCSManager()
    assert "GCS_BUCKET is not set in the configuration. GCS operations will fail." in caplog.text


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


def test_get_gcs_fs_no_manager(monkeypatch):
    monkeypatch.setattr(config, "BUCKET_NAME", None)
    gcs_client.get_gcs_manager.cache_clear()  # Explicitly clear manager cache
    gcs_client.get_gcs_fs.cache_clear()
    assert gcs_client.get_gcs_fs() is None


def test_build_gcs_path(gcs_manager):
    assert gcs_client.build_gcs_path("test/path") == "gs://test-bucket/test/path"


def test_build_gcs_path_no_manager(monkeypatch):
    monkeypatch.setattr(config, "BUCKET_NAME", None)
    gcs_client.get_gcs_manager.cache_clear()  # Explicitly clear manager cache
    assert gcs_client.build_gcs_path("test/path") is None


def test_gcs_manager_save_json_to_gcs_exception(gcs_manager, mocker):
    mocker.patch(
        "hippique_orchestrator.gcs_client.json.dump", side_effect=Exception("Mock GCS write error")
    )
    _ = mocker.patch.object(gcs_manager.fs, "open")

    gcs_path = "gs://test-bucket/error.json"
    data = {"key": "value"}

    with pytest.raises(Exception, match="Mock GCS write error"):
        gcs_manager.save_json_to_gcs(gcs_path, data)


def test_gcs_manager_save_json_to_gcs_success(gcs_manager, mocker, caplog):
    mock_fs_open = mocker.patch.object(gcs_manager.fs, "open")
    _ = mocker.patch("hippique_orchestrator.gcs_client.json.dump")

    gcs_path = "gs://test-bucket/test.json"
    data = {"key": "value"}

    with caplog.at_level(logging.INFO):
        gcs_manager.save_json_to_gcs(gcs_path, data)

    mock_fs_open.assert_called_once_with(gcs_path, 'w')


def test_global_save_json_to_gcs_success(monkeypatch, mocker):
    monkeypatch.setattr(config, "BUCKET_NAME", "test-bucket")
    gcs_client.get_gcs_manager.cache_clear()
    gcs_client.get_gcs_fs.cache_clear()

    mock_manager_save = mocker.patch.object(gcs_client.GCSManager, "save_json_to_gcs")

    gcs_path = "gs://test-bucket/success.json"
    data = {"another": "value"}

    gcs_client.save_json_to_gcs(gcs_path, data)

    mock_manager_save.assert_called_once_with(gcs_path, data)


def test_global_save_json_to_gcs_no_manager_raises_runtime_error(monkeypatch, caplog):
    monkeypatch.setattr(config, "BUCKET_NAME", None)
    gcs_client.get_gcs_manager.cache_clear()

    gcs_path = "gs://test-bucket/error.json"
    data = {"key": "value"}

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="GCSManager not initialized."):
            gcs_client.save_json_to_gcs(gcs_path, data)

    assert "GCSManager not initialized. Cannot save JSON to" in caplog.text
