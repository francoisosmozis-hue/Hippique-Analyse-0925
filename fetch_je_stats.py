"""Helpers to materialise jockey/entraineur statistics from a snapshot."""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import logging
import re
import time
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeAlias
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

# --- Constants ---
GENY_BASE_URL = "https://www.geny.com"
DEFAULT_TIMEOUT = 15
TIMEOUT = DEFAULT_TIMEOUT
DELAY = 1.0
RETRIES = 3
TTL_DEFAULT = 3600
DEFAULT_HEADERS = {
    "User-Agent": "Hippique-Analyse/1.0 (contact: ops@hippique.local)",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
}
UA = DEFAULT_HEADERS["User-Agent"]
ResultDict: TypeAlias = dict[str, str | None]

# --- Original Functions (Kept for compatibility) ---

@dataclass
class FetchConf:
    timeout: float
    delay_between_requests: float
    user_agent: str
    use_cache: bool
    cache_dir: Path
    ttl_seconds: int
    retries: int

def load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

def http_get(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    headers: Mapping[str, str] | None = None,
) -> str:
    caller = session.get if session else requests.get
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    try:
        response = caller(url, headers=merged_headers, timeout=timeout)
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        raise RuntimeError(f"HTTP request failed for {url}") from exc

@lru_cache(maxsize=512)
def _normalise_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    cleaned = "".join(char for char in decomposed if char.isalnum())
    return cleaned.lower()

def discover_horse_url_by_name(
    name: str,
    *,
    get: Callable[[str], str] | None = None,
) -> str | None:
    if not name or not name.strip():
        return None
    fetch = get or http_get
    query = quote_plus(name.strip())
    search_url = f"{GENY_BASE_URL}/recherche?query={query}"
    try:
        html = fetch(search_url)
    except RuntimeError:
        LOGGER.warning("Failed to fetch Geny search results for %s", name)
        return None
    soup = BeautifulSoup(html, "html.parser")
    target_norm = _normalise_text(name)
    best_url: str | None = None
    best_score = 0.0
    for link in soup.select("a[href]"):
        href = link.get("href")
        if not href or "/chev" not in href:
            continue
        candidate_text = link.get_text(" ", strip=True)
        if not candidate_text:
            continue
        candidate_norm = _normalise_text(candidate_text)
        if candidate_norm == target_norm:
            return urljoin(GENY_BASE_URL, href)
        score = difflib.SequenceMatcher(None, target_norm, candidate_norm).ratio()
        if score > best_score:
            best_score = score
            best_url = urljoin(GENY_BASE_URL, href)
    return best_url

