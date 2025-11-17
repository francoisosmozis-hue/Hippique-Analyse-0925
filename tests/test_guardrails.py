from __future__ import annotations

import json
from pathlib import Path

import pytest
from src import guardrails
from src.guardrails import evaluate_guardrail


def _write_json(tmp_path: Path, name: str, payload: dict | list) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_evaluate_guardrail_uses_multiple_paths(tmp_path):
    payload = {
        "ev": {"global": 0.4},
        "validation": {"roi_global_est": 0.3},
    }
    path = _write_json(tmp_path, "analysis.json", payload)

    abstain, ev, roi = evaluate_guardrail(path, ev_min=0.35, roi_min=0.25)

    assert abstain is False
    assert ev == 0.4
    assert roi == 0.3


def test_evaluate_guardrail_detects_low_values(tmp_path):
    payload = {
        "metrics": {"ev_global": 0.2, "roi_global": 0.4},
    }
    path = _write_json(tmp_path, "analysis.json", payload)

    abstain, ev, roi = evaluate_guardrail(path, ev_min=0.35, roi_min=0.25)

    assert abstain is True
    assert ev == 0.2
    assert roi == 0.4


def test_load_json_raises_on_non_object(tmp_path: Path):
    """Tests that _load_json raises TypeError for non-object JSON."""
    path = _write_json(tmp_path, "list.json", [])
    with pytest.raises(TypeError, match="must be an object"):
        guardrails._load_json(path)


def test_extract_metric_returns_zero_when_missing():
    """Tests that _extract_metric returns 0.0 if no path matches."""
    metric = guardrails._extract_metric({}, [[("a",), ("b",)]])
    assert metric == 0.0


def test_append_env_writes_to_file(tmp_path: Path):
    """Tests that _append_env correctly writes and appends to a file."""
    env_file = tmp_path / "github.env"
    
    guardrails._append_env([("KEY1", "VALUE1")], env_file)
    content1 = env_file.read_text()
    assert content1 == "KEY1=VALUE1\n"

    guardrails._append_env([("KEY2", "VALUE2")], env_file)
    content2 = env_file.read_text()
    assert content2 == "KEY1=VALUE1\nKEY2=VALUE2\n"


def test_main_success_path(tmp_path: Path, mocker, capsys):
    """Tests the main function on a successful run (no abstention)."""
    analysis_file = _write_json(tmp_path, "analysis.json", {"ev": {"global": 0.5}, "roi_global": 0.5})
    env_file = tmp_path / "github.env"
    
    mocker.patch("sys.argv", [
        "guardrails.py",
        "--analysis", str(analysis_file),
        "--ev-min", "0.4",
        "--roi-min", "0.4",
        "--env", str(env_file),
    ])

    guardrails.main()

    env_content = env_file.read_text()
    assert "ABSTAIN=false" in env_content
    assert "ABSTAIN_EV=0.500000" in env_content
    assert "ABSTAIN_ROI=0.500000" in env_content

    captured = capsys.readouterr()
    assert "[guardrails] status=OK ev=0.5000 roi=0.5000" in captured.out


def test_main_abstention_path_creates_report(tmp_path: Path, mocker):
    """Tests that the main function creates a report on abstention."""
    analysis_file = _write_json(tmp_path, "analysis.json", {"ev_global": 0.1, "roi_global": 0.1})
    report_file = tmp_path / "report.json"
    
    mocker.patch("sys.argv", [
        "guardrails.py",
        "--analysis", str(analysis_file),
        "--ev-min", "0.2",
        "--roi-min", "0.2",
        "--report", str(report_file),
    ])

    guardrails.main()

    assert report_file.exists()
    report_data = json.loads(report_file.read_text())
    assert report_data["status"] == "abstention"
    assert report_data["reason"] == "guardrail_ev_roi"
    assert report_data["ev_global"] == 0.1
    assert report_data["roi_global"] == 0.1


def test_main_file_not_found(mocker):
    """Tests that main exits if the analysis file is not found."""
    mocker.patch("sys.argv", [
        "guardrails.py",
        "--analysis", "nonexistent.json",
        "--ev-min", "0.2",
        "--roi-min", "0.2",
    ])
    
    with pytest.raises(SystemExit):
        guardrails.main()
