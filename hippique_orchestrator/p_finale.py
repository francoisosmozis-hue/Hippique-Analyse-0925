#!/usr/bin/env python3
"""
This module provides functions to process race data and generate 'p_finale' probabilities.
The logic is designed to be pure and I/O-free.
"""

from __future__ import annotations

from typing import Any

DRIFT_DELTA = 0.04  # Probability variation threshold between H-30 and H-5
F_STEAM = 1.03  # Bonus factor if a horse's probability "steams" (increases)
F_DRIFT_FAV = 0.97  # Penalty factor if the H-30 favorite "drifts" (probability decreases)


def apply_drift_steam(p_val, num, p5_map, p30_map, fav30):
    """
    Applies a small market-based bonus/penalty to the p_val (place probability).
    """
    if not p_val:
        return 0.0

    # If either probability map is missing, do not apply drift/steam.
    if p5_map is None or p30_map is None:
        return p_val

    try:
        p5v = float(p5_map.get(str(num), 0.0))
        p30v = float(p30_map.get(str(num), 0.0))
    except (ValueError, TypeError):
        return p_val

    if p5v >= p30v + DRIFT_DELTA:
        return p_val * F_STEAM
    if (p30v >= p5v + DRIFT_DELTA) and (str(fav30) == str(num)):
        return p_val * F_DRIFT_FAV
    return p_val


def generate_p_finale_data(
    analysis_data: dict[str, Any],
    p30_odds_map: dict[str, float] | None = None,
    p5_odds_map: dict[str, float] | None = None,
    fav30_runner_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Extracts and transforms runner data from an analysis payload.

    This function contains the core logic, separated from file I/O.

    Parameters
    ----------
    analysis_data : dict
        The content of the analysis payload.
    p30_odds_map: dict, optional
        Mapping of runner ID to H-30 odds probabilities.
    p5_odds_map: dict, optional
        Mapping of runner ID to H-5 odds probabilities.
    fav30_runner_id: str, optional
        The ID of the favorite runner at H-30.

    Returns
    -------
    list[dict[str, Any]]
        A list of dictionaries, each representing a runner's p_finale data.
    """
    runners = []
    # Try different data structures from the input payload
    if 'runners' in analysis_data:
        runners = analysis_data['runners']
    elif 'horses' in analysis_data:
        runners = analysis_data['horses']
    elif 'partants' in analysis_data:
        runners = analysis_data['partants']

    if not runners:
        return []

    rows: list[dict[str, Any]] = []
    for runner in runners:
        if not isinstance(runner, dict):
            continue

        num = runner.get('num') or runner.get('number') or runner.get('id')
        p_finale_val = runner.get('p_finale') or runner.get('p') or runner.get('p_true')

        # Apply drift/steam factor if context is provided
        if p_finale_val and p30_odds_map and p5_odds_map:
            p_finale_val = apply_drift_steam(
                p_finale_val, num, p5_odds_map, p30_odds_map, fav30_runner_id
            )

        row = {
            'num': num,
            'nom': runner.get('nom') or runner.get('name'),
            'p_finale': p_finale_val,
            'odds': runner.get('odds') or runner.get('cote'),
            'j_rate': runner.get('j_rate') or runner.get('jockey_rate'),
            'e_rate': runner.get('e_rate') or runner.get('trainer_rate'),
        }
        rows.append(row)

    return rows
