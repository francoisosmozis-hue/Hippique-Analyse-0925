#!/usr/bin/env python3
# -*- coding: utf-8 -*-

def must_have(value, msg):
    """Raise ``RuntimeError`` if ``value`` is falsy."""
    if not value:
        raise RuntimeError(msg)
    return value


def validate_inputs(cfg, partants, odds_h30, odds_h5, stats_je):
    """Validate raw inputs before any EV computation.

    Parameters
    ----------
    cfg : dict
        Configuration containing flags such as ``ALLOW_JE_NA``,
        ``REQUIRE_DRIFT_LOG`` and ``REQUIRE_ODDS_WINDOWS``.
    partants : list[dict]
        List of runners with at least an ``id`` key.
    odds_h30, odds_h5 : dict
        Mapping ``id`` -> cote for the corresponding snapshot.
    stats_je : dict
        Mapping ``id`` -> {"j_win", "e_win"} stats.
    """

    allow_je_na = cfg.get("ALLOW_JE_NA", False)
    require_drift = cfg.get("REQUIRE_DRIFT_LOG", False)
    required_windows = cfg.get("REQUIRE_ODDS_WINDOWS", []) or []

    partants = must_have(partants, "Partants manquants")
    ids = {str(p["id"]) for p in partants}
    must_have(ids, "Aucun partant")

    def check_snapshot(odds, label):
        must_have(odds, f"Cotes manquantes {label}")
        if set(map(str, odds.keys())) != ids:
            raise ValueError(f"Partants incohérents ({label})")
        for cid, cote in odds.items():
            if cote in (None, ""):
                raise ValueError(f"Cotes manquantes {label} pour {cid}.")
            try:
                if float(cote) <= 1.01:
                    raise ValueError(
                        f"Cote invalide {label} pour {cid}: {cote}"
                    )
            except Exception:
                raise ValueError(
                    f"Cote non numérique {label} pour {cid}: {cote}"
                )

    if required_windows:
        if 30 in required_windows:
            check_snapshot(odds_h30, "H-30")
        if 5 in required_windows:
            check_snapshot(odds_h5, "H-5")
    else:
        if odds_h30 is not None:
            check_snapshot(odds_h30, "H-30")
        if odds_h5 is not None:
            check_snapshot(odds_h5, "H-5")

    if require_drift:
        must_have(odds_h30, "Drift log manquant (H-30)")
        must_have(odds_h5, "Drift log manquant (H-5)")

    if not allow_je_na:
        must_have(stats_je, "Stats J/E manquantes")
        for cid in ids:
            je = stats_je.get(cid) if stats_je else None
            if not je or (je.get("j_win") is None and je.get("e_win") is None):
                raise ValueError(f"Stats J/E manquantes pour {cid}")

    return True


def validate(h30: dict, h5: dict, allow_je_na: bool) -> bool:
    ids30 = [x["id"] for x in h30.get("runners", [])]
    ids05 = [x["id"] for x in h5.get("runners", [])]
    if set(ids30) != set(ids05):
        raise ValueError("Partants incohérents (H-30 vs H-5).")
    if not ids05:
        raise ValueError("Aucun partant.")

    for snap, label in [(h30, "H-30"), (h5, "H-5")]:
        for r in snap.get("runners", []):
            if "odds" not in r or r["odds"] in (None, ""):
                raise ValueError(
                    f"Cotes manquantes {label} pour {r.get('name', r.get('id'))}."
                )
            try:
                if float(r["odds"]) <= 1.01:
                    raise ValueError(
                        f"Cote invalide {label} pour {r.get('name', r.get('id'))}: {r['odds']}"
                    )
            except Exception:
                raise ValueError(
                    f"Cote non numérique {label} pour {r.get('name', r.get('id'))}: {r.get('odds')}"
                )
    if not allow_je_na:
        for r in h5.get("runners", []):
            je = r.get("je_stats", {})
            if not je or ("j_win" not in je and "e_win" not in je):
                raise ValueError(
                    f"Stats J/E manquantes: {r.get('name', r.get('id'))}"
                )
    return True


   # Backward compatibility: validation basée sur EV ratio
def validate_ev(stats: dict, threshold: float = 0.40) -> bool:
    ev_ratio = float(stats.get("ev_ratio", 0.0))
    if ev_ratio < threshold:
        raise ValueError("EV ratio en dessous du seuil")
    return True
