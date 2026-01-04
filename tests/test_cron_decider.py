# -*- coding: utf-8 -*-

import json
import datetime as dt
from pathlib import Path
from unittest.mock import patch, call
import sys
import os

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem

from hippique_orchestrator.scripts.cron_decider import (
    _load_meetings,
    _parse_start,
    _invoke_runner,
    main,
    PARIS,
)


@pytest.fixture
def fake_fs_cron_decider(fs: FakeFilesystem):
    """Fixture to set up a fake file system for cron_decider tests."""
    fs.create_dir("config")
    fs.create_dir("scripts")
    fs.create_file(
        "scripts/runner_chain.py", contents="print('runner_chain executed')"
    )
    yield fs


# --- Tests for _load_meetings ---
def test_load_meetings_from_dict_key_meetings(fake_fs_cron_decider: FakeFilesystem):
    """Test _load_meetings with 'meetings' key in dict."""
    meetings_data = {"meetings": [{"id": 1}, {"id": 2}]}
    fake_fs_cron_decider.create_file(
        "meetings.json", contents=json.dumps(meetings_data)
    )
    result = list(_load_meetings(Path("meetings.json")))
    assert result == [{"id": 1}, {"id": 2}]


def test_load_meetings_from_dict_key_reunions(fake_fs_cron_decider: FakeFilesystem):
    """Test _load_meetings with 'reunions' key in dict."""
    meetings_data = {"reunions": [{"id": 3}, {"id": 4}]}
    fake_fs_cron_decider.create_file(
        "meetings.json", contents=json.dumps(meetings_data)
    )
    result = list(_load_meetings(Path("meetings.json")))
    assert result == [{"id": 3}, {"id": 4}]


def test_load_meetings_from_dict_key_data(fake_fs_cron_decider: FakeFilesystem):
    """Test _load_meetings with 'data' key in dict."""
    meetings_data = {"data": [{"id": 5}, {"id": 6}]}
    fake_fs_cron_decider.create_file(
        "meetings.json", contents=json.dumps(meetings_data)
    )
    result = list(_load_meetings(Path("meetings.json")))
    assert result == [{"id": 5}, {"id": 6}]


def test_load_meetings_from_list(fake_fs_cron_decider: FakeFilesystem):
    """Test _load_meetings with direct list of meetings."""
    meetings_data = [{"id": 7}, {"id": 8}]
    fake_fs_cron_decider.create_file(
        "meetings.json", contents=json.dumps(meetings_data)
    )
    result = list(_load_meetings(Path("meetings.json")))
    assert result == [{"id": 7}, {"id": 8}]


def test_load_meetings_invalid_json_raises_error(fake_fs_cron_decider: FakeFilesystem):
    """Test _load_meetings raises JSONDecodeError for invalid JSON."""
    fake_fs_cron_decider.create_file("meetings.json", contents="invalid json")
    with pytest.raises(json.JSONDecodeError):
        list(_load_meetings(Path("meetings.json")))


# --- Tests for _parse_start ---
def test_parse_start_iso_timestamp():
    """Test _parse_start with an ISO timestamp."""
    dt_obj = _parse_start(None, "2026-01-03T10:30:00+01:00")
    assert dt_obj is not None
    assert dt_obj.year == 2026
    assert dt_obj.month == 1
    assert dt_obj.day == 3
    assert dt_obj.hour == 10
    assert dt_obj.minute == 30
    assert dt_obj.tzinfo == PARIS


def test_parse_start_hh_mm_with_date_hint():
    """Test _parse_start with HH:MM and a date hint."""
    dt_obj = _parse_start("2026-01-03", "10:30")
    assert dt_obj is not None
    assert dt_obj.year == 2026
    assert dt_obj.month == 1
    assert dt_obj.day == 3
    assert dt_obj.hour == 10
    assert dt_obj.minute == 30
    assert dt_obj.tzinfo == PARIS


def test_parse_start_invalid_format():
    """Test _parse_start with an invalid time format."""
    assert _parse_start(None, "invalid-time") is None
    assert _parse_start("2026-01-03", "invalid-time") is None


def test_parse_start_hh_mm_no_date_hint():
    """Test _parse_start with HH:MM but no date hint."""
    assert _parse_start(None, "10:30") is None


# --- Tests for _invoke_runner ---
@patch("hippique_orchestrator.scripts.cron_decider.os.environ", new_callable=lambda: os.environ.copy())
@patch("subprocess.run")
def test_invoke_runner(mock_subprocess_run, mock_os_environ):
    """Test _invoke_runner calls subprocess.run with correct arguments and environment."""
    reunion = "R1"
    course = "C1"
    phase = "H5"

    expected_env = mock_os_environ.copy()
    expected_env["ALLOW_HEURISTIC"] = "0"

    _invoke_runner(reunion, course, phase)
    mock_subprocess_run.assert_called_once_with(
        [
            sys.executable,
            "scripts/runner_chain.py",
            "--reunion",
            reunion,
            "--course",
            course,
            "--phase",
            phase,
        ],
        check=True,
        env=expected_env,
    )


# --- Tests for main ---
def test_main_meetings_file_not_found(fake_fs_cron_decider: FakeFilesystem, capsys):
    """Test main prints warning if meetings file is not found."""
    # meetings.json does not exist in the fake filesystem
    main([])
    captured = capsys.readouterr()
    assert "[WARN] meetings file not found: meetings.json" in captured.out


