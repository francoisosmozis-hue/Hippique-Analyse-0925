#!/usr/bin/env python3
"""
prompt_analyse.py — stub minimal
Usage:
  python prompt_analyse.py --race "R1C3 Vincennes 2025-10-20 attelé 12" --budget 5 --out prompts/prompt_R1C3.txt
Écrit un prompt GPI v5.1 simple dans --out.
"""
import argparse
import os
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--race", required=True)
    ap.add_argument("--budget", type=float, default=5.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    Path(os.path.dirname(args.out) or ".").mkdir(parents=True, exist_ok=True)
    content = (
        f"# Analyse GPI v5.1\n"
        f"Course : {args.race}\n"
        f"Budget : {args.budget:.2f} €\n"
        f"Checklist : chronos / JE / cotes H-30 & H-5 / overround / EV thresholds\n"
        f"Objectif : SP Dutching 60% + 1 combiné 40% si EV≥+40% & payout≥10€ ; cap total 5€\n"
    )
    Path(args.out).write_text(content, encoding="utf-8")
    print(f"[prompt_analyse] écrit → {args.out}")

if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Compatibilité API FastAPI (service.py)
# ---------------------------------------------------------------------------

def build_prompt(reunion: str, course: str, budget: float = 5.0, mode: str = "GPI_v5_1") -> str:
    """
    Génère le texte du prompt GPI v5.1 standard pour une course donnée.
    Appelé depuis service.py (/prompt/generate)
    """
    header = f"# PROMPT GPI {mode}\n"
    body = (
        f"Réunion {reunion} — Course {course}\n"
        f"Budget alloué : {budget:.2f} €\n"
        f"Objectif : ROI ≥ +40 %, EV globale ≥ +20 %\n"
        f"Structure : Dutching SP (60 %) + combiné value (40 %)\n"
        f"Critères : chronos / cotes H-30 vs H-5 / stats J-E / profil oublié / overround\n"
        f"Cap total : 5 € (Kelly fractionné)\n"
    )
    checklist = (
        "Checklist pré-analyse :\n"
        " - ✅ Chronos 3 dernières courses\n"
        " - ✅ Mouvements de cotes H-30 / H-5\n"
        " - ✅ Statistiques Jockey / Entraîneur\n"
        " - ✅ Retard de gains & profil oublié\n"
        " - ✅ EV simulée ≥ +40 %, ROI simulé ≥ +20 %\n"
    )
    return header + body + checklist
