from __future__ import annotations
import csv
import os
from datetime import datetime
from typing import Dict, Iterable

# En-tête standard pour le tracking GPI v5.1 (adapté à ton pipeline)
CSV_HEADER: Iterable[str] = [
    "timestamp",           # horodatage ISO
    "reunion",             # ex: R1
    "course",              # ex: C1
    "hippodrome",          # ex: Deauville
    "discipline",          # trot/plat/monté
    "distance_m",          # entier
    "partants",            # entier
    "phase",               # H30 / H5 / RESULT
    "url",                 # source course
    "tickets",             # description courte (SP dutching + combiné…)
    "mise_totale_eur",     # float (<= 5.0)
    "ev_global",           # float (ex: 0.42 = +42%)
    "roi_estime",          # float (ex: 0.25 = +25%)
    "verdict",             # 'valide' / 'abstention'
    "notes",               # libre
]

def _ensure_parent_dir(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def append_csv_line(csv_path: str, row: Dict[str, object]) -> None:
    """
    Ajoute une ligne dans le CSV de suivi en garantissant:
    - création auto du dossier parent
    - écriture de l'en-tête si fichier inexistant ou vide
    - ordre des colonnes = CSV_HEADER
    - valeurs manquantes => ""
    """
    _ensure_parent_dir(csv_path)
    file_exists = os.path.exists(csv_path) and os.path.getsize(csv_path) > 0

    # timestamp auto si absent
    row = dict(row) if row is not None else {}
    row.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))

    # normalise mise/EV/ROI si fournis en string
    for k in ("mise_totale_eur", "ev_global", "roi_estime"):
        if k in row and isinstance(row[k], str):
            try:
                row[k] = float(row[k].replace(",", "."))
            except Exception:
                pass

    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(CSV_HEADER))
        if not file_exists:
            writer.writeheader()
        # remet les clés dans l'ordre + valeurs vides si manquantes
        ordered = {k: row.get(k, "") for k in CSV_HEADER}
        writer.writerow(ordered)
