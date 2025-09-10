#!/usr/bin/env python3
# -*- coding: utf-8 -*-

def validate(h30:dict, h5:dict, allow_je_na:bool)->bool:
    ids30=[x["id"] for x in h30.get("runners",[])]
    ids05=[x["id"] for x in h5.get("runners",[])]
    if set(ids30)!=set(ids05):
        raise ValueError("Partants incohérents (H-30 vs H-5).")
    if not ids05:
        raise ValueError("Aucun partant.")

    for snap,label in [(h30,"H-30"),(h5,"H-5")]:
        for r in snap.get("runners",[]):
            if "odds" not in r or r["odds"] in (None,""):
                raise ValueError(f"Cotes manquantes {label} pour {r.get('name',r.get('id'))}.")
            try:
                if float(r["odds"])<=1.01:
                    raise ValueError(f"Cote invalide {label} pour {r.get('name',r.get('id'))}: {r['odds']}")
            except Exception:
                raise ValueError(f"Cote non numérique {label} pour {r.get('name',r.get('id'))}: {r.get('odds')}")
    if not allow_je_na:
        for r in h5.get("runners",[]):
            je=r.get("je_stats",{})
            if not je or ("j_win" not in je and "e_win" not in je):
                raise ValueError(f"Stats J/E manquantes: {r.get('name',r.get('id'))}")
    return True

   # Backward compatibility: validation basée sur EV ratio
def validate_ev(stats:dict, threshold:float=0.40)->bool:
    ev_ratio = float(stats.get("ev_ratio", 0.0))
    if ev_ratio < threshold:
        raise ValueError("EV ratio en dessous du seuil")
    return True
