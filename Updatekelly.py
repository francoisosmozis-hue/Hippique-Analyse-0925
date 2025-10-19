import importlib
import inspect
import sys
import textwrap
from pathlib import Path

SOURCE = textwrap.dedent(
    '''\
from __future__ import annotations
import math

__all__ = ["kelly_fraction", "kelly_stake"]

def _to_float(x, default: float | None = None) -> float | None:
    try:
        v = float(x)
        if not math.isfinite(v):
            return default
        return v
    except Exception:
        return default

def kelly_fraction(p: float, odds: float, lam: float = 1.0, cap: float = 1.0) -> float:
    """
    Fraction de Kelly (pour cotes décimales) avec Kelly fractionné et plafond

    Args:
        p    : probabilité de gain (0 < p < 1)
        odds : cote décimale (> 1)
        lam  : fraction de Kelly appliquée (0 < lam <= 1)
        cap  : plafond sur la fraction finale (0 < cap <= 1)

    Retourne:
        f in [0, cap], 0 si edge ≤ 0 ou si entrées invalides.
    """
    p = _to_float(p)
    o = _to_float(odds)
    lam = _to_float(lam, 1.0) or 1.0
    cap = _to_float(cap, 1.0) or 1.0

    # Validation douce
    if p is None or o is None or not (0.0 < p < 1.0) or o <= 1.0:
        return 0.0
    if not (0.0 < lam <= 1.0):
        lam = 1.0
    if not (0.0 < cap <= 1.0):
        cap = 1.0

    # Kelly pur pour cotes décimales : f* = (p*o - 1)/(o - 1)
    numerator = p * o - 1.0
    denom = o - 1.0
    if denom <= 0.0:
        return 0.0

    f = numerator / denom
    if f <= 0.0:
        return 0.0

    # Kelly fractionné + plafond
    f = f * lam
    if f > cap:
        f = cap
    # clamp final de sécurité
    if f < 0.0:
        f = 0.0
    elif f > 1.0:
        f = 1.0
    return f

def kelly_stake(p: float, odds: float, bankroll: float, lam: float = 1.0, cap: float = 1.0) -> float:
    """
    Montant conseillé (en €) selon Kelly fractionné + plafond.
    """
    frac = kelly_fraction(p, odds, lam=lam, cap=cap)
    bk = _to_float(bankroll, 0.0) or 0.0
    if bk <= 0.0:
        return 0.0
    return frac * bk
'''
)


def write_file() -> None:
    target = Path(__file__).with_name("kelly.py")
    target.write_text(SOURCE, encoding="utf-8")


def purge_pycache() -> None:
    for pycache in Path(__file__).parent.rglob("__pycache__"):
        if not pycache.is_dir():
            continue
        for item in sorted(pycache.glob("**/*"), reverse=True):
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                item.rmdir()
        pycache.rmdir()


def verify_import() -> None:
    module_name = "kelly"
    if module_name in sys.modules:
        del sys.modules[module_name]
    module = importlib.import_module(module_name)
    sig = inspect.signature(module.kelly_fraction)
    expected_params = ("p", "odds", "lam", "cap")
    if tuple(sig.parameters) != expected_params:
        raise RuntimeError("Signature de kelly_fraction incorrecte")
    if sig.parameters["lam"].default != 1.0 or sig.parameters["cap"].default != 1.0:
        raise RuntimeError("Valeurs par défaut inattendues pour lam/cap")


if __name__ == "__main__":
    write_file()
    purge_pycache()
    verify_import()
