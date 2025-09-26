import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from scripts import update_excel_planning as planner


def _read_row(ws, row_idx: int) -> dict[str, object]:
    header_map = {cell.value: idx for idx, cell in enumerate(ws[1], start=1) if cell.value}
    return {header: ws.cell(row=row_idx, column=col).value for header, col in header_map.items()}


def test_h30_populates_planning_sheet(tmp_path: Path) -> None:
    meeting_dir = tmp_path / "meeting"
    meeting_dir.mkdir()
    payload = {
        "meta": {
            "date": "2024-09-25",
            "reunion": "R1",
            "course": "C1",
            "hippodrome": "Paris-Vincennes",
            "start_time": "2024-09-25T12:05:00",
            "discipline": "Trot",
        },
        "runners": [{"id": 1}, {"id": 2}, {"id": 3}],
    }
    (meeting_dir / "snapshot_H-30.json").write_text(json.dumps(payload), encoding="utf-8")

    excel_path = tmp_path / "planning.xlsx"
    planner.main(
        [
            "--phase",
            "H30",
            "--input",
            str(meeting_dir),
            "--excel",
            str(excel_path),
        ]
    )

    wb = load_workbook(excel_path)
    ws = wb["Planning"]
    row = _read_row(ws, 2)
    assert row["Date"] == "2024-09-25"
    assert row["Heure"] == "12:05"
    assert row["Partants"] == 3
    assert row["Discipline"] == "Trot"
    assert row["Statut H-30"] == "Collecté"
    assert row.get("Statut H-5") in (None, "")
    assert row.get("Jouable H-5") in (None, "")


def test_h5_updates_status_and_tickets(tmp_path: Path) -> None:
    meeting_dir = tmp_path / "meeting"
    meeting_dir.mkdir()
    meeting_payload = {
        "meta": {
            "date": "2024-09-25",
            "reunion": "R1",
            "course": "C1",
            "hippodrome": "Paris-Vincennes",
            "discipline": "Trot",
        },
        "runners": [{"id": 1}, {"id": 2}],
    }
    (meeting_dir / "snapshot.json").write_text(json.dumps(meeting_payload), encoding="utf-8")
    excel_path = tmp_path / "planning.xlsx"
    planner.main(
        [
            "--phase",
            "H30",
            "--input",
            str(meeting_dir),
            "--excel",
            str(excel_path),
        ]
    )

    rc_dir = tmp_path / "R1C1"
    rc_dir.mkdir()
    analysis = {
        "meta": {
            "date": "2024-09-25",
            "reunion": "R1",
            "course": "C1",
            "hippodrome": "Paris-Vincennes",
            "start_time": "12:10",
            "discipline": "Trot",
        },
        "validation": {"roi_global_est": 0.31},
        "abstain": False,
        "tickets": [
            {
                "id": "SP1",
                "type": "SP",
                "legs": [{"horse": "6"}],
                "stake": 2.0,
                "odds": 3.4,
            }
        ],
    }
    (rc_dir / "analysis_H5_R1C1.json").write_text(json.dumps(analysis), encoding="utf-8")

    planner.main(
        [
            "--phase",
            "H5",
            "--input",
            str(rc_dir),
            "--excel",
            str(excel_path),
            "--rc",
            "R1C1",
        ]
    )

    wb = load_workbook(excel_path)
    ws = wb["Planning"]
    row = _read_row(ws, 2)
    assert row["Statut H-30"] == "Collecté"
    assert row["Statut H-5"] == "Analysé"
    assert row["Jouable H-5"] == "Oui"
    assert row["Commentaires"] == "ROI estimé 31%"
    assert row["Tickets H-5"] == "SP:6@3.4"
    assert row["Heure"] == "12:10"


def test_h5_abstention_uses_reason(tmp_path: Path) -> None:
    excel_path = tmp_path / "planning.xlsx"
    meeting_dir = tmp_path / "meeting"
    meeting_dir.mkdir()
    base_payload = {
        "meta": {
            "date": "2024-09-25",
            "reunion": "R1",
            "course": "C1",
        },
        "runners": [{"id": 1}],
    }
    (meeting_dir / "snapshot.json").write_text(json.dumps(base_payload), encoding="utf-8")
    planner.main([
        "--phase",
        "H30",
        "--input",
        str(meeting_dir),
        "--excel",
        str(excel_path),
    ])

    rc_dir = tmp_path / "R1C1"
    rc_dir.mkdir()
    abstain_payload = {
        "meta": {
            "date": "2024-09-25",
            "reunion": "R1",
            "course": "C1",
        },
        "abstain": True,
        "notes": "ROI global < 0.20",
    }
    (rc_dir / "analysis.json").write_text(json.dumps(abstain_payload), encoding="utf-8")

    planner.main([
        "--phase",
        "H5",
        "--input",
        str(rc_dir / "analysis.json"),
        "--excel",
        str(excel_path),
        "--rc",
        "R1C1",
    ])

    wb = load_workbook(excel_path)
    ws = wb["Planning"]
    row = _read_row(ws, 2)
    assert row["Statut H-5"] == "Analysé"
    assert row["Jouable H-5"] == "Non"
    assert row["Commentaires"] == "ROI global < 0.20"
    assert row.get("Tickets H-5") in (None, "")


