#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_excel_with_results.py — Consolidated (Post-R10C5)
-------------------------------------------------------
But
    Mettre à jour le fichier Excel de suivi (modele_suivi_courses_hippiques.xlsx)
    avec les informations d'une course + résultats réels, calculer le ROI et
    consigner le verdict "jeu réel" ainsi que les tickets joués.

Entrées
    - JSON de résultats produit par get_arrivee_geny.py
    - Paramètres de tickets/mises/gains

Colonnes standard (onglet 'Suivi')
    Date | Réunion | Course | Hippodrome | Discipline | Partants
    Tickets | Mises_totales | Gains_reels | ROI_estime | ROI_reel
    Verdict | Arrivee_officielle | Notes | Timestamp_UTC

Usage
    python update_excel_with_results.py \
        --excel modele_suivi_courses_hippiques.xlsx \
        --result r10c5.json \
        --tickets "SP Dutching 6€ ; Trio 3.6€ ; ZE4 2.4€" \
        --mises 12.0 \
        --gains 18.6 \
        --roi_estime 0.55 \
        --verdict "Valide jeu réel" \
        --notes "Migration depuis discussion lourde R10C5"

Notes
    - Crée le fichier et la feuille si absents (openpyxl + pandas).
    - Pas de dépendance réseau. Aucune trace "pmu".
"""
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

import pandas as pd

DEFAULT_SHEET = "Suivi"

COLUMNS = [
    "Date",
    "Réunion",
    "Course",
    "Hippodrome",
    "Discipline",
    "Partants",
    "Tickets",
    "Mises_totales",
    "Gains_reels",
    "ROI_estime",
    "ROI_reel",
    "Verdict",
    "Arrivee_officielle",
    "Notes",
    "Timestamp_UTC",
]

def load_or_create(excel_path: Path) -> pd.DataFrame:
    if excel_path.exists():
        try:
            df = pd.read_excel(excel_path, sheet_name=DEFAULT_SHEET, engine="openpyxl")
        except Exception:
            df = pd.DataFrame(columns=COLUMNS)
    else:
        df = pd.DataFrame(columns=COLUMNS)
    # s'assurer de toutes les colonnes
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df[COLUMNS]

def append_row(df: pd.DataFrame, row: Dict[str, Any]) -> pd.DataFrame:
    df = pd.concat([df, pd.DataFrame([row], columns=COLUMNS)], ignore_index=True)
    return df

def save_df(excel_path: Path, df: pd.DataFrame) -> None:
    with pd.ExcelWriter(excel_path, engine="openpyxl", mode="w") as writer:
        df.to_excel(writer, sheet_name=DEFAULT_SHEET, index=False)

def main():
    ap = argparse.ArgumentParser(description="Met à jour le suivi Excel avec les résultats réels d'une course.")
    ap.add_argument("--excel", required=True, help="Chemin vers le fichier Excel de suivi.")
    ap.add_argument("--result", required=True, help="JSON produit par get_arrivee_geny.py")
    ap.add_argument("--tickets", required=True, help='Description courte des tickets joués, ex: "SP Dutching 6€ ; Trio 3.6€ ; ZE4 2.4€"')
    ap.add_argument("--mises", type=float, required=True, help="Mises totales (€).")
    ap.add_argument("--gains", type=float, required=True, help="Gains réels (€).")
    ap.add_argument("--roi_estime", type=float, default=None, help="ROI estimé (ex: 0.5 pour +50 %)")
    ap.add_argument("--verdict", default="", help='Ex: "Valide jeu réel" / "Abstention" / "Non jouable"')
    ap.add_argument("--notes", default="", help="Notes libres.")
    args = ap.parse_args()

    excel_path = Path(args.excel)
    result = json.loads(Path(args.result).read_text(encoding="utf-8"))

    mises = float(args.mises)
    gains = float(args.gains)
    roi_reel = None
    if mises > 0:
        roi_reel = (gains - mises) / mises
    ts_utc = int(time.time())

    row = {
        "Date": result.get("date"),
        "Réunion": result.get("reunion"),
        "Course": result.get("course"),
        "Hippodrome": result.get("hippodrome"),
        "Discipline": result.get("discipline"),
        "Partants": result.get("partants"),
        "Tickets": args.tickets,
        "Mises_totales": mises,
        "Gains_reels": gains,
        "ROI_estime": args.roi_estime,
        "ROI_reel": roi_reel,
        "Verdict": args.verdict,
        "Arrivee_officielle": result.get("arrivee_str"),
        "Notes": args.notes,
        "Timestamp_UTC": ts_utc,
    }

    df = load_or_create(excel_path)
    df = append_row(df, row)
    save_df(excel_path, df)

    print(f"[OK] Suivi mis à jour → {excel_path}")
    print(df.tail(1).to_string(index=False))

if __name__ == "__main__":
    main()
