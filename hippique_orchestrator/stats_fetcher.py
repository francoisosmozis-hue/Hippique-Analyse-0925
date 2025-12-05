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

    runners = data.get("runners", [])
    rows = []
    successful_fetches = 0
    for r in runners:
        num = str(r.get("num") or r.get("id"))
        name = (r.get("name") or "").strip()
        j_rate = e_rate = h_win5 = h_place5 = h_win_career = h_place_career = None
        if name:
