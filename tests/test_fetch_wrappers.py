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

    out_dir = tmp_path / "artefacts"

    result = module.enrich_from_snapshot(str(snapshot), str(out_dir))

    if isinstance(result, dict):
        assert result.get("je_stats") is not None
        assert result.get("chronos") is not None
        assert Path(result["je_stats"]).exists()
        assert Path(result["chronos"]).exists()
    else:
        assert result is not None
        out_path = Path(result)
        assert out_path.exists()
        assert out_path.stat().st_size > 0


@pytest.mark.parametrize("module", [fetch_je_stats, fetch_je_chrono])
def test_enrich_from_snapshot_handles_missing_fields(
    module: Any, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("WARNING")
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"runners": [{"id": "A"}]}), encoding="utf-8")

    result = module.enrich_from_snapshot(str(snapshot), str(tmp_path / "out"))

    if isinstance(result, dict):
        assert result.get("je_stats") is not None
    else:
        assert result is not None

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
    assert any("Unable to load" in message for message in caplog.messages)
               
def test_fetch_je_chrono_enrich_from_snapshot_builds_chronos_csv(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "runners": [
                    {"id": "1", "chrono": "1.12"},
                    {"id": "2", "time": "1.18"},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = fetch_je_chrono.enrich_from_snapshot(
        str(snapshot), str(tmp_path / "artefacts")
    )

    chronos_path = tmp_path / "artefacts" / "chronos.csv"
    assert result["chronos"] == str(chronos_path)
    assert chronos_path.read_text(encoding="utf-8").splitlines() == [
        "num,chrono",
        "1,1.12",
        "2,1.18",
    ]


def test_fetch_je_chrono_enrich_from_snapshot_requires_snapshot(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("WARNING")
    missing = tmp_path / "R1C1_H-5.json"

    result = fetch_je_chrono.enrich_from_snapshot(
        str(missing), str(tmp_path / "artefacts")
    )

    assert result == {"je_stats": None, "chronos": None}
    assert not (tmp_path / "artefacts" / "chronos.csv").exists()
    assert any("does not exist" in message for message in caplog.messages)


