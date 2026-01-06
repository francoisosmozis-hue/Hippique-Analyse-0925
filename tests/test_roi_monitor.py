import json
import csv
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hippique_orchestrator.scripts.backup_restore import (
    load_json_safe,
    parse_tracking_csv,
    collect_analyses,
    compute_statistics,
    print_report,
    export_json,
    main,
)


@pytest.fixture
def mock_data_dir(tmp_path):
    """Fixture to create a mock data directory structure for testing."""
    (tmp_path / "R1C1").mkdir()
    (tmp_path / "R1C1" / "analysis.json").write_text(
        json.dumps(
            {
                "meta": {"date": "2026-01-01"},
                "tickets": [{"type": "win", "stake": 10, "gain": 15}],
                "validation": {"roi_global_est": 0.1},
                "ev": {"ev_ratio": 0.05},
            }
        )
    )
    (tmp_path / "R1C1" / "tracking.csv").write_text("header1,header2\nvalue1,value2")
    (tmp_path / "R1C1" / "metrics.json").write_text(
        json.dumps({"clv_moyen": 0.02, "sharpe": 0.5, "risk_of_ruin": 0.01})
    )

    (tmp_path / "R2C2").mkdir()
    (tmp_path / "R2C2" / "analysis.json").write_text(
        json.dumps(
            {
                "meta": {"date": "2026-01-01"},
                "tickets": [{"type": "place", "stake": 5, "gain": 4}],
                "validation": {"roi_global_est": -0.1},
                "ev": {"ev_ratio": -0.02},
            }
        )
    )

    (tmp_path / "R3C3").mkdir()
    (tmp_path / "R3C3" / "analysis.json").write_text(
        json.dumps({"meta": {"date": "2026-01-02"}, "abstain": True})
    )

    (tmp_path / "R4C4").mkdir()
    (tmp_path / "R4C4" / "analysis_H5.json").write_text(
        json.dumps(
            {
                "meta": {"date": "2026-01-01"},
                "tickets": [{"type": "show", "stake": 20, "gain": 30}],
                "validation": {"roi_global_est": 0.2},
                "ev": {"ev_global": 0.1},
                "flags": {"ALERTE_VALUE": True},
            }
        )
    )

    return tmp_path


def test_load_json_safe_success(tmp_path):
    """Test loading a valid JSON file."""
    file_path = tmp_path / "test.json"
    file_path.write_text(json.dumps({"key": "value"}))
    assert load_json_safe(file_path) == {"key": "value"}


def test_load_json_safe_failure(tmp_path, capsys):
    """Test loading a non-existent or invalid JSON file."""
    file_path = tmp_path / "non_existent.json"
    assert load_json_safe(file_path) is None
    outerr = capsys.readouterr()
    assert "Warning: Failed to load" in outerr.err

    file_path.write_text("invalid json")
    assert load_json_safe(file_path) is None
    outerr = capsys.readouterr()
    assert "Warning: Failed to load" in outerr.err


def test_parse_tracking_csv_success(tmp_path):
    """Test parsing a valid CSV file."""
    file_path = tmp_path / "tracking.csv"
    file_path.write_text("col1,col2\nval1,val2\nval3,val4")
    expected = [{"col1": "val1", "col2": "val2"}, {"col1": "val3", "col2": "val4"}]
    assert parse_tracking_csv(file_path) == expected


def test_parse_tracking_csv_failure(tmp_path, capsys):
    """Test parsing a non-existent CSV file."""
    file_path = tmp_path / "non_existent.csv"
    assert parse_tracking_csv(file_path) == []
    outerr = capsys.readouterr()
    assert "Warning: Failed to parse" in outerr.err


def test_collect_analyses_no_date_filter(mock_data_dir):
    """Test collecting analyses without a date filter."""
    analyses = collect_analyses(mock_data_dir)
    assert len(analyses) == 4
    assert analyses[0]["rc"] == "R1C1"
    assert "analysis" in analyses[0]
    assert "tracking" in analyses[0]
    assert "metrics" in analyses[0]


def test_collect_analyses_with_date_filter(mock_data_dir):
    """Test collecting analyses with a specific date filter."""
    analyses = collect_analyses(mock_data_dir, date="2026-01-01")
    assert len(analyses) == 3  # R1C1, R2C2, R4C4
    for analysis_item in analyses:
        assert analysis_item["analysis"]["meta"]["date"] == "2026-01-01"


