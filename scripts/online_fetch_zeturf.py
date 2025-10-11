"""Tools for fetching meetings from Zeturf and computing odds drifts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    Sequence,
    TypeVar,
)

try:
    import requests
except ModuleNotFoundError as exc:  # pragma: no cover - exercised via dedicated test
    raise RuntimeError(
        "The 'requests' package is required to fetch data from Zeturf. "
        "Install it with 'pip install requests' or switch to the urllib-based fallback implementation."
    ) from exc
import re

import yaml
from bs4 import BeautifulSoup

try:  # pragma: no cover - Python < 3.9 fallbacks are extremely rare
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - very defensive
    ZoneInfo = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

# ... (le reste du fichier jusqu'à la fin, avec toutes les corrections)

def fetch_from_pmu_api(date: str, reunion: int, course: int) -> Dict[str, Any]:
    """
    Fetches race data from the unofficial PMU Turfinfo API.
    """
    date_str = date.replace("-", "")
    base_url = f"https://offline.turfinfo.api.pmu.fr/rest/client/7/programme/{date_str}/R{reunion}/C{course}"

    try:
        partants_url = f"{base_url}/participants"
        partants_resp = _http_get_with_backoff(partants_url)
        partants_data = partants_resp.json()
        if not partants_data:
            logger.error(f"No data returned from PMU participants API for R{reunion}C{course}")
            return {}
    except Exception as e:
        logger.error(f"Failed to fetch PMU participants for R{reunion}C{course}: {e}")
        return {}

    runners = []
    for p in partants_data.get('participants', []):
        runners.append({
            "num": p.get('numero'),
            "name": p.get('nom'),
            "sexe": p.get('sexe'),
            "age": p.get('age'),
            "musique": p.get('musique'),
        })

    try:
        rapports_url = f"{base_url}/rapports/SIMPLE_PLACE"
        rapports_resp = _http_get_with_backoff(rapports_url)
        rapports_data = rapports_resp.json()
        if rapports_data:
            odds_map = {}
            for rapport in rapports_data.get('rapports', []):
                if rapport.get('typePari') == 'SIMPLE_PLACE':
                    for comb in rapport.get('combinaisons', []):
                        num = comb.get('combinaison')[0]
                        odds_map[str(num)] = comb.get('rapport')

            for runner in runners:
                if str(runner['num']) in odds_map:
                    runner['dernier_rapport'] = {'gagnant': odds_map[str(runner['num'])]}
                    runner['cote'] = odds_map[str(runner['num'])]

    except Exception as e:
        logger.warning(f"Failed to fetch PMU rapports for R{reunion}C{course}: {e}")

    return {
        "runners": runners,
        "hippodrome": partants_data.get('hippodrome', {}).get('libelleCourt'),
        "discipline": partants_data.get('discipline'),
        "partants": len(runners),
        "course_id": partants_data.get('id'),
        "reunion": f"R{reunion}",
        "course": f"C{course}",
        "date": date,
    }

def fetch_race_snapshot(
    reunion: str,
    course: str | None = None,
    phase: str = "H30",
    *,
    sources: Mapping[str, Any] | None = None,
    url: str | None = None,
    retries: int = 3,
    backoff: float = 1.5,
    initial_delay: float = 0.5,
) -> Dict[str, Any]:

    if sources and sources.get("provider") == "pmu":
        if not url:
            raise ValueError("URL is required for PMU provider")
        
        match = re.search(r"(R\d+C\d+)", url)
        if not match:
            raise ValueError("Cannot extract R/C from URL for PMU provider")
        
        rc_label = match.group(1)
        reunion_str, course_str = _derive_rc_parts(rc_label)
        
        today = dt.date.today().strftime("%Y-%m-%d")
        r_num = int(reunion_str.replace("R", ""))
        c_num = int(course_str.replace("C", ""))
        return fetch_from_pmu_api(today, r_num, c_num)

    # Zeturf/Geny logic (existing code)
    rc_from_first = _normalise_rc(reunion)
    if course is None and sources is not None and rc_from_first:
        return _fetch_race_snapshot_by_rc(
            rc_from_first,
            phase=phase,
            sources=sources,
            url=url,
            retries=retries,
            backoff=backoff,
            initial_delay=initial_delay,
        )

    if course is None:
        raise ValueError(
            "course label is required when reunion/course are provided separately"
        )

    reunion_label = _normalise_reunion_label(reunion)
    course_label = _normalise_course_label(course)
    rc = f"{reunion_label}{course_label}"

    config: Dict[str, Any]
    if isinstance(sources, MutableMapping):
        config = dict(sources)
    elif isinstance(sources, Mapping):
        config = dict(sources)
    else:
        config = {}

    rc_map_raw = (
        config.get("rc_map") if isinstance(config.get("rc_map"), Mapping) else None
    )
    rc_map: Dict[str, Any] = (
        {str(k): v for k, v in rc_map_raw.items()} if rc_map_raw else {}
    )

    entry = dict(rc_map.get(rc, {}))
    entry.setdefault("reunion", reunion_label)
    entry.setdefault("course", course_label)
    if url:
        entry["url"] = url

    rc_map[rc] = entry
    config["rc_map"] = rc_map

    snapshot = _fetch_race_snapshot_by_rc(
        rc,
        phase=phase,
        sources=config,
        url=url,
        retries=retries,
        backoff=backoff,
        initial_delay=initial_delay,
    )

    snapshot.setdefault("reunion", reunion_label)
    snapshot.setdefault("course", course_label)
    snapshot.setdefault("rc", rc)
    return snapshot

def write_snapshot_from_geny(course_id: str, phase: str, rc_dir: Path) -> None:
    logger.info("STUB: Writing dummy snapshots for %s in %s", course_id, rc_dir)
    rc_dir.mkdir(parents=True, exist_ok=True)

    runners = [
        {"id": "1", "num": "1", "name": "DUMMY 1", "odds": 5.0},
        {"id": "2", "num": "2", "name": "DUMMY 2", "odds": 6.0},
        {"id": "3", "num": "3", "name": "DUMMY 3", "odds": 7.0},
        {"id": "4", "num": "4", "name": "DUMMY 4", "odds": 8.0},
        {"id": "5", "num": "5", "name": "DUMMY 5", "odds": 9.0},
        {"id": "6", "num": "6", "name": "DUMMY 6", "odds": 10.0},
        {"id": "7", "num": "7", "name": "DUMMY 7", "odds": 11.0},
    ]

    # Create dummy H-30 file
    h30_file = rc_dir / "dummy_H-30.json"
    with open(h30_file, "w", encoding="utf-8") as f:
        json.dump({"id_course": course_id, "phase": "H-30", "runners": runners, "distance": 2100}, f)
    logger.info("STUB: Wrote dummy H-30 file to %s", h30_file)

    # Create dummy H-5 file
    h5_file = rc_dir / "dummy_H-5.json"
    with open(h5_file, "w", encoding="utf-8") as f:
        json.dump({"id_course": course_id, "phase": "H-5", "runners": runners, "distance": 2100}, f)
    logger.info("STUB: Wrote dummy H-5 file to %s", h5_file)



# ... (le reste du fichier)