def extract_links_from_horse_page(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    links: dict[str, str] = {}
    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        if not href:
            continue
        absolute = urljoin(GENY_BASE_URL, href)
        text = anchor.get_text(" ", strip=True).lower()
        href_lower = absolute.lower()
        if "jockey" in text or "driver" in text or re.search(r"/jockey|/driver", href_lower):
            links.setdefault("jockey", absolute)
        if "entraine" in text or "entraîne" in text or "trainer" in text or "coach" in text or re.search(r"/entraine|/entraineur|/trainer|/coach", href_lower):
            links.setdefault("trainer", absolute)
    return links

_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_RATIO_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_VICTORY_RE = re.compile(r"victoires?\s*[:=]\s*(\d+)", re.IGNORECASE)

def _parse_percentage(text: str) -> float | None:
    if not text: return None
    percent = _PERCENT_RE.search(text)
    if percent: return float(percent.group(1).replace(",", "."))
    ratio = _RATIO_RE.search(text)
    if ratio:
        numerator, denominator = int(ratio.group(1)), int(ratio.group(2))
        if denominator: return round(100.0 * numerator / denominator, 2)
    victory = _VICTORY_RE.search(text)
    if victory: return float(victory.group(1))
    number = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not number: return None
    try: value = float(number.group(1).replace(",", "."))
    except ValueError: return None
    if 0.0 <= value <= 1.0: return round(value * 100, 2)
    if 0.0 <= value <= 100.0: return value
    return None

def extract_rate_from_profile(html: str) -> float | None:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup.find_all(["span", "div", "td", "th", "p", "li", "strong", "b"]):
        text = element.get_text(" ", strip=True)
        rate = _parse_percentage(text)
        if rate is not None: return rate
    return _parse_percentage(soup.get_text(" ", strip=True))

def parse_horse_percentages(horse_name: str, *, get: Callable[[str], str] | None = None) -> tuple[float | None, float | None]:
    fetch = get or http_get
    horse_url = discover_horse_url_by_name(horse_name, get=fetch)
    if not horse_url: return None, None
    try: horse_html = fetch(horse_url)
    except RuntimeError:
        LOGGER.warning("Failed to fetch horse page %s", horse_url)
        return None, None
    links = extract_links_from_horse_page(horse_html)
    jockey_rate = trainer_rate = None
    if jockey_link := links.get("jockey"):
        try: jockey_rate = extract_rate_from_profile(fetch(jockey_link))
        except RuntimeError: LOGGER.warning("Failed to fetch jockey profile %s", jockey_link)
    if trainer_link := links.get("trainer"):
        try: trainer_rate = extract_rate_from_profile(fetch(trainer_link))
        except RuntimeError: LOGGER.warning("Failed to fetch trainer profile %s", trainer_link)
    return jockey_rate, trainer_rate

def collect_stats(
    h5: str, out: str | None = None, *, timeout: float = TIMEOUT, delay: float = DELAY, retries: int = RETRIES,
    cache: bool = False, cache_dir: str | None = None, ttl_seconds: int = TTL_DEFAULT, neutral_on_fail: bool = False
) -> str:
    conf = FetchConf(timeout=timeout, delay_between_requests=delay, user_agent=UA, use_cache=bool(cache), cache_dir=(Path(cache_dir) if cache_dir else Path.home()/'.cache'/'hippiques'/'geny'), ttl_seconds=int(ttl_seconds), retries=int(retries))
    def fetcher(url): return http_get(url, timeout=conf.timeout)
    data = load_json(h5)
    runners = data.get("runners", [])
    h5p = Path(h5)
    json_out_path = h5p.parent / "stats_je.json"
    ensure_parent(json_out_path)
    rows = []
    successful_fetches = 0
    for r in runners:
        num = str(r.get("num") or r.get("id"))
        name = (r.get("name") or "").strip()
        j_rate = e_rate = h_win5 = h_place5 = h_win_career = h_place_career = None
        if name:
            try:
                h_url = discover_horse_url_by_name(name, get=fetcher)
                time.sleep(conf.delay_between_requests)
                if h_url:
                    h_html = fetcher(h_url)
                    time.sleep(conf.delay_between_requests)
                    links = extract_links_from_horse_page(h_html or "")
                    j_url, e_url = links.get("jockey"), links.get("trainer")
                    if j_url:
                        j_rate = extract_rate_from_profile(fetcher(j_url))
                        time.sleep(conf.delay_between_requests)
                    if e_url:
                        e_rate = extract_rate_from_profile(fetcher(e_url))
                        time.sleep(conf.delay_between_requests)
                    if j_rate is not None or e_rate is not None:
                        successful_fetches += 1
            except Exception as e:
                LOGGER.warning(f"Could not fetch stats for horse '{name}': {e}")
        def _fmt(x): return f"{float(x):.2f}" if isinstance(x, (int, float)) else ""
        rows.append({"num": num, "j_rate": _fmt(j_rate), "e_rate": _fmt(e_rate), "h_win5": _fmt(h_win5), "h_place5": _fmt(h_place5), "h_win_career": _fmt(h_win_career), "h_place_career": _fmt(h_place_career)})
    coverage = (successful_fetches / len(runners) * 100) if runners else 0
    output_payload = {"coverage": coverage, "rows": rows}
    json_out_path.write_text(json.dumps(output_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    csv_out_path = Path(out) if out else (h5p.parent / f"{h5p.stem}_je.csv")
    ensure_parent(csv_out_path)
    with csv_out_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = ["num", "j_rate", "e_rate", "h_win5", "h_place5", "h_win_career", "h_place_career"]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows: w.writerow({k: v for k, v in row.items() if k in fieldnames})
    return str(json_out_path)

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
    out_csv = collect_stats(args.h5, args.out, timeout=args.timeout, delay=args.delay, retries=args.retries, cache=bool(args.cache), cache_dir=args.cache_dir, ttl_seconds=args.ttl_seconds, neutral_on_fail=bool(args.neutral_on_fail))
    print(f"[OK] je_stats.csv écrit → {out_csv}")

# --- New Robust Implementation ---

def enrich_from_snapshot(snapshot_path: str, out_dir: str, **kwargs) -> dict:
    """Build ``je_stats.csv`` file from ``snapshot_path``."""
    result: ResultDict = {"je_stats": None, "chronos": None}
    snapshot_file = Path(snapshot_path)
    try:
        raw_payload = json.loads(snapshot_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        LOGGER.warning("Snapshot %s does not exist", snapshot_file)
        return result
    except (OSError, json.JSONDecodeError):
        LOGGER.exception("Unable to load snapshot %s", snapshot_file)
        return result

    if not isinstance(raw_payload, Mapping):
        LOGGER.warning("Snapshot %s is not a JSON object", snapshot_file)
        payload: Mapping[str, Any] = {}
    else:
        payload = raw_payload

    runners_field = payload.get("runners")
    runners: list[Mapping[str, Any]] = []
    if isinstance(runners_field, list):
        for index, runner in enumerate(runners_field):
            if isinstance(runner, Mapping):
                runners.append(runner)
            else:
                LOGGER.warning("Runner entry %s in %s is not an object and will be ignored", index, snapshot_file)
    else:
        LOGGER.warning("Snapshot %s is missing a 'runners' array", snapshot_file)

    normalised = list(_normalise_runners(runners, snapshot_file))

    output_dir = Path(out_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        LOGGER.exception("Unable to create output directory %s", output_dir)
        return result

    je_path = output_dir / "je_stats.csv"
    try:
        header = ("num", "nom", "j_rate", "e_rate")
        _write_csv(je_path, normalised, header)
    except OSError:
        LOGGER.exception("Failed to write JE statistics CSV at %s", je_path)
    else:
        result["je_stats"] = str(je_path)

    # This module does not produce chronos, so we leave it as None
    return result

def _normalise_runners(runners: Iterable[Mapping[str, Any]], snapshot_file: Path) -> Iterable[dict[str, str]]:
    for index, runner in enumerate(runners):
        descriptor = _runner_descriptor(runner, index)
        yield {
            "num": _extract_value(runner, ("num", "number", "id"), snapshot_file, descriptor, "num"),
            "nom": _extract_value(runner, ("nom", "name", "horse", "label"), snapshot_file, descriptor, "nom"),
            "j_rate": _extract_value(runner, ("j_rate", "j_win", "jockey_rate"), snapshot_file, descriptor, "j_rate"),
            "e_rate": _extract_value(runner, ("e_rate", "e_win", "trainer_rate"), snapshot_file, descriptor, "e_rate"),
        }

def _runner_descriptor(runner: Mapping[str, Any], index: int) -> str:
    for key in ("num", "number", "id"):
        value = runner.get(key)
        if value not in (None, ""):
            return f"{key}={value}"
    return f"index {index}"

def _extract_value(
    runner: Mapping[str, Any], keys: Iterable[str], snapshot_file: Path, descriptor: str, label: str
) -> str:
    for key in keys:
        value = runner.get(key)
        if value not in (None, ""):
            return str(value)
    LOGGER.warning("Runner %s in %s is missing '%s'; using empty string", descriptor, snapshot_file, label)
    return ""

def _write_csv(path: Path, rows: Iterable[dict[str, str]], columns: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = list(columns)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(column, "") for column in header])

__all__ = ["collect_stats", "enrich_from_snapshot"]

if __name__ == "__main__":
    main()