def test_h5_preserves_existing_metadata_when_missing(tmp_path: Path) -> None:
    meeting_dir = tmp_path / "meeting"
    meeting_dir.mkdir()
    base_payload = {
        "meta": {
            "date": "2024-09-26",
            "reunion": "R2",
            "course": "C3",
            "hippodrome": "Lyon-Parilly",
            "start_time": "2024-09-26T14:15:00",
        },
        "runners": [{"id": 1}, {"id": 2}],
    }
    (meeting_dir / "snapshot.json").write_text(json.dumps(base_payload), encoding="utf-8")

    excel_path = tmp_path / "planning.xlsx"
    planner.main(
        [
            "--phase",
            "H30",
            "--input",
            str(meeting_dir),
            "--excel",
            str(excel_path),
        ]
    )

    analysis_dir = tmp_path / "R2C3"
    analysis_dir.mkdir()
    minimal_h5 = {
        "meta": {
            "date": "2024-09-26",
            "reunion": "R2",
            "course": "C3",
        },
        "abstain": True,
        "abstain_reason": "Champ trop ouvert",
    }
    (analysis_dir / "analysis_H5.json").write_text(json.dumps(minimal_h5), encoding="utf-8")

    planner.main(
        [
            "--phase",
            "H5",
            "--input",
            str(analysis_dir),
            "--excel",
            str(excel_path),
        ]
    )

    wb = load_workbook(excel_path)
    ws = wb["Planning"]
    row = _read_row(ws, 2)
    assert row["Hippodrome"] == "Lyon-Parilly"
    assert row["Heure"] == "14:15"
    assert row["Statut H-5"] == "Analysé"
    assert row["Jouable H-5"] == "Non"


def test_h5_converts_timezone_when_tz_env_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meeting_dir = tmp_path / "meeting"
    meeting_dir.mkdir()
    base_payload = {
        "meta": {
            "date": "2024-10-01",
            "reunion": "R3",
            "course": "C4",
            "hippodrome": "Chantilly",
        },
        "runners": [{"id": 1}, {"id": 2}],
    }
    (meeting_dir / "snapshot.json").write_text(json.dumps(base_payload), encoding="utf-8")

    excel_path = tmp_path / "planning.xlsx"
    planner.main(
        [
            "--phase",
            "H30",
            "--input",
            str(meeting_dir),
            "--excel",
            str(excel_path),
        ]
    )

    monkeypatch.setenv("TZ", "Europe/Paris")
    planner._env_timezone.cache_clear()

    rc_dir = tmp_path / "R3C4"
    rc_dir.mkdir()
    analysis_payload = {
        "meta": {
            "date": "2024-10-01",
            "reunion": "R3",
            "course": "C4",
            "start_time": "2024-10-01T12:05:00+00:00",
        },
        "abstain": False,
    }
    (rc_dir / "analysis_H5.json").write_text(json.dumps(analysis_payload), encoding="utf-8")

    planner.main(
        [
            "--phase",
            "H5",
            "--input",
            str(rc_dir),
            "--excel",
            str(excel_path),
        ]
    )

    wb = load_workbook(excel_path)
    ws = wb["Planning"]
    row = _read_row(ws, 2)
    assert row["Heure"] == "14:05"

    planner._env_timezone.cache_clear()


def test_custom_status_h5_flag(tmp_path: Path) -> None:
    meeting_dir = tmp_path / "meeting"
    meeting_dir.mkdir()
    payload = {
        "meta": {
            "date": "2024-09-25",
            "reunion": "R1",
            "course": "C1",
        },
        "runners": [{"id": 1}],
    }
    (meeting_dir / "snapshot.json").write_text(json.dumps(payload), encoding="utf-8")

    excel_path = tmp_path / "planning.xlsx"
    planner.main(
        [
            "--phase",
            "H30",
            "--input",
            str(meeting_dir),
            "--excel",
            str(excel_path),
        ]
    )

    analysis_dir = tmp_path / "R1C1"
    analysis_dir.mkdir()
    analysis_payload = {
        "meta": {
            "date": "2024-09-25",
            "reunion": "R1",
            "course": "C1",
        },
        "tickets": [],
    }
    (analysis_dir / "analysis.json").write_text(json.dumps(analysis_payload), encoding="utf-8")

    planner.main(
        [
            "--phase",
            "H5",
            "--input",
            str(analysis_dir),
            "--excel",
            str(excel_path),
            "--status-h5",
            "Validé",
        ]
    )

    wb = load_workbook(excel_path)
    ws = wb["Planning"]
    row = _read_row(ws, 2)
    assert row["Statut H-5"] == "Validé"


