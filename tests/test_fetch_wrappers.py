from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

import fetch_je_chrono
import fetch_je_stats


@pytest.mark.parametrize("module", [fetch_je_stats, fetch_je_chrono])
def test_enrich_from_snapshot_builds_csvs(
    module: Any, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("WARNING")
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "runners": [
                    {
                        "num": "1",
                        "nom": "Alpha",
                        "j_rate": "12.5",
                        "e_rate": "9.1",
                        "chrono": "1'12\"5",
                    },
                    {
                        "number": 2,
                        "name": "Beta",
                        "j_win": 7.8,
                        "trainer_rate": 4.5,
                        "time": "1'13\"0",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    out_dir = tmp_path / "artefacts")

    result = module.enrich_from_snapshot(str(snapshot), str(out_dir))

    assert result == {
        "je_stats": str(out_dir / "je_stats.csv"),
        "chronos": str(out_dir / "chronos.csv"),
    }

    je_rows = list(csv.reader((out_dir / "je_stats.csv").open(encoding="utf-8")))
    assert je_rows == [
        ["num", "nom", "j_rate", "e_rate"],
        ["1", "Alpha", "12.5", "9.1"],
        ["2", "Beta", "7.8", "4.5"],
    ]

    chrono_rows = list(csv.reader((out_dir / "chronos.csv").open(encoding="utf-8")))
    assert chrono_rows == [
        ["num", "chrono"],
        ["1", "1'12\"5"],
        ["2", "1'13\"0"],
    ]

    assert not caplog.messages


@pytest.mark.parametrize("module", [fetch_je_stats, fetch_je_chrono])
def test_enrich_from_snapshot_handles_missing_fields(
    module: Any, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("WARNING")
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"runners": [{"id": "A"}]}), encoding="utf-8")

    result = module.enrich_from_snapshot(str(snapshot), str(tmp_path / "out"))

    assert result["je_stats"] is not None
    assert result["chronos"] is not None

    je_rows = list(csv.reader(Path(result["je_stats"]).open(encoding="utf-8")))
    assert je_rows == [["num", "nom", "j_rate", "e_rate"], ["A", "", "", ""]]

    chrono_rows = list(csv.reader(Path(result["chronos"]).open(encoding="utf-8")))
    assert chrono_rows == [["num", "chrono"], ["A", ""]]

    warnings = [message for message in caplog.messages if "missing" in message]
    assert warnings, "Expected warnings for missing fields"


@pytest.mark.parametrize("module", [fetch_je_stats, fetch_je_chrono])
def test_enrich_from_snapshot_missing_snapshot_returns_none(
    module: Any, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:    
    caplog.set_level("WARNING")
    missing = tmp_path / "absent.json"

    result = module.enrich_from_snapshot(str(missing), str(tmp_path / "out"))

    assert result == {"je_stats": None, "chronos": None}
    assert any("does not exist" in message for message in caplog.messages)


@pytest.mark.parametrize("module", [fetch_je_stats, fetch_je_chrono])
def test_enrich_from_snapshot_invalid_json(
    module: Any, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("WARNING")
    snapshot = tmp_path / "broken.json"
    snapshot.write_text("not-json", encoding="utf-8")
    
    result = module.enrich_from_snapshot(str(snapshot), str(tmp_path / "out"))

    assert result == {"je_stats": None, "chronos": None}
    assert any("Unable to load" in message for message in caplog.messages
               
def test_fetch_je_chrono_materialise_builds_csv(tmp_path: Path) -> None:
    course_dir = tmp_path / "R1C1"
    course_dir.mkdir()
    snapshot = course_dir / "R1C1_H-5.json"
    snapshot.write_text(
        json.dumps(
            {
                "partants": {
                    "runners": [
                        {"id": "1", "chrono": "1.12"},
                        {"id": "2", "time": "1.18"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    csv_path = fetch_je_chrono._materialise_chronos(course_dir, "R1", "C1")

    assert csv_path == course_dir / "R1C1_chronos.csv"
    assert (course_dir / "chronos.csv").exists()
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines == ["num,chrono", "1,1.12", "2,1.18"]


def test_fetch_je_chrono_materialise_requires_snapshot(tmp_path: Path) -> None:
    course_dir = tmp_path / "R1C1"
    course_dir.mkdir()

    with pytest.raises(RuntimeError, match="snapshot-missing"):
        fetch_je_chrono._materialise_chronos(course_dir, "R1", "C1")