def test_compute_statistics(mock_data_dir):
    """Test computing statistics from collected analyses."""
    analyses = collect_analyses(mock_data_dir)
    stats = compute_statistics(analyses)

    assert stats["total_races"] == 4  # Total directories (including R3C3)
    assert stats["races_played"] == 3  # R1C1, R2C2, R4C4
    assert stats["races_abstain"] == 1  # R3C3
    assert stats["races_alerte"] == 1  # R4C4

    # R1C1 (stake 10, gain 15) + R2C2 (stake 5, gain 4) + R4C4 (stake 20, gain 30)
    assert stats["total_stake"] == 35.0
    assert stats["total_gain"] == 49.0
    assert stats["net_profit"] == 14.0
    assert stats["real_roi"] == pytest.approx(0.4)

    # (0.1 + (-0.1) + 0.2) / 3 = 0.06666...
    assert stats["expected_roi_avg"] == pytest.approx(0.0667)

    # (0.05 + (-0.02) + 0.1) / 3 = 0.04333...
    assert stats["ev_ratio_avg"] == pytest.approx(0.0433)

    # R1C1 (clv 0.02)
    assert stats["clv_avg"] == pytest.approx(0.02)

    # R1C1 (sharpe 0.5)
    assert stats["sharpe_avg"] == pytest.approx(0.5)

    # R1C1 (ror 0.01)
    assert stats["ror_avg"] == pytest.approx(0.01)

    assert stats["by_type"]["win"]["stake"] == 10.0
    assert stats["by_type"]["win"]["gain"] == 15.0
    assert stats["by_type"]["win"]["count"] == 1
    assert stats["by_type"]["win"]["wins"] == 1

    assert stats["by_type"]["place"]["stake"] == 5.0
    assert stats["by_type"]["place"]["gain"] == 4.0
    assert stats["by_type"]["place"]["count"] == 1
    assert stats["by_type"]["place"]["wins"] == 0

    assert stats["by_type"]["show"]["stake"] == 20.0
    assert stats["by_type"]["show"]["gain"] == 30.0
    assert stats["by_type"]["show"]["count"] == 1
    assert stats["by_type"]["show"]["wins"] == 1


def test_print_report(capsys):
    """Test printing the report output."""
    stats = {
        "total_races": 4,
        "races_played": 3,
        "races_abstain": 1,
        "races_alerte": 1,
        "total_stake": 35.0,
        "total_gain": 49.0,
        "net_profit": 14.0,
        "real_roi": 0.4,
        "expected_roi_avg": 0.0667,
        "ev_ratio_avg": 0.0433,
        "roi_variance": 0.3333,
        "clv_avg": 0.02,
        "sharpe_avg": 0.5,
        "ror_avg": 0.01,
        "by_type": {
            "win": {"stake": 10.0, "gain": 15.0, "count": 1, "wins": 1},
            "place": {"stake": 5.0, "gain": 4.0, "count": 1, "wins": 0},
        },
    }
    print_report(stats, detail=True)
    outerr = capsys.readouterr()
    assert "ROI MONITORING REPORT" in outerr.out
    assert "Total Races:        4" in outerr.out
    assert "Real ROI:           40.00%" in outerr.out
    assert "win".upper() in outerr.out
    assert "place".upper() in outerr.out


def test_export_json(tmp_path):
    """Test exporting statistics to a JSON file."""
    output_path = tmp_path / "stats.json"
    stats = {"key": "value"}
    export_json(stats, output_path)
    assert output_path.exists()
    assert json.loads(output_path.read_text()) == stats


@patch("argparse.ArgumentParser.parse_args")
@patch("builtins.print")
@patch("time.sleep")
@patch("sys.stderr", new_callable=MagicMock)
def test_main_run_once(mock_stderr, mock_sleep, mock_print, mock_parse_args, mock_data_dir):
    """Test main function in run-once mode."""
    mock_parse_args.return_value = MagicMock(
        data_dir=mock_data_dir, date=None, last_days=None, detail=False, json_out=None, watch=False
    )
    main()
    # The print statement for JSON export is not expected in this test case as json_out is None
    mock_print.assert_called()


@patch("argparse.ArgumentParser.parse_args")
@patch("builtins.print")
@patch("time.sleep")
@patch("sys.stderr", new_callable=MagicMock)
def test_main_watch_mode(mock_stderr, mock_sleep, mock_print, mock_parse_args, mock_data_dir):
    """Test main function in watch mode (runs twice then KeyboardInterrupt)."""
    mock_parse_args.return_value = MagicMock(
        data_dir=mock_data_dir, date=None, last_days=None, detail=False, json_out=None, watch=True
    )
    mock_sleep.side_effect = [None, KeyboardInterrupt]  # Simulate running twice then stopping
    main()
    assert mock_sleep.call_count == 2
    mock_print.assert_any_call("\n👋 Monitoring stopped")
