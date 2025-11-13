#!/usr/bin/env python3
"""
pmu_geny_scraper.py
====================

Ce script fournit un exemple de collecte de données hippiques auprès du
PMU (via l'API non officielle **offline.turfinfo.api.pmu.fr**) et de
Geny.com.  Il récupère, pour une date donnée, la liste des réunions,
des courses et des partants, puis écrit un fichier CSV avec les
informations essentielles: nom du cheval, numéro de corde (numPmu),
nom du jockey/driver, nom de l'entraîneur ainsi que les derniers
"rapports" connus (cote gagnante) fournis par le PMU.  Les
utilisateurs peuvent lancer ce script quotidiennement pour créer un
jeu de données actualisé qui servira de base à un modèle prédictif ou
à des analyses statistiques.

Fonctionnalités:

* **fetch_program(date)** — interroge l'endpoint programme du PMU pour
  récupérer toutes les réunions et courses d'une date donnée.
* **fetch_participants(date, reunion, course)** — interroge
  l'endpoint participants pour récupérer la liste des partants, avec
  les cotes et les informations sur les chevaux/jockeys/entraîneurs.
* **parse_participants(json_data)** — extrait les champs pertinents
  d'une réponse participants et les prépare pour l'écriture dans le
  CSV.
* **main()** — point d'entrée CLI : accepte une date (au format
  `AAAAMMJJ`), éventuellement une réunion spécifique (`R1`, `R2`, …),
  et le chemin vers un fichier CSV de sortie.  Itere sur chaque
  course et écrit les lignes dans le CSV.

Remarques:

* L'API `offline.turfinfo.api.pmu.fr` n'est pas documentée
  officiellement.  Son usage doit rester respectueux (pas trop de
  requêtes par seconde) et conforme aux conditions générales du site.
  Ce script ne met en cache aucune réponse; en production on
  devrait implémenter un mécanisme de cache et de temporisation.
* Les champs `dernierRapportDirect.rapport` et
  `dernierRapportReference.rapport` représentent les derniers
  "rapports" (cotes) disponibles au moment de l'appel.  Ils ne
  correspondent pas nécessairement aux cotes en temps réel mais
  donnent une indication du rapport éventuel pour un pari gagnant.
* Pour enrichir avec des statistiques de jockeys/entraîneurs (j_rate
  et e_rate), il faudrait soit scruter les pages détaillées de
  Geny.com (non couvert dans ce script), soit utiliser une API
  professionnelle (voir la documentation jointe dans le rapport).

Exemple d'utilisation:

```
# Collecte des courses du 15 octobre 2025 et écriture dans un CSV
python pmu_geny_scraper.py --date 20251015 --out races_20251015.csv

# Collecte uniquement de la réunion 1 du 2025-10-15
python pmu_geny_scraper.py --date 20251015 --reunion 1 --out R1_20251015.csv
```
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import requests

BASE_URL = "https://offline.turfinfo.api.pmu.fr/rest/client/7"


@dataclass
class Participant:
    """Représente un partant dans une course."""

    date: str
    reunion: str
    course: str
    hippodrome: str
    discipline: str
    num: str
    cheval: str
    jockey: str | None
    entraineur: str | None
    rapport_direct: float | None
    rapport_reference: float | None

    def to_row(self) -> list[str]:
        """Convertit le participant en liste pour écriture CSV."""
        return [
            self.date,
            self.reunion,
            self.course,
            self.hippodrome,
            self.discipline,
            self.num,
            self.cheval,
            self.jockey or "",
            self.entraineur or "",
            f"{self.rapport_direct}" if self.rapport_direct is not None else "",
            f"{self.rapport_reference}" if self.rapport_reference is not None else "",
        ]


def fetch_program(date_str: str) -> dict[str, any]:
    """
    Récupère le programme des réunions pour une date donnée.

    Parameters
    ----------
    date_str : str
        Date au format `AAAAMMJJ` (ex. "20251015").

    Returns
    -------
    dict
        Un dictionnaire Python issu du JSON retourné par l'API.
    """
    url = f"{BASE_URL}/programme/{date_str}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Réponse JSON invalide pour {url}") from exc


def fetch_participants(date_str: str, reunion: str, course: str) -> dict[str, any]:
    """
    Récupère la liste des partants pour une course spécifique.

    Parameters
    ----------
    date_str : str
        Date au format `AAAAMMJJ`.
    reunion : str
        Numéro de la réunion (sans le 'R') : "1", "2", etc.
    course : str
        Numéro de la course (sans le 'C') : "1", "2", etc.

    Returns
    -------
    dict
        Le JSON renvoyé par l'API pour les participants.
    """
    url = f"{BASE_URL}/programme/{date_str}/R{reunion}/C{course}/participants"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Réponse JSON invalide pour {url}") from exc


def parse_participants(
    date_str: str,
    reunion: str,
    course: str,
    hippodrome: str,
    discipline: str,
    data: dict[str, any],
) -> Iterable[Participant]:
    """
    Transforme un JSON de participants en objets Participant.

    Chaque participant du JSON possède de nombreux champs.  Cette
    fonction en extrait quelques‑uns: numéro PMU (`numPmu`), nom du
    cheval (`nom`), nom du jockey ou driver (`driver` ou `jockey`),
    nom de l'entraîneur (`entraineur`), et les derniers rapports
    direct/reference.

    Parameters
    ----------
    date_str : str
        Date au format `AAAAMMJJ`.
    reunion : str
        Numéro de la réunion sans le 'R'.
    course : str
        Numéro de la course sans le 'C'.
    hippodrome : str
        Nom de l'hippodrome.
    discipline : str
        Type de course (trot, plat, obstacle, etc.).
    data : dict
        JSON des participants retourné par l'API.

    Yields
    ------
    Participant
        Un générateur d'objets Participant pour chaque cheval.
    """
    participants = data.get("participants", [])
    for p in participants:
        num = str(p.get("numPmu", p.get("numPmu1", "")))
        cheval = p.get("nom", "").strip()
        # Selon la discipline, l'API utilise soit 'driver' (trot), soit 'jockey' (plat)
        jockey = p.get("driver") or p.get("jockey")
        # Certains champs sont des dicts ; on récupère juste le nom si présent
        if isinstance(jockey, dict):
            jockey = jockey.get("nom") or jockey.get("name")
        entraineur = p.get("entraineur")
        if isinstance(entraineur, dict):
            entraineur = entraineur.get("nom") or entraineur.get("name")
        # Rapports direct et référence
        direct = p.get("dernierRapportDirect") or {}
        reference = p.get("dernierRapportReference") or {}
        rapport_direct = None
        rapport_reference = None
        try:
            rapport_direct = float(direct.get("rapport")) if direct.get("rapport") is not None else None
        except Exception:
            rapport_direct = None
        try:
            rapport_reference = float(reference.get("rapport")) if reference.get("rapport") is not None else None
        except Exception:
            rapport_reference = None
        yield Participant(
            date=date_str,
            reunion=f"R{reunion}",
            course=f"C{course}",
            hippodrome=hippodrome,
            discipline=discipline,
            num=num,
            cheval=cheval,
            jockey=jockey,
            entraineur=entraineur,
            rapport_direct=rapport_direct,
            rapport_reference=rapport_reference,
        )


def write_csv(path: Path, participants: Iterable[Participant]) -> None:
    """
    Écrit les participants dans un fichier CSV.  Si le fichier existe,
    les lignes sont ajoutées à la fin.  Un en‑tête est ajouté
    uniquement lorsque le fichier est créé.

    Parameters
    ----------
    path : Path
        Chemin du fichier CSV.
    participants : Iterable[Participant]
        Les participants à écrire.
    """
    header = [
        "date",
        "reunion",
        "course",
        "hippodrome",
        "discipline",
        "num",
        "cheval",
        "jockey",
        "entraineur",
        "rapport_direct",
        "rapport_reference",
    ]
    file_exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(header)
        for p in participants:
            writer.writerow(p.to_row())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape les courses PMU pour une date donnée.")
    parser.add_argument(
        "--date",
        required=True,
        help="Date des réunions au format AAAAMMJJ (ex. 20251015)",
    )
    parser.add_argument(
        "--reunion",
        help="Numéro de la réunion à traiter (ex. 1 pour R1). Si non spécifié, toutes les réunions sont traitées.",
    )
    parser.add_argument(
        "--out",
        default="races.csv",
        help="Chemin du fichier CSV de sortie.",
    )
    args = parser.parse_args(argv)

    date_yyyymmdd = args.date
    try:
        # Convert YYYYMMDD to DDMMYYYY for the API
        date_obj = dt.datetime.strptime(date_yyyymmdd, "%Y%m%d")
        date_ddmmyyyy = date_obj.strftime("%d%m%Y")
    except ValueError:
        print(f"Format de date invalide: {date_yyyymmdd}. Attendu: AAAAMMJJ", file=sys.stderr)
        return 1

    reunion_filter = args.reunion
    out_path = Path(args.out)

    try:
        programme = fetch_program(date_ddmmyyyy)
    except Exception as exc:
        print(f"Erreur lors de la récupération du programme pour {date_str}: {exc}", file=sys.stderr)
        return 1

    reunions = programme.get("programme", {}).get("reunions", [])
    if not reunions:
        print(f"Aucune réunion trouvée pour la date {date_str}")
        return 1

    all_participants: list[Participant] = []
    for reu in reunions:
        reu_num = str(reu.get("numReunion"))
        if reunion_filter and reu_num != str(reunion_filter):
            continue
        hippodrome = reu.get("hippodrome", {}).get("libelleCourt", "") or reu.get("hippodrome", {}).get("nomHippodrome", "")
        discipline = reu.get("discipline" , "") or ""
        courses = reu.get("courses", [])
        for course in courses:
            course_num = str(course.get("numOrdreCourse"))
            # Récupération des participants
            try:
                part_json = fetch_participants(date_ddmmyyyy, reu_num, course_num)
            except Exception as exc:
                print(
                    f"Erreur lors de la récupération des participants pour {date_ddmmyyyy} R{reu_num} C{course_num}: {exc}",
                    file=sys.stderr,
                )
                continue
            # Enrichit les participants
            participants = list(
                parse_participants(
                    date_yyyymmdd, # Use YYYYMMDD for the CSV output
                    reu_num,
                    course_num,
                    hippodrome=hippodrome,
                    discipline=discipline,
                    data=part_json,
                )
            )
            all_participants.extend(participants)

    if not all_participants:
        print(f"Aucun participant collecté pour {date_str}")
        return 1

    # Écriture du CSV
    write_csv(out_path, all_participants)
    print(f"{len(all_participants)} lignes écrites dans {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
