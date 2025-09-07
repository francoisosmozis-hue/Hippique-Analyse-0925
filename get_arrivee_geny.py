#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
get_arrivee_geny.py  —  Consolidated (Post-R10C5) — NO external scraping
-----------------------------------------------------------------------
Objectif
    Normaliser la récupération de l'arrivée officielle à partir d'une ENTRÉE LOCALE
    (texte brut, CSV simple ou HTML sauvegardé), SANS aucun appel réseau.

Pourquoi
    La pipeline "Analyse Hippique" ne doit plus dépendre de sources externes
    ni laisser la moindre trace "pmu" : ce module se concentre sur un parsing
    hors-ligne de captures/export GENY (ou texte libre).

Entrées supportées (au choix)
    1) Texte/ligne simple (ex. "Arrivée : 1 7 4 12")
    2) Fichier CSV minimal (colonnes tolérées: place,numero,horse)
    3) Fichier HTML sauvegardé contenant une chaîne "Arrivée" + séquence de numéros

Sortie
    Dictionnaire python SERIALISABLE en JSON :
    {
      "date": "2025-07-14",
      "reunion": "R10",
      "course": "C5",
      "hippodrome": "Tokyo",
      "discipline": "plat",
      "partants": 10,
      "arrivee": [1,7,4,12],
      "arrivee_str": "1 7 4 12",
      "source": "text|csv|html",
      "notes": "..."
    }

CLI (exemples)
    # 1) Depuis une ligne de texte
    python get_arrivee_geny.py --race "R10C5 Tokyo 2025-07-14 plat 10" --arrivee "1 7 4 12" --out r10c5.json

    # 2) Depuis un HTML local sauvegardé
    python get_arrivee_geny.py --race "R10C5 Tokyo 2025-07-14 plat 10" --html path/to/page.html --out r10c5.json

    # 3) Depuis un CSV minimal
    python get_arrivee_geny.py --race "R10C5 Tokyo 2025-07-14 plat 10" --csv path/to/arrivee.csv --out r10c5.json

Notes
    - AUCUNE dépendance externe (bs4/lxml). Parsing via regex.
    - Tolérant aux formats européens (espaces, tirets, virgules).
    - Strictement SANS mention ni dépendance "pmu".
"""
from __future__ import annotations
import argparse
import csv
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple

ARRIVEEREGEX = re.compile(r"(?:Arriv[ée]e[^0-9]*)([\d\s\-–,;]+)")

@dataclass
class RaceMeta:
    reunion: str
    course: str
    hippodrome: Optional[str] = None
    date: Optional[str] = None
    discipline: Optional[str] = None
    partants: Optional[int] = None

def parse_race_meta(raw: str) -> RaceMeta:
    """
    Accepte des formats flexibles, ex.:
      "R10C5 Tokyo 2025-07-14 plat 10"
      "R1C6 Clairefontaine 2025/08/18 plat 10 partants"
    """
    tokens = raw.strip().split()
    # Chercher R..C..
    r = next((t for t in tokens if t.upper().startswith("R") and "C" in t.upper()), None)
    reunion, course = "R?", "C?"
    if r:
        up = r.upper()
        i = up.find("C")
        reunion, course = up[:i], up[i:]
        tokens.remove(r)

    # Date YYYY-MM-DD ou YYYY/MM/DD
    date = None
    for t in list(tokens):
        if re.match(r"\d{4}[-/]\d{2}[-/]\d{2}", t):
            date = t.replace("/", "-")
            tokens.remove(t)
            break

    # Discipline plausible
    discipline = None
    for d in ["plat", "trot", "attel\u00e9", "attelé", "mont\u00e9", "monté", "obstacles", "haies", "steeple"]:
        if d in [x.lower() for x in tokens]:
            discipline = d
            tokens.remove(d)
            break

    # Partants (dernier entier restant > 0)
    partants = None
    for t in reversed(tokens):
        if t.isdigit():
            partants = int(t)
            tokens.remove(t)
            break

    hippodrome = " ".join(tokens) if tokens else None
    return RaceMeta(reunion=reunion, course=course, hippodrome=hippodrome, date=date, discipline=discipline, partants=partants)

def clean_seq_to_ints(seq: str) -> List[int]:
    seq = re.sub(r"[^\d\s]", " ", seq)  # garder que chiffres/espaces
    nums = [int(x) for x in seq.split() if x.isdigit()]
    return nums

def parse_text_line(line: str) -> List[int]:
    # Essaye soit "Arrivée : 1 7 4 12", soit juste "1 7 4 12"
    m = ARRIVEEREGEX.search(line)
    if m:
        return clean_seq_to_ints(m.group(1))
    return clean_seq_to_ints(line)

def parse_html_file(path: Path) -> List[int]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    m = ARRIVEEREGEX.search(text)
    if m:
        return clean_seq_to_ints(m.group(1))
    # fallback: chercher une séquence de 3+ nombres isolés
    m2 = re.search(r"(\b\d{1,2}\b(?:\s+[–-]?\s*\b\d{1,2}\b){2,})", text)
    if m2:
        return clean_seq_to_ints(m2.group(1))
    raise ValueError("Aucune séquence d'arrivée détectée dans le HTML.")

def parse_csv_file(path: Path) -> List[int]:
    ranks = {}
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        # colonnes tolérées: place, rang, numero, number, horse
        for row in reader:
            place = row.get("place") or row.get("rang") or row.get("Rank") or row.get("Rang")
            num = row.get("numero") or row.get("number") or row.get("Num") or row.get("num")
            if place and num and str(place).isdigit() and str(num).isdigit():
                ranks[int(place)] = int(num)
    if not ranks:
        raise ValueError("CSV non reconnu. Colonnes attendues: place/rang + numero/number.")
    arrivee = [v for k, v in sorted(ranks.items(), key=lambda kv: kv[0])]
    return arrivee

def build_payload(meta: RaceMeta, arrivee: List[int], source: str, notes: str = "") -> dict:
    return {
        "date": meta.date,
        "reunion": meta.reunion,
        "course": meta.course,
        "hippodrome": meta.hippodrome,
        "discipline": meta.discipline,
        "partants": meta.partants,
        "arrivee": arrivee,
        "arrivee_str": " ".join(str(x) for x in arrivee),
        "source": source,
        "notes": notes,
    }

def main():
    ap = argparse.ArgumentParser(description="Parser hors-ligne de l'arrivée officielle (captures GENY/texte).")
    ap.add_argument("--race", required=True, help='Ex: "R10C5 Tokyo 2025-07-14 plat 10"')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--arrivee", help='Ligne simple, ex: "1 7 4 12" ou "Arrivée : 1 7 4 12"')
    g.add_argument("--html", help="Chemin vers un fichier HTML sauvegardé localement.")
    g.add_argument("--csv", help="Chemin vers un CSV minimal (place/rang + numero).")
    ap.add_argument("--out", help="Chemin fichier JSON de sortie (par défaut: arrivee.json)", default="arrivee.json")
    ap.add_argument("--notes", default="", help="Notes libres à intégrer.")
    args = ap.parse_args()

    meta = parse_race_meta(args.race)

    if args.arrivee:
        arr = parse_text_line(args.arrivee)
        source = "text"
    elif args.html:
        arr = parse_html_file(Path(args.html))
        source = "html"
    else:
        arr = parse_csv_file(Path(args.csv))
        source = "csv"

    if not arr:
        raise SystemExit("Arrivée vide: impossible de continuer.")
    payload = build_payload(meta, arr, source, notes=args.notes)

    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Arrivée sauvegardée → {args.out}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
