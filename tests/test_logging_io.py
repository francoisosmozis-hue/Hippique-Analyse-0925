from fsspec.implementations.memory import MemoryFileSystem

from hippique_orchestrator.logging_io import CSV_HEADER, append_csv_line


def test_csv_header_and_columns(tmp_path, mocker):
    # Mock GCS manager to use an in-memory filesystem
    mem_fs = MemoryFileSystem()
    mock_gcs_manager = mocker.MagicMock()
    mock_gcs_manager.fs = mem_fs
    mock_gcs_manager.get_gcs_path.side_effect = lambda path: str(
        path
    )  # Use string path for in-memory fs
    mocker.patch("hippique_orchestrator.logging_io.get_gcs_manager", return_value=mock_gcs_manager)

    path = tmp_path / "log.csv"
    append_csv_line(path, {"reunion": "R1", "course": "C1", "partants": 8})

    # Since we mocked GCS, we need to read from the in-memory filesystem
    gcs_path = str(path)
    assert mock_gcs_manager.fs.exists(gcs_path)
    with mock_gcs_manager.fs.open(gcs_path, "r") as f:
        content = f.read().strip().splitlines()

    header = content[0].split(";")
    assert header == CSV_HEADER
    assert len(header) == 16
    assert "total_optimized_stake" in header
    row = content[1].split(";")
    assert row[header.index("reunion")] == "R1"
    assert row[header.index("course")] == "C1"
    assert row[header.index("partants")] == "8"


import json
import pytest

# Test the local filesystem path for append_csv_line
def test_append_csv_line_local_filesystem(tmp_path, mocker):
    mocker.patch("hippique_orchestrator.logging_io.get_gcs_manager", return_value=None)

    path = tmp_path / "log_local.csv"
    data = {"reunion": "R2", "course": "C3"}
    
    append_csv_line(path, data)

    assert path.exists()
    content = path.read_text().strip().splitlines()
    assert content[0].split(";") == CSV_HEADER
    assert "R2" in content[1]
    assert "C3" in content[1]

# Test appending to an existing CSV on local disk
def test_append_csv_line_appends_locally(tmp_path, mocker):
    mocker.patch("hippique_orchestrator.logging_io.get_gcs_manager", return_value=None)
    path = tmp_path / "log_append.csv"

    append_csv_line(path, {"reunion": "R1"})
    append_csv_line(path, {"reunion": "R2"})

    content = path.read_text().strip().splitlines()
    assert len(content) == 3  # Header + 2 rows
    assert content[0].split(";") == CSV_HEADER
    assert "R1" in content[1]
    assert "R2" in content[2]

# Test the local filesystem path for append_json
def test_append_json_local_filesystem(tmp_path, mocker):
    mocker.patch("hippique_orchestrator.logging_io.get_gcs_manager", return_value=None)
    path = tmp_path / "data.json"
    data = {"key": "value", "items": [1, 2]}

    from hippique_orchestrator.logging_io import append_json
    append_json(path, data)

    assert path.exists()
    content = json.loads(path.read_text())
    assert content == data

# Test the GCS path for append_json
def test_append_json_gcs(mocker):
    mem_fs = MemoryFileSystem()
    mock_gcs_manager = mocker.MagicMock()
    mock_gcs_manager.fs = mem_fs
    mock_gcs_manager.get_gcs_path.side_effect = lambda p: str(p)
    mocker.patch("hippique_orchestrator.logging_io.get_gcs_manager", return_value=mock_gcs_manager)

    path = "/gcs/bucket/data.json"
    data = {"key": "gcs_value"}

    from hippique_orchestrator.logging_io import append_json
    append_json(path, data)

    assert mem_fs.exists(path)
    with mem_fs.open(path, "r") as f:
        content = json.load(f)
    assert content == data