def test_h30_handles_nested_course_payload(tmp_path: Path) -> None:
    meeting_dir = tmp_path / "snapshots"
    meeting_dir.mkdir()
    payload = {
        "courses": [
            {
                "meta": {
                    "date": "2024-09-25",
                    "reunion": "R4",
                    "course": "C5",
                    "hippodrome": "Vincennes",
                    "start_time": "13h05",
                    "partants": 14,
                },
                "discipline": "Plat",
            }
        ]
    }
    (meeting_dir / "meeting.json").write_text(json.dumps(payload), encoding="utf-8")
    excel_path = tmp_path / "planning.xlsx"

    planner.main(
        [
            "--phase",
            "H30",
            "--input",
            str(meeting_dir),
            "--excel",
            str(excel_path),
        ]
    )

    wb = load_workbook(excel_path)
    ws = wb["Planning"]
    row = _read_row(ws, 2)

    assert row["Réunion"] == "R4"
    assert row["Course"] == "C5"
    assert row["Hippodrome"] == "Vincennes"
    assert row["Heure"] == "13:05"
    assert row["Partants"] == 14
    assert row["Discipline"] == "Plat"


def test_h5_compact_ticket_summary(tmp_path: Path) -> None:
    meeting_dir = tmp_path / "snapshots"
    meeting_dir.mkdir()
    payload = {
        "courses": [
            {
                "meta": {
                    "date": "2024-09-25",
                    "reunion": "R4",
                    "course": "C5",
                    "hippodrome": "Vincennes",
                },
            }
        ]
    }
    (meeting_dir / "meeting.json").write_text(json.dumps(payload), encoding="utf-8")
    excel_path = tmp_path / "planning.xlsx"
    planner.main(
        [
            "--phase",
            "H30",
            "--input",
            str(meeting_dir),
            "--excel",
            str(excel_path),
        ]
    )

    analysis_dir = tmp_path / "R4C5"
    analysis_dir.mkdir()
    analysis_payload = {
        "meta": {
            "date": "2024-09-25",
            "reunion": "R4",
            "course": "C5",
            "hippodrome": "Vincennes",
            "start_time": "13h05",
            "discipline": "Plat",
            "partants": 14,
        },
        "abstain": False,
        "roi": 0.12,
        "tickets": [
            {
                "type": "SP",
                "legs": [{"selections": [3, 5]}],
                "odds": 2.0,
            },
            {
                "type": "CPL",
                "legs": [{"horses": [1, 3]}],
                "rapport": 1.5,
            },
        ],
    }
    (analysis_dir / "analysis_H5.json").write_text(json.dumps(analysis_payload), encoding="utf-8")

    planner.main(
        [
            "--phase",
            "H5",
            "--input",
            str(analysis_dir),
            "--excel",
            str(excel_path),
        ]
    )

    wb = load_workbook(excel_path)
    ws = wb["Planning"]
    row = _read_row(ws, 2)

    assert row["Statut H-5"] == "Analysé"
    assert row["Jouable H-5"] == "Oui"
    assert row["Tickets H-5"] == "SP:3-5@2 | CPL:1-3@1.5"
    assert row["Commentaires"] == "ROI estimé 12%"

def test_format_time_respects_input_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TZ", raising=False)
    planner._env_timezone.cache_clear()
    assert planner._format_time("2024-09-25T13:05:00+02:00") == "13:05"


def test_format_time_uses_env_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "Europe/Paris")
    planner._env_timezone.cache_clear()
    assert planner._format_time("2024-09-25T13:05:00+00:00") == "15:05"
    monkeypatch.delenv("TZ", raising=False)
    planner._env_timezone.cache_clear()


@pytest.mark.parametrize(
    "value, expected",
    [
        ("13h05", "13:05"),
        ("7h", "07:00"),
        ("09 heures 30", "09:30"),
        ("18.45", "18:45"),
    ],
)
def test_format_time_handles_textual_hours(value: str, expected: str) -> None:
    """French textual hour formats should be normalised to HH:MM."""

    assert planner._format_time(value) == expected
