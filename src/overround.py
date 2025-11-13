#!/usr/bin/env python3
"""
overround.py — calculs overround (win/place) + cap adaptatif GPI v5.1
"""
from __future__ import annotations

from collections.abc import Iterable


def _clean_odds(x) -> float | None:
    if x is None:
        return None
    try:
        f = float(str(x).replace(",", "."))
        return f if f > 1.0 else None
    except Exception:
        return None

def compute_overround_win(win_odds: Iterable[float]) -> float:
    inv = 0.0
    for o in win_odds:
        v = _clean_odds(o)
        if v:
            inv += 1.0 / v
    return inv

def compute_overround_place(place_odds: Iterable[float]) -> float:
    inv = 0.0
    for o in place_odds:
        v = _clean_odds(o)
        if v:
            inv += 1.0 / v
    return inv

def adaptive_cap(discipline: str, n_partants: int) -> float:
    d = (discipline or "").lower()
    if d.startswith("plat") and n_partants >= 14:
        return 1.25
    return 1.30
