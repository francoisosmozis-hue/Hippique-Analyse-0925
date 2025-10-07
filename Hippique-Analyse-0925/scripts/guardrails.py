#!/usr/bin/env python3
"""Utility helpers used by CI workflows to enforce EV/ROI guardrails."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable, Mapping, Sequence

JsonMapping = Mapping[str, object]


def _extract_metric(payload: JsonMapping, paths: Sequence[Sequence[str]]) -> float:
    """Return the first numeric metric found following ``paths``."""

    for path in paths:
        value: object = payload
        for key in path:
            if isinstance(value, Mapping):
                value = value.get(key)  # type: ignore[assignment]
            else:
                value = None
                break
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _load_json(path: Path) -> JsonMapping:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, Mapping):
        return data
    raise TypeError(f"JSON payload must be an object: {path}")


def evaluate_guardrail(
    analysis_json: Path,
    *,
    ev_min: float,
    roi_min: float,
) -> tuple[bool, float, float]:
    """Return ``(abstain, ev, roi)`` based on ``analysis_json`` content."""

    payload = _load_json(analysis_json)
    ev_paths: Sequence[Sequence[str]] = (
        ("ev", "global"),
        ("ev", "ev_global"),
        ("validation", "ev_global_est"),
        ("validation", "ev_global"),
        ("stats", "ev_global"),
        ("metrics", "ev_global"),
        ("ev_global",),
    )
    roi_paths: Sequence[Sequence[str]] = (
        ("ev", "roi_global"),
        ("validation", "roi_global_est"),
        ("validation", "roi_global"),
        ("stats", "roi_global"),
        ("metrics", "roi_global"),
        ("roi_global",),
    )

    ev = _extract_metric(payload, ev_paths)
    roi = _extract_metric(payload, roi_paths)
    abstain = ev < ev_min or roi < roi_min
    return abstain, ev, roi


def _append_env(entries: Iterable[tuple[str, str]], env_file: Path | None) -> None:
    if env_file is None:
        return
    env_file.parent.mkdir(parents=True, exist_ok=True)
    with env_file.open("a", encoding="utf-8") as fh:
        for key, value in entries:
            fh.write(f"{key}={value}\n")


def main() -> None:  # pragma: no cover - exercised via workflows
    parser = argparse.ArgumentParser(description="Apply EV/ROI guardrails on analysis outputs")
    parser.add_argument("--analysis", required=True, help="Path to analysis_H5.json")
    parser.add_argument("--ev-min", type=float, required=True, help="Minimum EV ratio")
    parser.add_argument("--roi-min", type=float, required=True, help="Minimum ROI")
    parser.add_argument(
        "--report",
        help="Path where the abstention report should be written when guardrail triggers",
    )
    parser.add_argument(
        "--env",
        help="Path to the GitHub environment file (defaults to $GITHUB_ENV)",
    )
    args = parser.parse_args()

    analysis_path = Path(args.analysis)
    if not analysis_path.exists():
        raise SystemExit(f"analysis file not found: {analysis_path}")

    abstain, ev, roi = evaluate_guardrail(analysis_path, ev_min=args.ev_min, roi_min=args.roi_min)

    env_path = Path(args.env) if args.env else None
    if env_path is None and os.getenv("GITHUB_ENV"):
        env_path = Path(os.environ["GITHUB_ENV"])

    _append_env(
        (
            ("ABSTAIN", "true" if abstain else "false"),
            ("ABSTAIN_EV", f"{ev:.6f}"),
            ("ABSTAIN_ROI", f"{roi:.6f}"),
        ),
        env_path,
    )

    if abstain and args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": "abstention",
            "reason": "guardrail_ev_roi",
            "ev_global": ev,
            "roi_global": roi,
            "analysis": str(analysis_path),
        }
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    status = "ABSTENTION" if abstain else "OK"
    print(f"[guardrails] status={status} ev={ev:.4f} roi={roi:.4f}")


if __name__ == "__main__":  # pragma: no cover
    main()
