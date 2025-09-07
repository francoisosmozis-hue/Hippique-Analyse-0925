#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
online_fetch_zeturf.py — GPI v5.1 (corrected)
---------------------------------------------
- Réunions/courses ZEturf → JSON normalisé pipeline (H-30 / H-5 / manual)
- Corrections:
  * import manquant: from pathlib import Path
  * usage d'attributs argparse invalides: args.reunion-url → args.reunion_url (idem course)
  * sanitation d'URL: supprime l'ancre "#..."
  * robustesse meeting/date depuis l'URL

⚠️ Respectez les CGU du site source, throttle si nécessaire.
"""

import sys
import re
import json
import time
import math
import uuid
import argparse
import datetime as dt
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Any, Tuple

import requests
from bs4 import BeautifulSoup

# ----------------------------
# Utilitaires HTTP
# ----------------------------

DEFAULT_HEADERS = {
    "User-Agent": "AnalyseHippiqueBot/1.0 (+https://example.local; contact: owner@example.local)",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Connection": "keep-alive",
}

def http_get(url: str, retries: int = 3, timeout: int = 20) -> str:
    last_err = None
    for i in range(retries):
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET failed for {url}: {last_err}")

# ----------------------------
# Modèle de données
# ----------------------------

@dataclass
class Runner:
    num: str
    name: str
    jockey: Optional[str] = None
    trainer: Optional[str] = None
    sex_age: Optional[str] = None
    music: Optional[str] = None
    odds_win: Optional[float] = None
    odds_place: Optional[float] = None

@dataclass
class Race:
    r_label: str         # e.g. "R1"
    c_label: str         # e.g. "C2"
    meeting: str         # e.g. "Vincennes"
    date: str            # "YYYY-MM-DD"
    discipline: Optional[str] = None
    distance_m: Optional[int] = None
    going: Optional[str] = None
    track: Optional[str] = None
    partants: int = 0
    url_course: Optional[str] = None
    odds_snapshot: Optional[str] = None  # "H-30" or "H-5" or timestamp
    runners: List[Runner] = None

# ----------------------------
# Parsing ZEturf (HTML fragile → patterns tolérants)
# ----------------------------

def parse_meeting_page(html: str) -> List[Tuple[str, str]]:
    """
    Retourne une liste [(label_course, url_course), ...] depuis la page réunion.
    label_course typique: "R1C2"
    """
    soup = BeautifulSoup(html, "lxml")
    out = []
    # Liens de type "/fr/course/YYYY-MM-DD/R1C2-xxxxx"
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"/fr/course/\d{4}-\d{2}-\d{2}/R\d+C\d+", href):
            label_m = re.search(r"(R\d+C\d+)", href)
            if not label_m:
                continue
            label = label_m.group(1)
            url = "https://www.zeturf.fr" + href if href.startswith("/fr/") else href
            out.append((label, url))
    # Unicité
    seen = set()
    uniq = []
    for label, url in out:
        if (label, url) not in seen:
            uniq.append((label, url))
            seen.add((label, url))
    return uniq

def _text(el):
    return re.sub(r"\s+", " ", el.get_text(strip=True)) if el else ""

def parse_course_page(html: str) -> Dict[str, Any]:
    """
    Extrait infos de course + partants + cotes (si disponibles).
    Retourne un dict brut.
    """
    soup = BeautifulSoup(html, "lxml")

    # Entête course
    h1 = soup.find("h1")
    title = _text(h1)
    meeting = ""
    discipline = ""
    distance_m = None
    going = None
    track = None
    partants = 0

    # Heuristique: trouver infos dans les blocs "course-infos" / "atf-infos"
    info_blobs = soup.find_all(["ul","div"], class_=re.compile(r"(course|event|meeting|infos|details)", re.I))
    for blob in info_blobs:
        txt = _text(blob)
        # distance
        m = re.search(r"(\d{3,5})\s?m", txt)
        if m: distance_m = int(m.group(1))
        # partants
        m = re.search(r"(\d+)\s+partants", txt, re.I)
        if m: partants = int(m.group(1))
        # discipline
        mm = re.search(r"(trot|attelé|monté|plat|haies|steeple)", txt, re.I)
        if mm:
            discipline = mm.group(1)
        # going / piste
        mg = re.search(r"terrain\s*:\s*([A-Za-zéèàûô\- ]+)", txt, re.I)
        if mg:
            going = mg.group(1).strip()

    # Meeting (hippodrome) – souvent dans le title ou breadcrumb
    breadcrumb = soup.find("nav") or soup.find("ol")
    if breadcrumb:
        btxt = _text(breadcrumb)
        m = re.search(r"(Vincennes|Cabourg|Lyon|Toulouse|Caen|ParisLongchamp|Marseille\-Bor[eé]ly|Strasbourg|Hy[eè]res|La Teste\-de\-Buch)", btxt, re.I)
        if m: meeting = m.group(1)

    # Liste partants
    runners = []
    rows = soup.find_all(["tr","article","div"], class_=re.compile(r"(runner|partant|cheval|row)", re.I))
    for row in rows:
        row_txt = _text(row)
        # numéro
        mnum = re.search(r"^\s*(\d{1,2})\s+", row_txt)
        num = mnum.group(1) if mnum else None

        # nom cheval : balises <a> ou <strong>
        name = None
        for cand in row.find_all(["a","strong","span"]):
            t = _text(cand)
            if len(t) > 2 and not re.search(r"(jockey|driver|entra[iî]neur|coach|poids|kg|ans)", t, re.I):
                name = t
                break

        # jockey/driver
        jockey = None
        m = re.search(r"(Driver|Jockey|Jocke[y|e])\s*:\s*([A-ZÉÈÎÂÙÂ\- ]+)", row_txt, re.I)
        if m:
            jockey = m.group(2).strip()
        else:
            m = re.search(r"(avec|par)\s+([A-ZÉÈÎÂÙÂ][A-Za-zÉÈÎÂÙÂ\-\s]+)", row_txt)
            if m:
                jockey = m.group(2).strip()

        # entraineur
        trainer = None
        me = re.search(r"(Entra[iî]neur|Trainer)\s*:\s*([A-ZÉÈÎÂÙÂ\- ]+)", row_txt, re.I)
        if me: trainer = me.group(2).strip()

        # musique
        music = None
        mu = re.search(r"(\d[a-z]?(?:-\d[a-z]?){2,})", row_txt, re.I)
        if mu: music = mu.group(1)

        # cotes (si présentes)
        odds_win, odds_place = None, None
        mw = re.search(r"Cote\s*Gagnant\s*:\s*([0-9]+(?:[.,][0-9]+)?)", row_txt, re.I)
        if mw: odds_win = float(mw.group(1).replace(",", "."))
        mp = re.search(r"Cote\s*Placé\s*:\s*([0-9]+(?:[.,][0-9]+)?)", row_txt, re.I)
        if mp: odds_place = float(mp.group(1).replace(",", "."))

        if num and name:
            runners.append({
                "num": num,
                "name": name,
                "jockey": jockey,
                "trainer": trainer,
                "music": music,
                "odds_win": odds_win,
                "odds_place": odds_place,
            })

    return {
        "title": title,
        "meeting": meeting,
        "discipline": discipline,
        "distance_m": distance_m,
        "going": going,
        "track": track,
        "partants": partants,
        "runners": runners,
    }

# ----------------------------
# Normalisation & sorties
# ----------------------------

# ----------------------------
# Enrichissement: H-30 odds, form_score, SR normalisés
# ----------------------------
def _norm_sr(x):
    try:
        if x is None:
            return None
        if isinstance(x, str) and x.strip().endswith("%"):
            return max(0.0, min(1.0, float(x.strip().rstrip("%"))/100.0))
        xv = float(x)
        if xv > 1.0:
            return max(0.0, min(1.0, xv/100.0))
        return max(0.0, min(1.0, xv))
    except Exception:
        return None

def _form_score_from_music(music: str) -> float:
    if not music or not isinstance(music, str):
        return 0.0
    seq = []
    for ch in music:
        if ch.isdigit():
            try:
                val = int(ch)
                if val <= 0:
                    continue
                seq.append(val)
            except Exception:
                continue
        else:
            # lettres -> 10 (mauvais/incident)
            seq.append(10)
    if not seq:
        return 0.0
    last = seq[-4:]
    def s_of(p):
        if p == 1: return 1.0
        if p == 2: return 0.8
        if p == 3: return 0.6
        if p == 4: return 0.4
        if p == 5: return 0.2
        return 0.0
    w = [0.4, 0.3, 0.2, 0.1]
    scores = [s_of(v) for v in last]
    w = w[-len(scores):]
    num = sum(si*wi for si,wi in zip(scores, w))
    den = sum(w)
    return max(0.0, min(1.0, num/den if den>0 else 0.0))

def _load_prev_map(prev_path):
    try:
        pj = Path(prev_path)
        if not pj.exists():
            return {}
        prev = json.loads(pj.read_text(encoding="utf-8"))
        out = {}
        for r in prev.get("runners", []):
            k = str(r.get("num"))
            out[k] = {"ow": r.get("odds_win"), "op": r.get("odds_place")}
        return out
    except Exception:
        return {}

def _find_prev_json(prev_arg: str, date_str: str, meeting: str, r_label: str, c_label: str) -> str:
    if not prev_arg:
        return ""
    pp = Path(prev_arg)
    if pp.is_file():
        return str(pp)
    if pp.is_dir():
        # expected filename pattern
        cand = pp / f"{date_str}_{meeting}_{r_label}{c_label}_H-30.json".replace(" ", "")
        if cand.exists():
            return str(cand)
        # fallback: search by pattern
        pats = list(pp.glob(f"*{meeting}_{r_label}{c_label}_H-30.json".replace(" ", "")))
        if pats:
            return str(pats[0])
    return ""

def enrich_raw(raw: Dict[str, Any], prev_json_path: str) -> Dict[str, Any]:
    # normalize sr and add form_score
    for r in raw.get("runners", []):
        jn = _norm_sr(r.get("jockey_sr"))
        en = _norm_sr(r.get("trainer_sr"))
        if jn is not None: r["jockey_sr"] = jn
        if en is not None: r["trainer_sr"] = en
        if r.get("form_score") is None:
            music = r.get("music") or r.get("musique") or r.get("form")
            r["form_score"] = _form_score_from_music(music) if isinstance(music, str) else 0.0
    # add H-30 odds if provided
    if prev_json_path:
        prev_map = _load_prev_map(prev_json_path)
        for r in raw.get("runners", []):
            num = str(r.get("num"))
            pj = prev_map.get(num, {})
            if pj.get("ow") is not None:
                r["odds_win_h30"] = pj["ow"]
            if pj.get("op") is not None:
                r["odds_place_h30"] = pj["op"]
    return raw

def to_pipeline_json(r_label: str, c_label: str, meeting: str, date_str: str, course_url: str, raw: Dict[str, Any], snapshot_label: str) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "standard": "GPIv5.1",
        "meeting": meeting or raw.get("meeting") or "",
        "r_label": r_label,
        "c_label": c_label,
        "date": date_str,
        "discipline": raw.get("discipline"),
        "distance_m": raw.get("distance_m"),
        "partants": raw.get("partants"),
        "going": raw.get("going"),
        "course_url": course_url,
        "snapshot": snapshot_label,  # "H-30" / "H-5" / "manual"
        "runners": raw.get("runners", []),
        "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
    }

def save_json(obj: Dict[str, Any], outpath: str):
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# ----------------------------
# CLI
# ----------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Fetch ZEturf meetings/courses/odds → JSON normalisé (GPI v5.1)")
    p.add_argument("--reunion-url", dest="reunion_url", help="URL ZEturf de la réunion (ex: https://www.zeturf.fr/fr/reunion/2025-09-06/R1-vincennes)")
    p.add_argument("--course-url",  dest="course_url",  help="URL ZEturf de la course (ex: https://www.zeturf.fr/fr/course/2025-09-06/R1C2-vinc)")
    p.add_argument("--snapshot", default="manual", choices=["H-30","H-5","manual"], help="Étiquette du snapshot")
    p.add_argument("--out", default="data", help="Dossier de sortie")
    p.add_argument("--prev-json", help="Fichier H-30 correspondant OU dossier contenant les H-30")
    return p.parse_args(argv)

def main(argv=None):
    args = parse_args(argv)

    # Sanitize anchors (e.g. #a-l-affiche-tab)
    if args.reunion_url:
        args.reunion_url = args.reunion_url.split('#', 1)[0]
    if args.course_url:
        args.course_url = args.course_url.split('#', 1)[0]

    Path(args.out).mkdir(parents=True, exist_ok=True)

    if not args.reunion_url and not args.course_url:
        print("Vous devez fournir --reunion-url ou --course-url", file=sys.stderr)
        return 2

    if args.reunion_url:
        html = http_get(args.reunion_url)
        pairs = parse_meeting_page(html)

        date_match = re.search(r"/reunion/(\d{4}-\d{2}-\d{2})/R\d+-", args.reunion_url)
        date_str = date_match.group(1) if date_match else dt.date.today().isoformat()
        # Essayer d'extraire le meeting (hippodrome) depuis l'URL
        m_meet = re.search(r"/reunion/\d{4}-\d{2}-\d{2}/(R\d+)-([a-z0-9\-]+)", args.reunion_url, re.I)
        meeting = (m_meet.group(2).replace("-", " ") if m_meet else "").title()

        for label, url in pairs:
            rc = re.match(r"R(\d+)C(\d+)", label, re.I)
            if not rc:
                continue
            r_label = f"R{rc.group(1)}"
            c_label = f"C{rc.group(2)}"
            course_html = http_get(url)
            raw = parse_course_page(course_html)
            prevp = _find_prev_json(args.prev_json, date_str, meeting, r_label, c_label)
            raw = enrich_raw(raw, prevp)
            out = to_pipeline_json(r_label, c_label, meeting, date_str, url, raw, args.snapshot)
            outname = f"{date_str}_{meeting}_{r_label}{c_label}_{args.snapshot}.json".replace(" ", "")
            save_json(out, str(Path(args.out) / outname))
            print(outname)
        return 0

    if args.course_url:
        html = http_get(args.course_url)
        # Inférences
        rc = re.search(r"/course/(\d{4}-\d{2}-\d{2})/(R\d+C\d+)-([a-z0-9\-]+)", args.course_url, re.I)
        date_str = rc.group(1) if rc else dt.date.today().isoformat()
        label = rc.group(2) if rc else "R?C?"
        m_meet = re.search(r"/course/\d{4}-\d{2}-\d{2}/R\d+C\d+-([a-z0-9\-]+)", args.course_url, re.I)
        meeting = (m_meet.group(1).replace("-", " ") if m_meet else "").title()

        raw = parse_course_page(html)
        # Enrich with prev json if available
        # r_label/c_label not known yet; temporarily extract after computing
        r_m = re.search(r"(R\d+)", label)
        c_m = re.search(r"(C\d+)", label)
        r_label = r_m.group(1) if r_m else "R?"
        c_label = c_m.group(1) if c_m else "C?"

        prevp = _find_prev_json(args.prev_json, date_str, meeting, r_label, c_label)
        raw = enrich_raw(raw, prevp)
        out = to_pipeline_json(r_label, c_label, meeting, date_str, args.course_url, raw, args.snapshot)
        outname = f"{date_str}_{meeting}_{r_label}{c_label}_{args.snapshot}.json".replace(" ", "")
        save_json(out, str(Path(args.out) / outname))
        print(outname)
        return 0

    return 0

if __name__ == "__main__":
    sys.exit(main())
