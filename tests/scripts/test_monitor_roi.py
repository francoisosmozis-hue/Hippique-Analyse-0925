import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from hippique_orchestrator.scripts.monitor_roi import (
    collect_analyses,
    compute_statistics,
    export_json,
    load_json_safe,
    main,  # Moved import to top-level
    parse_tracking_csv,
    print_report,
)


@pytest.fixture
def fake_data_dir(tmp_path: Path) -> Path:
    """Creates a fake data directory structure for testing."""
    # Race 1: Played and Won
    r1c1_dir = tmp_path / "R1C1"
    r1c1_dir.mkdir()
    analysis1 = {
        "meta": {"date": "2025-12-25"},
        "tickets": [{"type": "SG", "stake": 10, "gain_reel": 50}],
        "validation": {"roi_global_est": 0.3},
        "ev": {"ev_ratio": 0.4},
        "flags": {},
    }
    (r1c1_dir / "analysis.json").write_text(json.dumps(analysis1))
    (r1c1_dir / "metrics.json").write_text(json.dumps({"clv_moyen": 0.05}))

    # Race 2: Abstained
    r1c2_dir = tmp_path / "R1C2"
    r1c2_dir.mkdir()
    analysis2 = {
        "meta": {"date": "2025-12-25"},
        "abstain": True,
    }
    (r1c2_dir / "analysis.json").write_text(json.dumps(analysis2))

    # Race 3: Played and Lost (different date)
    r1c3_dir = tmp_path / "R1C3"
    r1c3_dir.mkdir()
    analysis3 = {
        "meta": {"date": "2025-12-26"},
        "tickets": [{"type": "SP", "stake": 20, "gain_reel": 0}],
        "validation": {"roi_global_est": 0.2},
        "ev": {"ev_global": 0.25},
        "flags": {"ALERTE_VALUE": True},
    }
    (r1c3_dir / "analysis_H5.json").write_text(json.dumps(analysis3))

    # Race 4: Invalid analysis file
    r1c4_dir = tmp_path / "R1C4"
    r1c4_dir.mkdir()
    (r1c4_dir / "analysis.json").write_text("this is not json")

    return tmp_path


def test_load_json_safe_success(tmp_path: Path):
    """Test loading a valid JSON file."""
    path = tmp_path / "test.json"
    path.write_text('{"key": "value"}')
    assert load_json_safe(path) == {"key": "value"}


def test_load_json_safe_failure(tmp_path: Path, capsys):
    """Test loading a malformed or nonexistent JSON file."""
    path = tmp_path / "invalid.json"
    path.write_text("invalid json")
    assert load_json_safe(path) is None
    assert "Warning: Failed to load" in capsys.readouterr().err

    assert load_json_safe(tmp_path / "nonexistent.json") is None


def test_parse_tracking_csv_success(tmp_path: Path):
    """Test parsing a valid CSV file."""
    path = tmp_path / "tracking.csv"
    path.write_text("col1,col2\nval1,val2")
    rows = parse_tracking_csv(path)
    assert len(rows) == 1
    assert rows[0] == {"col1": "val1", "col2": "val2"}


def test_collect_analyses_no_date_filter(fake_data_dir: Path):
    """Test collecting all valid analyses without a date filter."""
    analyses = collect_analyses(fake_data_dir)
    # R1C1, R1C2, R1C3 should be found. R1C4 is invalid.
    assert len(analyses) == 3
    rcs = {item["rc"] for item in analyses}
    assert rcs == {"R1C1", "R1C2", "R1C3"}


def test_collect_analyses_with_date_filter(fake_data_dir: Path):
    """Test filtering analyses by a specific date."""
    analyses = collect_analyses(fake_data_dir, date="2025-12-25")
    assert len(analyses) == 2
    rcs = {item["rc"] for item in analyses}
    assert rcs == {"R1C1", "R1C2"}


def test_compute_statistics(fake_data_dir: Path):
    """Test the main statistics computation logic."""
    analyses = collect_analyses(fake_data_dir)
    stats = compute_statistics(analyses)

    assert stats["total_races"] == 3
    assert stats["races_played"] == 2
    assert stats["races_abstain"] == 1
    assert stats["races_alerte"] == 1
    assert stats["total_stake"] == 30.00
    assert stats["total_gain"] == 50.00
    assert stats["net_profit"] == 20.00
    assert stats["real_roi"] == round(20 / 30, 4)
    assert stats["expected_roi_avg"] == round((0.3 + 0.2) / 2, 4)
    assert stats["ev_ratio_avg"] == round((0.4 + 0.25) / 2, 4)
    assert stats["clv_avg"] == 0.05

    # Check by_type aggregation
    by_type = stats["by_type"]
    assert by_type["SG"]["stake"] == 10
    assert by_type["SG"]["gain"] == 50
    assert by_type["SG"]["wins"] == 1
    assert by_type["SG"]["count"] == 1
    assert by_type["SP"]["stake"] == 20
    assert by_type["SP"]["gain"] == 0


def test_compute_statistics_no_races_played():
    """Test stats computation when no races are played."""
    analyses = [{"analysis": {"abstain": True}, "metrics": {}}]
    stats = compute_statistics(analyses)
    assert stats["races_played"] == 0
    assert stats["total_stake"] == 0
    assert stats["real_roi"] == 0
    assert stats["expected_roi_avg"] == 0


def test_print_report(capsys):
    """Test that the report printing function runs without errors."""
    stats = {
        "total_races": 1,
        "races_played": 1,
        "races_abstain": 0,
        "races_alerte": 0,
        "total_stake": 10,
        "total_gain": 15,
        "net_profit": 5,
        "real_roi": 0.5,
        "expected_roi_avg": 0.4,
        "roi_variance": 0.1,
        "ev_ratio_avg": 0.45,
        "clv_avg": 0.1,
        "sharpe_avg": 2.5,
        "ror_avg": 0.01,
        "by_type": {},
    }
    print_report(stats, detail=True)
    captured = capsys.readouterr()
    assert "ROI MONITORING REPORT" in captured.out
    assert "Net Profit:         5.00 €" in captured.out
    assert "Real ROI:           50.00%" in captured.out


def test_export_json(tmp_path: Path):
    """Test that the JSON export function writes a file."""
    output_path = tmp_path / "stats.json"
    stats = {"key": "value"}
    export_json(stats, output_path)
    assert output_path.exists()
    assert output_path.read_text() == json.dumps(stats, indent=2)


def test_main_run_once(fake_data_dir: Path, capsys):
    """Test the main function for a single run."""
    with patch.object(
        sys, "argv", ["monitor_roi.py", "--data-dir", str(fake_data_dir), "--detail"]
    ):
        main()

    captured = capsys.readouterr()
    assert "Found 3 races" in captured.out
    assert "Net Profit:         20.00 €" in captured.out
    assert "BY BET TYPE" in captured.out
