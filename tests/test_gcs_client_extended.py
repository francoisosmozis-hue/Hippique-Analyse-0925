import logging
from unittest.mock import MagicMock, patch

import pytest

from hippique_orchestrator import config, gcs_client


@pytest.fixture
def gcs_manager(monkeypatch):
    monkeypatch.setattr(config, "BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(config, "GCS_ENABLED", True)  # Ensure GCS is enabled for the test
    gcs_client.reset_gcs_manager()
    return gcs_client.get_gcs_manager()


def test_gcs_manager_init(monkeypatch):
    monkeypatch.setattr(config, "BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(config, "GCS_ENABLED", True)
    manager = gcs_client.GCSManager()
    assert manager.bucket_name == "test-bucket"

    manager_with_arg = gcs_client.GCSManager(bucket_name="another-bucket")
    assert manager_with_arg.bucket_name == "another-bucket"


def test_gcs_manager_init_no_bucket(monkeypatch, caplog):
    monkeypatch.setattr(config, "BUCKET_NAME", None)
    monkeypatch.setattr(config, "GCS_ENABLED", True) # GCS enabled, but no bucket
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match="GCS_BUCKET must be set when GCS_ENABLED is True."):
            gcs_client.GCSManager()
    assert "GCS_BUCKET is not set in the configuration, but GCS_ENABLED is True. GCS operations will fail." in caplog.text


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


def test_get_gcs_manager_no_bucket(monkeypatch, caplog):
    monkeypatch.setattr(config, "BUCKET_NAME", None)
    monkeypatch.setattr(config, "GCS_ENABLED", True) # GCS enabled, but no bucket
    gcs_client.reset_gcs_manager()
    with caplog.at_level(logging.WARNING):
        assert gcs_client.get_gcs_manager() is None


def test_get_gcs_manager_singleton(monkeypatch):
    monkeypatch.setattr(config, "BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(config, "GCS_ENABLED", True)
    gcs_client.reset_gcs_manager()
    manager1 = gcs_client.get_gcs_manager()
    manager2 = gcs_client.get_gcs_manager()
    assert manager1 is manager2


def test_get_gcs_fs_no_manager(monkeypatch):
    monkeypatch.setattr(config, "BUCKET_NAME", None)
    monkeypatch.setattr(config, "GCS_ENABLED", True) # GCS enabled, but no bucket
    gcs_client.reset_gcs_manager()  # Explicitly clear manager cache
    assert gcs_client.get_gcs_fs() is None


def test_build_gcs_path(gcs_manager):
    assert gcs_client.build_gcs_path("test/path") == "gs://test-bucket/test/path"


def test_build_gcs_path_no_manager(monkeypatch, caplog):
    monkeypatch.setattr(config, "BUCKET_NAME", None)
    monkeypatch.setattr(config, "GCS_ENABLED", True) # GCS enabled, but no bucket
    gcs_client.reset_gcs_manager()  # Explicitly clear manager cache
    with caplog.at_level(logging.ERROR):
        assert gcs_client.build_gcs_path("test/path") is None
    assert "GCSManager is not initialized. Cannot build GCS path." in caplog.text


def test_gcs_manager_save_json_to_gcs_exception(gcs_manager, mocker):
    mocker.patch(
        "hippique_orchestrator.gcs_client.json.dump", side_effect=Exception("Mock GCS write error")
    )
    # Patch self.fs.open directly, not gcs_client.fs.open
    mock_fs_open = mocker.patch.object(gcs_manager.fs, "open")

    gcs_path = "gs://test-bucket/error.json"
    data = {"key": "value"}

    with pytest.raises(Exception, match="Mock GCS write error"):
        gcs_manager.save_json_to_gcs(gcs_path, data)
    
    mock_fs_open.assert_called_once_with(gcs_path, 'w')


def test_gcs_manager_save_json_to_gcs_success(gcs_manager, mocker, caplog):
    mock_fs_open = mocker.patch.object(gcs_manager.fs, "open")
    mocker.patch("hippique_orchestrator.gcs_client.json.dump")

    gcs_path = "gs://test-bucket/test.json"
    data = {"key": "value"}

    with caplog.at_level(logging.INFO):
        gcs_manager.save_json_to_gcs(gcs_path, data)

    mock_fs_open.assert_called_once_with(gcs_path, 'w')
    assert f"Successfully saved JSON to {gcs_path}" in caplog.text


def test_global_save_json_to_gcs_success(monkeypatch, mocker):
    monkeypatch.setattr(config, "BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(config, "GCS_ENABLED", True)
    gcs_client.reset_gcs_manager()

    mock_manager_save = mocker.patch.object(gcs_client.GCSManager, "save_json_to_gcs")

    gcs_path = "gs://test-bucket/success.json"
    data = {"another": "value"}

    gcs_client.save_json_to_gcs(gcs_path, data)

    mock_manager_save.assert_called_once_with(gcs_client.build_gcs_path(gcs_path), data)


def test_global_save_json_to_gcs_no_manager_raises_runtime_error(monkeypatch, caplog):
    monkeypatch.setattr(config, "BUCKET_NAME", None)
    monkeypatch.setattr(config, "GCS_ENABLED", False) # GCS explicitly disabled
    gcs_client.reset_gcs_manager()

    gcs_path = "gs://test-bucket/error.json"
    data = {"key": "value"}

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="GCSManager not initialized or GCS disabled."):
            gcs_client.save_json_to_gcs(gcs_path, data)

    assert "GCSManager not initialized. Cannot save JSON to" in caplog.text


# New tests for list_files and read_file_from_gcs
def test_gcs_manager_list_files_success(gcs_manager, mocker):
    mock_fs_ls = mocker.patch.object(gcs_manager.fs, "ls")
    mock_fs_ls.return_value = [
        {"name": "test-bucket/dir/file1.json", "type": "file"},
        {"name": "test-bucket/dir/subdir", "type": "directory"},
        {"name": "test-bucket/dir/file2.txt", "type": "file"},
    ]
    path = "dir/"
    expected_files = ["gs://test-bucket/dir/file1.json", "gs://test-bucket/dir/file2.txt"]

    files = gcs_manager.list_files(path)
    assert files == expected_files
    mock_fs_ls.assert_called_once_with("gs://test-bucket/dir/", detail=True)


def test_gcs_manager_list_files_exception(gcs_manager, mocker):
    mock_fs_ls = mocker.patch.object(gcs_manager.fs, "ls", side_effect=Exception("Mock GCS list error"))
    path = "dir/"

    with pytest.raises(Exception, match="Mock GCS list error"):
        gcs_manager.list_files(path)
    mock_fs_ls.assert_called_once_with("gs://test-bucket/dir/", detail=True)


def test_gcs_manager_read_file_from_gcs_success(gcs_manager, mocker):
    mock_fs_open = mocker.patch.object(gcs_manager.fs, "open")
    mock_file_handle = MagicMock()
    mock_file_handle.__enter__.return_value.read.return_value = "file content"
    mock_fs_open.return_value = mock_file_handle

    gcs_path = "path/to/file.json"
    content = gcs_manager.read_file_from_gcs(gcs_path)
    assert content == "file content"
    mock_fs_open.assert_called_once_with("gs://test-bucket/path/to/file.json", 'r')


def test_gcs_manager_read_file_from_gcs_exception(gcs_manager, mocker):
    mock_fs_open = mocker.patch.object(gcs_manager.fs, "open", side_effect=Exception("Mock GCS read error"))
    gcs_path = "path/to/file.json"

    content = gcs_manager.read_file_from_gcs(gcs_path)
    assert content is None
    mock_fs_open.assert_called_once_with("gs://test-bucket/path/to/file.json", 'r')


def test_global_list_files_gcs_enabled_success(monkeypatch, mocker):
    monkeypatch.setattr(config, "BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(config, "GCS_ENABLED", True)
    gcs_client.reset_gcs_manager()

    mock_manager_list_files = mocker.patch.object(gcs_client.GCSManager, "list_files")
    mock_manager_list_files.return_value = ["gs://test-bucket/dir/file1.json"]

    files = gcs_client.list_files("dir/")
    assert files == ["gs://test-bucket/dir/file1.json"]
    mock_manager_list_files.assert_called_once_with("dir/")


def test_global_list_files_gcs_disabled_local_fallback(monkeypatch, mocker, tmp_path):
    monkeypatch.setattr(config, "BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(config, "GCS_ENABLED", False)
    gcs_client.reset_gcs_manager()

    # Create dummy local files
    local_dir = tmp_path / "data/test_race/snapshots"
    local_dir.mkdir(parents=True)
    (local_dir / "file1.json").write_text("content1")
    (local_dir / "file2.txt").write_text("content2")
    
    # Mock glob to return predictable local paths
    mocker.patch('glob.glob', return_value=[str(local_dir / "file1.json"), str(local_dir / "file2.txt")])
    mocker.patch('os.path.isfile', side_effect=lambda x: True) # Ensure mocked files are treated as files

    path = "data/test_race/snapshots/"
    files = gcs_client.list_files(path)
    assert len(files) == 2
    assert str(local_dir / "file1.json") in files
    assert str(local_dir / "file2.txt") in files


def test_global_read_file_from_gcs_gcs_enabled_success(monkeypatch, mocker):
    monkeypatch.setattr(config, "BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(config, "GCS_ENABLED", True)
    gcs_client.reset_gcs_manager()

    mock_manager_read_file = mocker.patch.object(gcs_client.GCSManager, "read_file_from_gcs")
    mock_manager_read_file.return_value = "GCS file content"

    content = gcs_client.read_file_from_gcs("path/to/gcs/file.json")
    assert content == "GCS file content"
    mock_manager_read_file.assert_called_once_with("path/to/gcs/file.json")


def test_global_read_file_from_gcs_gcs_disabled_local_fallback(monkeypatch, mocker, tmp_path):
    monkeypatch.setattr(config, "BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(config, "GCS_ENABLED", False)
    gcs_client.reset_gcs_manager()

    # Create a dummy local file
    local_file_name = "data/local_file.json"
    full_local_path = tmp_path / local_file_name
    full_local_path.parent.mkdir(parents=True, exist_ok=True)
    full_local_path.write_text("local file content")

    # Change current working directory to tmp_path for the test duration
    # This makes the local fallback in gcs_client resolve correctly.
    with monkeypatch.context() as m:
        m.chdir(tmp_path)
        gcs_path = local_file_name # This will be resolved relative to tmp_path/data/
        content = gcs_client.read_file_from_gcs(gcs_path)
        assert content == "local file content"

        gcs_path_with_gs = f"gs://test-bucket/{local_file_name}"
        content_with_gs = gcs_client.read_file_from_gcs(gcs_path_with_gs)
        assert content_with_gs == "local file content"


def test_global_read_file_from_gcs_gcs_disabled_local_file_not_found(monkeypatch, mocker, tmp_path):
    monkeypatch.setattr(config, "BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(config, "GCS_ENABLED", False)
    gcs_client.reset_gcs_manager()

    gcs_path = "data/non_existent.json"
    content = gcs_client.read_file_from_gcs(gcs_path)
    assert content is None
    # No direct log assertion, as warning is already checked in the original test suite
    # assert "Local file not found" in caplog.text