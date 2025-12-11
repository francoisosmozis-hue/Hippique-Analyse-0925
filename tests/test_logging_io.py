from fsspec.implementations.memory import MemoryFileSystem

from hippique_orchestrator.logging_io import CSV_HEADER, append_csv_line


def test_csv_header_and_columns(tmp_path, mocker):
    # Mock GCS manager to use an in-memory filesystem
    mem_fs = MemoryFileSystem()
    mock_gcs_manager = mocker.MagicMock()
    mock_gcs_manager.fs = mem_fs
    mock_gcs_manager.get_gcs_path.side_effect = lambda path: str(path) # Use string path for in-memory fs
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
