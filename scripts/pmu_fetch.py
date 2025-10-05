#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pmu_fetch.py — Client léger pour endpoints JSON turfinfo.api.pmu.fr
- Programme du jour (liste des réunions/courses)
- Participants de chaque course
- Rapports définitifs (arrivées)
⚠️ Endpoints non documentés et susceptibles de changer. Respecte un rate-limit.
"""

from __future__ import annotations
import argparse, datetime as dt, json, time
from pathlib import Path
import requests

ONLINE = "https://online.turfinfo.api.pmu.fr/rest/client"
OFFLINE = "https://offline.turfinfo.api.pmu.fr/rest/client"
UA = {"User-Agent": "pmu-open-client/0.1 (+roi-analyse)"}

def dmy(date: dt.date) -> str:
    return date.strftime("%d%m%Y")  # JJMMAAAA

def _get(url: str, retries: int = 3, timeout: int = 15):
    for i in range(retries):
        r = requests.get(url, headers=UA, timeout=timeout)
        if r.ok:
            try:
                return r.json()
            except Exception:
                # parfois l’API renvoie du texte/HTML en erreur
                raise RuntimeError(f"Réponse non-JSON pour {url[:120]}")
        time.sleep(0.6 * (i + 1))
    raise RuntimeError(f"Échec GET {url}")

def fetch_program(date: dt.date) -> dict:
    # Variante la plus courante et riche
    url = f"{OFFLINE}/7/programme/{dmy(date)}"
    return _get(url)

def iter_fr_courses(program_json: dict):
    """
    Itère sur (R, C, reunion_meta) en filtrant les réunions françaises.
    Le JSON observé: data['programme']['reunions'][i]['courses'][j]
    avec 'numReunion' et 'numOrdre' sur chaque course.
    """
    prog = program_json.get("programme", {})
    reunions = prog.get("reunions", []) or []
    for rn in reunions:
        # heuristique pays
        pays_obj = rn.get("pays", {})
        pays_code = pays_obj.get("code") if isinstance(pays_obj, dict) else pays_obj
        pays = (rn.get("codePays") or pays_code or rn.get("countryCode") or "").upper()
        if "FR" not in pays and pays != "":  # si le champ existe et ≠ FR, on saute
            continue
        courses = rn.get("courses", []) or []
        for c in courses:
            r = c.get("numReunion") or rn.get("numReunion") or rn.get("numOfficiel")
            n = c.get("numOrdre") or c.get("numCourse")
            if r and n:
                yield int(r), int(n), {
                    "hippodrome": rn.get("hippodrome", {}).get("libelleCourt") or rn.get("nomHippodrome"),
                    "heure": c.get("heureDepart"),
                    "discipline": c.get("discipline"),
                    "pays": pays or "FR?"
                }

def fetch_participants(date: dt.date, r: int, c: int) -> dict:
    url = f"{OFFLINE}/7/programme/{dmy(date)}/R{r}/C{c}/participants"
    return _get(url)

def fetch_rapports(date: dt.date, r: int, c: int) -> dict:
    url = f"{ONLINE}/1/programme/{dmy(date)}/R{r}/C{c}/rapports-definitifs"
    return _get(url)

def save_json(obj: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def main():
    ap = argparse.ArgumentParser(description="Fetch PMU open endpoints (FR)")
    ap.add_argument("--date", help="YYYY-MM-DD (défaut: aujourd’hui)", default=dt.date.today().isoformat())
    ap.add_argument("--out", help="Dossier de sortie", default="data/pmu")
    ap.add_argument("--sleep", type=float, default=0.5, help="pause entre requêtes")
    args = ap.parse_args()

    date = dt.date.fromisoformat(args.date)
    out_root = Path(args.out) / date.isoformat()
    print(f"[i] Date {date} → dossier {out_root}")

    # 1) Programme
    prog = fetch_program(date)
    save_json(prog, out_root / "programme.json")

    # 2) Boucle R/C (FR)
    count = 0
    for r, c, meta in iter_fr_courses(prog):
        course_dir = out_root / f"R{r}" / f"C{c}"
        print(f" - R{r}C{c} {meta.get('hippodrome','?')} {meta.get('heure','?')}) ({meta.get('discipline','?')})")
        try:
            part = fetch_participants(date, r, c)
            save_json(part, course_dir / "participants.json")
        except Exception as e:
            print(f"   ! participants indisponibles : {e}")
        time.sleep(args.sleep)
        try:
            rap = fetch_rapports(date, r, c)
            save_json(rap, course_dir / "rapports_definitifs.json")
        except Exception as e:
            print(f"   ! rapports-definitifs indisponibles (course pas encore arrivée ?) : {e}")
        time.sleep(args.sleep)
        count += 1

    print(f"[✓] Terminé. Courses traitées (FR): {count}. Fichiers sous {out_root}")

if __name__ == "__main__":
    main()