@patch("hippique_orchestrator.scripts.cron_decider.dt")
@patch("hippique_orchestrator.scripts.cron_decider._invoke_runner")
def test_main_happy_path_h5(
    mock_invoke_runner, mock_dt, fake_fs_cron_decider: FakeFilesystem
):
    """Test main triggers H5 phase correctly."""
    # Mock current time to trigger H5 window (e.g., 5 minutes before race)
    race_start_time = dt.datetime(2026, 1, 3, 10, 30, 0, tzinfo=PARIS)
    mock_dt.datetime.now.return_value = race_start_time - dt.timedelta(minutes=5)
    mock_dt.datetime.fromisoformat = dt.datetime.fromisoformat # Keep original for parsing

    meetings_data = {
        "meetings": [
            {
                "label": "R1",
                "date": "2026-01-03",
                "courses": [{"num": "C1", "start": "10:30"}],
            }
        ]
    }
    fake_fs_cron_decider.create_file(
        "meetings.json", contents=json.dumps(meetings_data)
    )

    main(["--meetings", "meetings.json"])
    mock_invoke_runner.assert_called_once_with("R1", "C1", "H5")


@patch("hippique_orchestrator.scripts.cron_decider.dt")
@patch("hippique_orchestrator.scripts.cron_decider._invoke_runner")
def test_main_happy_path_h30(
    mock_invoke_runner, mock_dt, fake_fs_cron_decider: FakeFilesystem
):
    """Test main triggers H30 phase correctly."""
    # Mock current time to trigger H30 window (e.g., 30 minutes before race)
    race_start_time = dt.datetime(2026, 1, 3, 11, 0, 0, tzinfo=PARIS)
    mock_dt.datetime.now.return_value = race_start_time - dt.timedelta(minutes=30)
    mock_dt.datetime.fromisoformat = dt.datetime.fromisoformat

    meetings_data = {
        "meetings": [
            {
                "label": "R2",
                "date": "2026-01-03",
                "courses": [{"num": "C2", "start": "11:00"}],
            }
        ]
    }
    fake_fs_cron_decider.create_file(
        "meetings.json", contents=json.dumps(meetings_data)
    )

    main([])
    mock_invoke_runner.assert_called_once_with("R2", "C2", "H30")


@patch("hippique_orchestrator.scripts.cron_decider.dt")
@patch("hippique_orchestrator.scripts.cron_decider._invoke_runner")
def test_main_no_trigger_outside_window(
    mock_invoke_runner, mock_dt, fake_fs_cron_decider: FakeFilesystem
):
    """Test main does not trigger if race is outside any window."""
    # Mock current time to be far from race start
    race_start_time = dt.datetime(2026, 1, 3, 10, 30, 0, tzinfo=PARIS)
    mock_dt.datetime.now.return_value = race_start_time - dt.timedelta(minutes=60)
    mock_dt.datetime.fromisoformat = dt.datetime.fromisoformat

    meetings_data = {
        "meetings": [
            {
                "label": "R3",
                "date": "2026-01-03",
                "courses": [{"num": "C3", "start": "10:30"}],
            }
        ]
    }
    fake_fs_cron_decider.create_file(
        "meetings.json", contents=json.dumps(meetings_data)
    )

    main([])
    mock_invoke_runner.assert_not_called()


@patch("hippique_orchestrator.scripts.cron_decider.dt")
@patch("hippique_orchestrator.scripts.cron_decider._invoke_runner")
def test_main_no_trigger_if_missing_info(
    mock_invoke_runner, mock_dt, fake_fs_cron_decider: FakeFilesystem
):
    """Test main does not trigger if meeting or course info is missing."""
    mock_dt.datetime.now.return_value = dt.datetime.now(PARIS)
    mock_dt.datetime.fromisoformat = dt.datetime.fromisoformat

    meetings_data = {
        "meetings": [
            {"label": "R4", "courses": [{"num": "C4"}]},  # Missing start
            {"date": "2026-01-03", "courses": [{"start": "12:00"}]},  # Missing label
            {"label": "R5", "date": "2026-01-03", "courses": [{"start": "12:00"}]},  # Missing num
        ]
    }
    fake_fs_cron_decider.create_file(
        "meetings.json", contents=json.dumps(meetings_data)
    )

    main([])
    mock_invoke_runner.assert_not_called()

@patch("hippique_orchestrator.scripts.cron_decider._invoke_runner")
def test_main_empty_meetings_file(mock_invoke_runner, fake_fs_cron_decider: FakeFilesystem):
    """Test main handles an empty meetings file gracefully."""
    fake_fs_cron_decider.create_file("meetings.json", contents="[]")
    main(["--meetings", "meetings.json"])
    mock_invoke_runner.assert_not_called()

@patch("hippique_orchestrator.scripts.cron_decider.dt")
@patch("hippique_orchestrator.scripts.cron_decider._invoke_runner")
def test_main_trigger_at_window_edge(
    mock_invoke_runner, mock_dt, fake_fs_cron_decider: FakeFilesystem
):
    """Test main triggers correctly at the exact window edges."""
    race_start_time = dt.datetime(2026, 1, 3, 12, 0, 0, tzinfo=PARIS)
    mock_dt.datetime.fromisoformat = dt.datetime.fromisoformat

    meetings_data = {
        "meetings": [
            {
                "label": "R1",
                "date": "2026-01-03",
                "courses": [{"num": "C1", "start": "12:00"}],
            }
        ]
    }
    fake_fs_cron_decider.create_file(
        "meetings.json", contents=json.dumps(meetings_data)
    )

    # Test H30 lower edge
    mock_dt.datetime.now.return_value = race_start_time - dt.timedelta(minutes=33)
    main([])
    mock_invoke_runner.assert_called_once_with("R1", "C1", "H30")
    mock_invoke_runner.reset_mock()

    # Test H5 upper edge
    mock_dt.datetime.now.return_value = race_start_time - dt.timedelta(minutes=3)
    main([])
    mock_invoke_runner.assert_called_once_with("R1", "C1", "H5")
