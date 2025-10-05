from logging_io import append_csv_line, CSV_HEADER


def test_csv_header_and_columns(tmp_path):
    path = tmp_path / "log.csv"
    append_csv_line(path, {"reunion": "R1", "course": "C1", "partants": 8})
    content = path.read_text(encoding="utf-8").strip().splitlines()
    header = content[0].split(";")
    assert header == CSV_HEADER
    assert len(header) == 16
    assert "total_optimized_stake" in header
    row = content[1].split(";")
    assert row[header.index("reunion")] == "R1"
    assert row[header.index("course")] == "C1"
    assert row[header.index("partants")] == "8"
