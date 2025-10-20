#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal pipeline for computing EV and exporting artefacts."""

import json
import logging
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)
LOG_LEVEL_ENV_VAR = "PIPELINE_LOG_LEVEL"
DEFAULT_OUTPUT_DIR = "out/hminus5"

PLACE_FEE = 0.15


def build_p_true(
    cfg: Dict[str, Any],
    partants: List[Dict[str, Any]],
    odds_h5: Dict[str, Any],
    odds_h30: Dict[str, Any],
    stats_je: Dict[str, Any],
) -> Dict:
    return {}


def compute_drift_dict(
    h30: Dict[str, float],
    h5: Dict[str, float],
    id2name: Dict[str, str],
    top_n: int = 5,
    min_delta: float = 0.8,
) -> Dict[str, List]:
    return {"missing_h30": [], "missing_h5": [], "drift": []}


def load_yaml(path: str) -> Dict:
    return {}


def _build_market(
    runners: List[Dict[str, Any]], slots_place_str: Optional[str] = None
) -> Dict[str, Any]:
    return {
        "slots_place": 3,
        "overround_place": 1.0,
        "runner_count_total": len(runners),
        "runner_count_with_win_odds": len(runners),
        "win_coverage_ratio": 1.0,
        "win_coverage_sufficient": True,
        "overround_win": 1.0,
        "overround": 1.0,
    }


def _ensure_place_odds(runners: List[Dict[str, Any]], market: Dict[str, Any]) -> None:
    pass


def enforce_ror_threshold(
    cfg: Dict,
    runners: List,
    combo_tickets: List,
    bankroll: float,
    *,
    global_roi: float,
    roi_min_threshold: float,
    **kwargs: Any,
) -> Tuple[List, Dict, Dict]:
    """
    Enforces the minimum global ROI threshold.
    If the provided global_roi is below the threshold, it returns empty tickets,
    indicating that no bets should be placed.
    """
    if global_roi >= roi_min_threshold:
        # ROI is fine, return original tickets
        return (
            combo_tickets,
            {},
            {
                "applied": False,
                "status": "success",
                "roi": global_roi,
                "threshold": roi_min_threshold,
            },
        )
    else:
        # ROI is too low, reject all tickets.
        return (
            [],
            {},
            {
                "applied": True,
                "status": "rejected_roi",
                "roi": global_roi,
                "threshold": roi_min_threshold,
            },
        )


def market_drift_signal(odds1: float, odds2: float, is_favorite: bool) -> int:
    return 0


def cmd_analyse(args: Any) -> None:
    outdir = args.outdir
    logger.info(f"[dummy cmd_analyse] outdir: {outdir}")
    if outdir:
        p_finale_path = Path(outdir) / "p_finale.json"
        data = {"meta": {"rc": "R1C1"}}
        logger.info(f"[dummy cmd_analyse] writing to {p_finale_path} with data: {data}")
        p_finale_path.write_text(json.dumps(data))


def _clv_median_ok(clv_values: list[float], threshold: float = 0.0) -> bool:
    """
    Return True if the median of CLV values is at or above the threshold.
    """
    if not clv_values:
        return True
    median_clv = statistics.median(clv_values)
    return median_clv >= threshold
