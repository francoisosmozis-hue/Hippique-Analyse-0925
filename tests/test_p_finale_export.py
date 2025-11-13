import json
from pathlib import Path

from src.hippique_orchestrator.scripts.p_finale_export import export


def test_export_creates_csv_and_excel(tmp_path: Path):
    # 1. Setup: Create a dummy p_finale.json in a temp directory
    output_dir = tmp_path / "race_outputs"
    output_dir.mkdir()
    p_finale_path = output_dir / "p_finale.json"

    p_finale_data = {
        "runners": [
            {"num": "1", "name": "Horse A", "p_finale": 0.5, "odds": 2.0, "j_rate": 0.1, "e_rate": 0.15},
            {"num": "2", "name": "Horse B", "p_finale": 0.3, "odds": 3.0, "j_rate": 0.05, "e_rate": 0.1},
        ]
    }
    p_finale_path.write_text(json.dumps(p_finale_data))

    # 2. Action: Call the export function
    success = export(str(output_dir))
    assert success, "Export function should return True on success"

    # 3. Assertions: Check if the output files were created
    csv_path = output_dir / "p_finale_export.csv"
    excel_path = output_dir / "p_finale_export.xlsx"

    assert csv_path.exists(), "p_finale_export.csv should be created"
    assert excel_path.exists(), "p_finale_export.xlsx should be created"

    # 4. Content check for CSV
    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "num,nom,p_finale,odds,j_rate,e_rate"
    assert "1,Horse A,0.5,2.0,0.1,0.15" in lines
    assert "2,Horse B,0.3,3.0,0.05,0.1" in lines
