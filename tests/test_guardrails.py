from __future__ import annotations

import json
from pathlib import Path

from src.guardrails import evaluate_guardrail


def _write_json(tmp_path: Path, name: str, payload: dict) -> Path:
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
