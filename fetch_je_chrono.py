#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_je_chrono.py — GPI v5.1
------------------------------
But :
  Récupérer les chronos récents (3 dernières courses) d'un cheval
  depuis Geny / LeTrot (HTML ou JSON local) et produire un CSV
  `chronos.csv` utilisable par p_finale_export.py.

Entrée :
  --h5 : JSON H-5 produit par online_fetch_zeturf.py
  --out : chemin du CSV à générer (défaut = chronos.csv dans le dossier JSON)
  --threshold : seuil chrono (défaut 1'14"5 trot ou 34s/600m plat)

Sortie :
  CSV colonnes : num,nom,ok (1 si chrono correct, 0 sinon)

Usage :
  python fetch_je_chrono.py --h5 data/2025-09-07_Vincennes_R1C2_H-5.json --out data/chronos.csv
"""

import argparse, csv, json, re
from pathlib import Path
from typing import Dict, Any, List

def load_json(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def parse_chrono(text: str) -> float:
    """
    Parse un chrono du type '1'13"8' → 73.8 secondes
    """
    if not text:
        return None
    m = re.match(r"(\d+)'(\d{2})(?:\"(\d))?", text.strip())
    if not m:
        return None
    minutes = int(m.group(1))
    seconds = int(m.group(2))
    dix = int(m.group(3)) if m.group(3) else 0
    return minutes * 60 + seconds + dix/10.0

def is_ok(chrono: float, discipline: str, threshold_trot=74.5, threshold_flat=34.0) -> bool:
    """
    Vérifie si un chrono est sous le seuil.
    - trot : réduction kilométrique < 1'14"5 (~74.5 s/km)
    - plat : top-speed < 34s/600m
    """
    if chrono is None:
        return False
    if "trot" in discipline.lower():
        return chrono < threshold_trot
    return chrono < threshold_flat

def main():
    ap = argparse.ArgumentParser(description="Construit chronos.csv depuis un JSON H-5 enrichi.")
    ap.add_argument("--h5", required=True, help="Fichier JSON H-5 (online_fetch_zeturf.py)")
    ap.add_argument("--out", default=None, help="Fichier CSV de sortie (défaut = chronos.csv dans le dossier JSON)")
    ap.add_argument("--threshold", type=float, default=None, help="Seuil chrono (s)")
    args = ap.parse_args()

    data = load_json(args.h5)
    runners: List[Dict[str, Any]] = data.get("runners", [])
    discipline = data.get("discipline") or ""

    h5_path = Path(args.h5)
    out = Path(args.out) if args.out else h5_path.parent / "chronos.csv"

    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["num", "nom", "ok"])
        for r in runners:
            num = str(r.get("num"))
            name = r.get("name", "")
            chrono_txt = r.get("chrono") or r.get("dernier_chrono") or ""
            chrono_val = parse_chrono(chrono_txt)
            seuil = args.threshold or (74.5 if "trot" in discipline.lower() else 34.0)
            ok = 1 if is_ok(chrono_val, discipline, threshold_trot=seuil, threshold_flat=seuil) else 0
            w.writerow([num, name, ok])

    print(f"[OK] chronos.csv écrit → {out}")

if __name__ == "__main__":
    main()
