# -*- coding: utf-8 -*-
"""
module_dutching_pmu.py — GPI v5.1
---------------------------------
Allocation des mises en **Simple Placé** (ou assimilé) par **Kelly fractionné**,
avec **cap 60 %** par cheval et **budget total configurable** (par défaut 5 €).
Compatibilité pandas.
...
"""
from typing import List, Optional, Sequence
import math
import pandas as pd

def _safe_prob(p: float) -> float:
    return max(0.01, min(0.90, float(p)))

def _kelly_fraction(p: float, o: float) -> float:
    b = max(0.0, float(o) - 1.0)
    if b <= 0.0:
        return 0.0
    f = (b * p - (1.0 - p)) / b
    return max(0.0, min(1.0, f))

def dutching_kelly_fractional(
    odds: Sequence[float],
    total_stake: float = 5.0,
    probs: Optional[Sequence[float]] = None,
    lambda_kelly: float = 0.5,
    cap_per_horse: float = 0.60,
    round_to: float = 0.10,
    horse_labels: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    ...
    return df

def ev_panier(df: pd.DataFrame) -> float:
    """EV totale (en €) du panier SP."""
    if df.empty:
        return 0.0
    return float(df["EV (€)"].sum())
