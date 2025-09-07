
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_je_stats_v4.py — GPI v5.1 (Geny via noms) + Cheval Stats
---------------------------------------------------------------
Améliorations vs v3 :
- Extrait j_rate / e_rate comme avant (cache disque, TTL, retries).
- **Ajoute des stats cheval** (si trouvables sur la page /cheval) :
    * h_win5, h_place5  : % victoires / % places sur 5 dernières (si dispo)
    * h_win_career      : % victoires carrière (si dispo)
    * h_place_career    : % places carrière (si dispo)
- Sortie CSV rétro-compatible + colonnes additionnelles :
    num,j_rate,e_rate,h_win5,h_place5,h_win_career,h_place_career

Usage
  python fetch_je_stats_v4.py --h5 data/R1C3_H-5.json --out probs/R1C3_je.csv --cache --ttl-seconds 86400
"""

import argparse
import csv
import html
import json
import os
import re
import time
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import urllib.parse
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119 Safari/537.36"
TIMEOUT = 10.0
DELAY = 0.6
RETRIES = 2
TTL_DEFAULT = 24*3600  # 24h

PCT_RE = re.compile(r"(?:\b|>)(\d{1,2}(?:[.,]\d{1,2})?)\s*%")
# Heuristiques pour trouver sections cheval
HORSE_HINTS = [
    r"5\s*derni[eè]res", r"derni[eè]res\s+courses",
    r"r[eé]ussite", r"victoires?", r"places?",
    r"carri[eè]re", r"statistiques"
]

@dataclass
class FetchConf:
    timeout: float = TIMEOUT
    delay_between_requests: float = DELAY
    user_agent: str = UA
    use_cache: bool = False
    cache_dir: Path = Path.home() / ".cache" / "hippiques" / "geny"
    ttl_seconds: int = TTL_DEFAULT
    retries: int = RETRIES

def _hash_url(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()

def cache_read(url: str, conf: FetchConf) -> Optional[str]:
    if not conf.use_cache:
        return None
    conf.cache_dir.mkdir(parents=True, exist_ok=True)
    fp = conf.cache_dir / f"{_hash_url(url)}.html"
    if not fp.exists():
        return None
    age = time.time() - fp.stat().st_mtime
    if age > conf.ttl_seconds:
        try: fp.unlink()
        except OSError: pass
        return None
    try:
        return fp.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

def cache_write(url: str, text: str, conf: FetchConf):
    if not conf.use_cache or not text:
        return
    conf.cache_dir.mkdir(parents=True, exist_ok=True)
    fp = conf.cache_dir / f"{_hash_url(url)}.html"
    try:
        fp.write_text(text, encoding="utf-8")
    except Exception:
        pass

def http_get(url: str, conf: FetchConf) -> Optional[str]:
    if not url:
        return None
    cached = cache_read(url, conf)
    if cached is not None:
        return cached
    last_err = None
    for attempt in range(1, conf.retries+1):
        req = urllib.request.Request(url, headers={"User-Agent": conf.user_agent, "Accept-Language": "fr,en;q=0.8"})
        try:
            with urllib.request.urlopen(req, timeout=conf.timeout) as r:
                raw = r.read()
            try:
                text = raw.decode("utf-8", errors="ignore")
            except Exception:
                text = raw.decode("latin-1", errors="ignore")
            cache_write(url, text, conf)
            return text
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(0.4 * attempt)
            continue
    return None

def first_percentage(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    for m in PCT_RE.finditer(text):
        try:
            val = float(m.group(1).replace(",", "."))
            if 0.0 <= val <= 100.0:
                return val
        except Exception:
            continue
    return None

def slugify_name_for_geny(name: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", name).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s

def discover_horse_url_by_name(name: str, conf: FetchConf) -> Optional[str]:
    base = "https://www.geny.com"
    slug = slugify_name_for_geny(name)
    # 1) tentative directe
    url1 = f"{base}/cheval/{slug}"
    html1 = http_get(url1, conf)
    if html1 and ("Cheval" in html1 or "/jockey/" in html1 or "/entra" in html1):
        return url1
    time.sleep(conf.delay_between_requests)
    # 2) recherche
    q = urllib.parse.quote(name)
    url2 = f"{base}/recherche?search={q}"
    html2 = http_get(url2, conf)
    if not html2:
        return None
    for m in re.finditer(r'href="(/cheval/[^"]+)"', html2, re.IGNORECASE):
        href = html.unescape(m.group(1))
        if "/cheval/" in href and "search=" not in href:
            return urllib.parse.urljoin(base, href)
    return None

def extract_links_from_horse_page(html_text: str) -> Tuple[Optional[str], Optional[str]]:
    if not html_text:
        return None, None
    base = "https://www.geny.com"
    j_url = None; e_url = None
    for m in re.finditer(r'href="(/jockey/[^"]+)"', html_text, re.IGNORECASE):
        j_url = urllib.parse.urljoin(base, html.unescape(m.group(1))); break
    for m in re.finditer(r'href="(/entra[îi]neur/[^"]+)"', html_text, re.IGNORECASE):
        e_url = urllib.parse.urljoin(base, html.unescape(m.group(1))); break
    return j_url, e_url

def extract_rate_from_profile(url: Optional[str], conf: FetchConf) -> Optional[float]:
    if not url:
        return None
    html_txt = http_get(url, conf)
    if not html_txt:
        return None
    return first_percentage(html_txt)

def parse_horse_percentages(html_text: Optional[str]) -> Dict[str, Optional[float]]:
    """
    Essaie de déduire quelques % utiles de la page cheval.
    Heuristiques tolérantes : on cherche les bloc '5 dernières', 'carrière', 'victoires', 'places'.
    Si plusieurs % sont trouvés, on prend le premier par rubrique.
    """
    out = {"h_win5": None, "h_place5": None, "h_win_career": None, "h_place_career": None}
    if not html_text:
        return out
    text = html_text
    # Simplifier pour recherche insensible
    low = text.lower()

    # Heuristiques de sections : 5 dernières
    # On récupère jusqu'à 300 caractères autour du mot-clef et on cherche 2 pourcentages
    for pat in HORSE_HINTS:
        for m in re.finditer(pat, low, re.IGNORECASE):
            start = max(0, m.start()-200)
            end = min(len(text), m.end()+300)
            window = text[start:end]

            # Si on est dans une section "5 dernières"
            if re.search(r"5\s*derni[eè]res|derni[eè]res\s+courses", window, re.IGNORECASE):
                # Chercher 2 pourcentages dans la fenêtre : souvent place puis victoire ou inversement
                pcts = [float(x.replace(',', '.')) for x in re.findall(r'(\d{1,2}(?:[.,]\d{1,2})?)\s*%', window)]
                if pcts:
                    # on essaie d'assigner le plus grand aux places, l'autre aux victoires (heuristique)
                    if len(pcts) == 1:
                        # On ne sait pas s'il s'agit de places ou victoires ; mettons-le en place5
                        out["h_place5"] = pcts[0]
                    else:
                        a, b = sorted(pcts, reverse=True)[:2]
                        out["h_place5"], out["h_win5"] = a, b
            # Carrière (victoires/places)
            if re.search(r"carri[eè]re|statistiques", window, re.IGNORECASE):
                pcts = [float(x.replace(',', '.')) for x in re.findall(r'(\d{1,2}(?:[.,]\d{1,2})?)\s*%', window)]
                if pcts:
                    # Heuristique : le plus grand ~ places, le plus petit ~ victoires
                    if len(pcts) == 1:
                        if out["h_place_career"] is None:
                            out["h_place_career"] = pcts[0]
                    else:
                        a, b = sorted(pcts, reverse=True)[:2]
                        if out["h_place_career"] is None:
                            out["h_place_career"] = a
                        if out["h_win_career"] is None:
                            out["h_win_career"] = b
    return out

def load_json(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def ensure_parent(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)

def main():
    ap = argparse.ArgumentParser(description="Génère je_stats.csv (+cheval stats) via Geny (cheval → jockey/entraîneur) avec cache.")
    ap.add_argument("--h5", required=True, help="Fichier JSON H-5")
    ap.add_argument("--out", default=None, help="Fichier CSV sortie (défaut: <h5_stem>_je.csv)")
    ap.add_argument("--timeout", type=float, default=TIMEOUT)
    ap.add_argument("--delay", type=float, default=DELAY)
    ap.add_argument("--retries", type=int, default=RETRIES)
    ap.add_argument("--cache", action="store_true")
    ap.add_argument("--cache-dir", default=None)
    ap.add_argument("--ttl-seconds", type=int, default=TTL_DEFAULT)
    ap.add_argument("--neutral-on-fail", action="store_true")
    args = ap.parse_args()

    conf = FetchConf(
        timeout=args.timeout,
        delay_between_requests=args.delay,
        user_agent=UA,
        use_cache=bool(args.cache),
        cache_dir=(Path(args.cache_dir) if args.cache_dir else Path.home()/".cache"/"hippiques"/"geny"),
        ttl_seconds=int(args.ttl_seconds),
        retries=int(args.retries),
    )

    data = load_json(args.h5)
    runners = data.get("runners", [])
    h5p = Path(args.h5)
    out = Path(args.out) if args.out else (h5p.parent / f"{h5p.stem}_je.csv")
    ensure_parent(out)

    rows = []
    for r in runners:
        num = str(r.get("num"))
        name = (r.get("name") or "").strip()
        j_rate = e_rate = None
        h_win5 = h_place5 = h_win_career = h_place_career = None

        if name:
            # 1) page cheval
            h_url = discover_horse_url_by_name(name, conf)
            time.sleep(conf.delay_between_requests)

            if h_url:
                h_html = http_get(h_url, conf)
                time.sleep(conf.delay_between_requests)
                # 2) profils J/E
                j_url, e_url = extract_links_from_horse_page(h_html or "")
                j_rate = extract_rate_from_profile(j_url, conf) if j_url else None
                time.sleep(conf.delay_between_requests)
                e_rate = extract_rate_from_profile(e_url, conf) if e_url else None
                time.sleep(conf.delay_between_requests)
                # 3) stats cheval
                hs = parse_horse_percentages(h_html or "")
                h_win5, h_place5 = hs.get("h_win5"), hs.get("h_place5")
                h_win_career, h_place_career = hs.get("h_win_career"), hs.get("h_place_career")

        def _fmt(x):
            return f"{float(x):.2f}" if isinstance(x, (int,float)) else ""

        rows.append({
            "num": num,
            "j_rate": _fmt(j_rate),
            "e_rate": _fmt(e_rate),
            "h_win5": _fmt(h_win5),
            "h_place5": _fmt(h_place5),
            "h_win_career": _fmt(h_win_career),
            "h_place_career": _fmt(h_place_career),
        })

    # écrire CSV
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "num","j_rate","e_rate","h_win5","h_place5","h_win_career","h_place_career"
        ])
        w.writeheader()
        for row in rows:
            w.writerow(row)

    print(f"[OK] je_stats.csv écrit → {out}")

if __name__ == "__main__":
    main()
