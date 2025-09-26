import json
from pathlib import Path

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
    assert row["R/C"] == "R1C1"
    assert row["Heure"] == "12:05"
    assert row["Partants"] == 3
    assert row["Statut H-30"] == "OK (collecte)"
    assert row.get("Statut H-5") in (None, "")


def test_h5_updates_status_and_tickets(tmp_path: Path) -> None:
    meeting_dir = tmp_path / "meeting"
    meeting_dir.mkdir()
    meeting_payload = {
        "meta": {
            "date": "2024-09-25",
            "reunion": "R1",
            "course": "C1",
            "hippodrome": "Paris-Vincennes",
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
    (rc_dir / "analysis_H5.json").write_text(json.dumps(analysis), encoding="utf-8")

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
    assert row["Statut H-30"] == "OK (collecte)"
    assert row["Statut H-5"] == "Jouable (ROI 0.31)"
    assert row["Tickets H-5"] == "SP [6] 2€ @ 3.4"
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
    assert row["Statut H-5"] == "Non jouable (ROI global < 0.20)"
    assert row.get("Tickets H-5") in (None, "")
