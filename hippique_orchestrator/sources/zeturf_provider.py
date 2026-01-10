from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Sequence
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from hippique_orchestrator.sources_interfaces import SourceProvider
from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)

# Constants adapted from online_fetch_zeturf.py
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GPI/5.1; +https://example.local)",
    "Accept-Language": "fr-FR,fr;q=0.9",
}
DEFAULT_TIMEOUT = 12.0
_RC_COMBINED_RE = re.compile(r"R?\s*(\d+)\s*C\s*(\d+)", re.IGNORECASE)
_PARTANTS_RE = re.compile(r"(?:\b|\D)(\d{1,2})\s+partant(?:e?s?)?\b", re.IGNORECASE)
_DISCIPLINE_RE = re.compile(r"(trot|plat|obstacles?|mont[ée]|attelé)", re.IGNORECASE)
_MEETING_RE = re.compile(r'<span class="hippodrome[^>]*>([^<]+?)\s*-?\s*</span>', re.IGNORECASE)
_DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
_SUSPICIOUS_HTML_PATTERNS = (
    "too many requests", "captcha", "temporarily unavailable", "access denied",
    "service unavailable", "cloudflare",
)
_ZT_BASE_URL = "https://www.zeturf.fr"


class ZeturfProvider(SourceProvider):
    """
    Provides racing data from ZEturf (primarily race snapshots, used as fallback).
    """

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)
        
    async def fetch_programme(
        self, url: str, correlation_id: str | None = None, trace_id: str | None = None
    ) -> list[dict[str, Any]]:
        logger.info(
            "ZeturfProvider does not implement programme fetching. Returning empty list.",
            extra={"url": url, "correlation_id": correlation_id},
        )
        return []

    async def fetch_snapshot(
        self,
        race_url: str,
        *,
        phase: str = "H30",
        date: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "Début du scraping des détails de course depuis ZEturf (fallback).",
            extra={"url": race_url, "phase": phase, "correlation_id": correlation_id},
        )
        
        # Zeturf's fetch_race_snapshot_full is synchronous, so run in threadpool
        loop = asyncio.get_running_loop()
        snapshot_data = await loop.run_in_executor(
            None,
            self._fetch_race_snapshot_sync,
            race_url,
            phase,
        )
        
        # Add source and timestamp to the snapshot
        snapshot_data["source"] = "Zeturf"
        snapshot_data["ts_fetch"] = datetime.now().isoformat()

        return snapshot_data

    def _fetch_race_snapshot_sync(self, race_url: str, phase: str) -> dict[str, Any]:
        """
        Synchronous internal method to fetch and normalize ZEturf snapshot.
        Adapted from online_fetch_zeturf.py
        """
        snapshot_mode = "H-5" if phase.upper().replace("-", "") == "H5" else "H-30"
        
        try:
            raw_snapshot = self._double_extract(race_url, snapshot=snapshot_mode)
            # Normalize the result
            normalized_snapshot = self._normalise_snapshot_result(
                raw_snapshot,
                reunion_hint=None, # These will be extracted from the raw_snapshot or URL
                course_hint=None,
                phase_norm=phase,
            )
            return normalized_snapshot
        except Exception as e:
            logger.error(f"Failed to fetch ZEturf snapshot for {race_url}: {e}", exc_info=True)
            return {}

    def _http_get_sync(self, url: str) -> str:
        """Synchronous HTTP GET, raises on suspicious payloads."""
        resp = self._session.get(url, timeout=DEFAULT_TIMEOUT)
        if resp.status_code in (403, 429) or 500 <= resp.status_code < 600:
            raise RuntimeError(f"HTTP {resp.status_code} returned by {url}")
        text = resp.text
        if self._looks_like_suspicious_html(text):
            raise RuntimeError(f"Payload suspect reçu de {url}")
        if not text or len(text) < 512:
            raise RuntimeError(f"Payload trop court reçu de {url}")
        return text

    def _looks_like_suspicious_html(self, payload: Any) -> bool:
        if isinstance(payload, bytes):
            try:
                payload = payload.decode("utf-8", errors="ignore")
            except Exception:
                payload = ""
        if not isinstance(payload, str):
            payload = str(payload or "")
        if not payload:
            return True

        lowered = payload.lower()
        if "<html" not in lowered:
            return False
        if any(marker in lowered for marker in _SUSPICIOUS_HTML_PATTERNS):
            return True
        stripped = lowered.strip()
        if stripped.startswith("<html") and len(stripped) < 512:
            return True
        return False

    def _double_extract(self, url: str, *, snapshot: str) -> dict[str, Any]:
        """Return parsed data using the official parser with a regex fallback."""
        html = self._http_get_sync(url)
        data: dict[str, Any] | None = None
        fallback_used = False
        fallback_data: dict[str, Any] | None = None

        def _ensure_fallback() -> dict[str, Any]:
            nonlocal fallback_data
            if fallback_data is None:
                fallback_data = self._fallback_parse_html(html, url)
            return fallback_data

        logger.debug("[ZEturf] Skipping primary parser due to recursion bug, using fallback.")
        
        # Directly use fallback as in online_fetch_zeturf's simplified logic
        fallback = _ensure_fallback()
        if fallback.get("runners"):
            data = {**(data or {}), **fallback}
            fallback_used = True
        elif data is None:
            data = fallback
            fallback_used = True

        if not data:
            logger.warning(
                "[ZEturf] Aucune donnée exploitable extraite (url=%s, snapshot=%s)",
                url,
                snapshot,
            )
            data = {"runners": []}
            fallback_used = True

        missing_keys: list[str] = []
        for key in ("meeting", "hippodrome", "discipline", "partants"):
            value = data.get(key)
            if value in (None, "", 0):
                missing_keys.append(key)

        if missing_keys:
            fallback = _ensure_fallback()
            for key in missing_keys:
                candidate = fallback.get(key)
                if candidate in (None, "", 0) and key == "hippodrome":
                    candidate = fallback.get("meeting")
                if candidate in (None, "", 0) and key == "meeting":
                    candidate = fallback.get("hippodrome")
                if candidate not in (None, "", 0):
                    data[key] = candidate
                    fallback_used = True

        for key in ("meeting", "discipline", "partants"):
            if data.get(key) in (None, "", 0):
                logger.warning(
                    "[ZEturf] Champ clé manquant: %s (url=%s, snapshot=%s)",
                    key,
                    url,
                    snapshot,
                )
        if not data.get("runners"):
            logger.warning(
                "[ZEturf] Aucun partant détecté (url=%s, snapshot=%s) — retournera une liste vide",
                url,
                snapshot,
            )
            data["runners"] = []
        data.setdefault("source_url", url)
        if fallback_used:
            logger.warning(
                "[ZEturf] Extraction fallback utilisée pour %s (snapshot=%s)",
                url,
                snapshot,
            )
        return data

    def _fallback_parse_html(self, html: Any, url: str) -> dict[str, Any]:
        """Extract a minimal snapshot payload using BeautifulSoup (fallback)."""
        if isinstance(html, bytes):
            try:
                html = html.decode("utf-8", errors="ignore")
            except Exception:
                html = ""
        if not isinstance(html, str):
            html = str(html or "")

        soup = BeautifulSoup(html, "lxml")

        def _clean_text(
            value: str | None, *, lowercase: bool = False, strip_accents: bool = False
        ) -> str | None:
            if value in (None, ""):
                return None
            text = unicodedata.normalize("NFKC", str(value))
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                return None
            if strip_accents:
                text = "".join(
                    ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
                )
            if lowercase:
                text = text.lower()
            return text

        runners: list[dict[str, Any]] = []

        # Find the main table of runners
        table = soup.find("table", class_="table-runners")
        if table:
            tbody = table.find("tbody")
            rows = tbody.find_all("tr") if tbody else table.find_all("tr")
            for row in rows:
                runner_data = {}
                num_cell = row.find("td", class_="numero")
                if num_cell:
                    runner_data["num"] = _clean_text(num_cell.text)

                name_cell = row.find("td", class_="cheval")
                if name_cell:
                    name_anchor = name_cell.find("a", class_="horse-name")
                    if name_anchor:
                        runner_data["name"] = _clean_text(name_anchor.get("title"))

                odds_cell = row.find("td", class_="cotes")
                if odds_cell:
                    odds_span = odds_cell.find("span", class_="cote")
                    if odds_span:
                        runner_data["cote"] = _clean_text(odds_span.text)

                cotes_infos_script = soup.find("script", string=re.compile("cotesInfos"))
                if cotes_infos_script:
                    cotes_infos_str = re.search(r'cotesInfos: (\{.*\})', cotes_infos_script.string)
                    if cotes_infos_str:
                        try:
                            cotes_infos = json.loads(cotes_infos_str.group(1))
                            runner_num_key = runner_data.get("num")
                            if runner_num_key and runner_num_key in cotes_infos:
                                odds_data = cotes_infos[runner_num_key].get("odds", {})
                                if odds_data.get("SG"):
                                    runner_data["cote"] = odds_data["SG"]
                                if odds_data.get("SPMin") and odds_data.get("SPMax"):
                                    runner_data["odds_place"] = (
                                        odds_data["SPMin"] + odds_data["SPMax"]
                                    ) / 2
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to decode cotesInfos script for {url}")

                if runner_data:
                    runners.append(runner_data)

        partants: int | None = None
        partants_match = _PARTANTS_RE.search(html)
        if partants_match:
            try:
                partants = int(partants_match.group(1))
            except Exception:
                partants = None

        discipline: str | None = None
        infos_paragraph_match = re.search(
            r'<p class="infos">\s*(Attelé|Plat|Monté|Trot|Obstacles?)\s*-', html, re.IGNORECASE
        )
        if infos_paragraph_match:
            discipline = _clean_text(infos_paragraph_match.group(1), lowercase=True, strip_accents=False)
        else:
            discipline_match = _DISCIPLINE_RE.search(html)
            if discipline_match:
                discipline = _clean_text(discipline_match.group(1), lowercase=True, strip_accents=False)

        meeting: str | None = None
        meeting_match = _MEETING_RE.search(html)
        if meeting_match:
            meeting = _clean_text(meeting_match.group(1))

        date: str | None = None
        date_match = _DATE_RE.search(html)
        if date_match:
            date = _clean_text(date_match.group(1))

        return {
            "meeting": meeting,
            "hippodrome": meeting,
            "date": date,
            "runners": runners,
            "partants": partants,
            "discipline": discipline,
        }

    def _normalise_snapshot_result(
        self,
        raw_snapshot: Mapping[str, Any] | None,
        *,
        reunion_hint: str | None, # These will be derived from raw_snapshot
        course_hint: str | None,  # These will be derived from raw_snapshot
        phase_norm: str,
        sources_config: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any]
        if isinstance(raw_snapshot, Mapping):
            result = dict(raw_snapshot)
        else:
            result = {}

        if "market" not in result:
            result["market"] = {}

        runners_raw = result.get("runners")
        runners: list[dict[str, Any]] = []
        if isinstance(runners_raw, Iterable) and not isinstance(runners_raw, (str, bytes)):
            for entry in runners_raw:
                if isinstance(entry, Mapping):
                    runners.append(self._coerce_runner_entry(entry))
        result["runners"] = runners

        existing_meta = result.get("meta") if isinstance(result.get("meta"), Mapping) else {}
        meta: dict[str, Any] = dict(existing_meta) if isinstance(existing_meta, Mapping) else {}

        def _clean_str(value: Any) -> str | None:
            if value in (None, ""):
                return None
            return str(value).strip()

        # Derive reunion and course from the source_url if not available in snapshot data
        rc_match = re.search(r"/(R\d+C\d+)(?:-|$)", raw_snapshot.get("source_url", ""), re.IGNORECASE)
        reunion_from_url = rc_match.group(1)[:rc_match.group(1).find('C')] if rc_match else None
        course_from_url = rc_match.group(1)[rc_match.group(1).find('C'):] if rc_match else None

        reunion_meta = (_clean_str(meta.get("reunion")) or reunion_hint or _clean_str(result.get("reunion")) or reunion_from_url)
        course_meta = (_clean_str(meta.get("course")) or course_hint or _clean_str(result.get("course")) or course_from_url)
        date_meta = _clean_str(meta.get("date")) or _clean_str(result.get("date"))
        hippo_meta = _clean_str(
            meta.get("hippodrome")
            or meta.get("meeting")
            or result.get("hippodrome")
            or result.get("meeting")
        )
        discipline_meta = _clean_str(meta.get("discipline") or result.get("discipline"))

        meta.update(
            {
                "date": date_meta,
                "hippodrome": hippo_meta,
                "discipline": discipline_meta,
                "reunion": reunion_meta,
                "course": course_meta,
                "phase": phase_norm,
            }
        )
        if hippo_meta and "meeting" not in meta:
            meta["meeting"] = hippo_meta

        result["meta"] = meta

        if reunion_meta:
            result["reunion"] = reunion_meta
            result["r_label"] = reunion_meta
        if course_meta:
            result["course"] = course_meta
            result["c_label"] = course_meta
        if hippo_meta:
            result.setdefault("hippodrome", hippo_meta)
            result.setdefault("meeting", hippo_meta)

        result["phase"] = phase_norm

        rc_value = result.get("rc")
        if not rc_value and reunion_meta and course_meta:
            rc_value = f"{reunion_meta}{course_meta}"
            result["rc"] = rc_value

        partants_candidates = [
            result.get("partants_count"),
            result.get("partants"),
            meta.get("partants"),
            existing_meta.get("partants") if isinstance(existing_meta, Mapping) else None,
        ]

        partants_count = None
        for candidate in partants_candidates:
            value = self._coerce_partants_int(candidate)
            if value is not None:
                partants_count = value
                break

        if partants_count is None and runners:
            partants_count = len(runners)

        result["partants_count"] = partants_count
        result["partants"] = partants_count

        # For Zeturf, we don't merge H30 odds for H5 here. This is handled by the pipeline logic.

        market_block = result.get("market") if isinstance(result.get("market"), Mapping) else {}
        market: dict[str, Any] = dict(market_block) if isinstance(market_block, Mapping) else {}
        slots_hint = (
            market.get("slots_place")
            or meta.get("slots_place")
            or meta.get("paying_places")
            or result.get("slots_place")
            or meta.get("places")
        )

        slots = self._parse_slots_hint(slots_hint, default=market.get("slots_place", 3))
        if slots:
            market["slots_place"] = slots

        overround_win = self._estimate_overround_from_runners(runners, use_place=False)
        overround_place = self._estimate_overround_from_runners(runners, use_place=True)
        if overround_win is not None:
            market["overround_win"] = overround_win
            market["overround"] = overround_win
        if overround_place is not None:
            market["overround_place"] = overround_place
            market.setdefault("overround", overround_place)

        if market:
            result["market"] = market
            if market.get("overround") is not None:
                result.setdefault("overround", market.get("overround"))
            meta.setdefault("overround_win", market.get("overround_win"))
            meta.setdefault("overround_place", market.get("overround_place"))

        return result

    def _coerce_runner_entry(self, entry: Mapping[str, Any]) -> dict[str, Any] | None:
        """Normalise a runner payload into the structure expected downstream."""
        # Adapted from online_fetch_zeturf.py
        if not isinstance(entry, Mapping):
            return None

        identifiers = (
            entry.get("num"),
            entry.get("number"),
            entry.get("id"),
            entry.get("runner_id"),
        )
        number: str | None = None
        for candidate in identifiers:
            if candidate in (None, ""):
                continue
            number = str(candidate).strip()
            if number:
                break
        if not number:
            return None

        name_raw = entry.get("name") or entry.get("horse") or entry.get("label") or entry.get("runner")
        name = str(name_raw).strip() if name_raw not in (None, "") else number

        runner: dict[str, Any] = {"num": number, "name": name}

        def _coerce_metadata_value(value: Any) -> Any:
            if value in (None, ""):
                return None
            if isinstance(value, (str, int, float, bool)):
                return value
            if isinstance(value, Mapping):
                for key in ("name", "label", "value", "text"):
                    candidate = value.get(key)
                    if candidate not in (None, ""):
                        return candidate
                return None
            return None

        def _coerce_float(value: Any) -> float | None:
            if value in (None, ""):
                return None
            try:
                return float(str(value).replace(",", "."))
            except (TypeError, ValueError):
                return None

        for odds_key in ("cote", "odds", "odd", "cote_dec", "price"):
            odds_candidate = entry.get(odds_key)
            if isinstance(odds_candidate, Mapping):
                gagnant_val = _coerce_float(odds_candidate.get("gagnant"))
                if gagnant_val is not None:
                    runner.setdefault("odds_win", gagnant_val)
                    break
            odds_val = _coerce_float(odds_candidate)
            if odds_val is not None:
                runner.setdefault("odds_win", odds_val)
                break

        for place_key in ("odds_place", "place_odds", "placeOdds", "place", "cote_place"):
            place_val = _coerce_float(entry.get(place_key))
            if place_val is not None:
                runner.setdefault("odds_place", place_val)
                break

        for prob_key in ("p", "probability", "p_imp", "p_imp_h5", "p_true"):
            prob_val = _coerce_float(entry.get(prob_key))
            if prob_val is not None:
                runner.setdefault("p", prob_val)
                break

        for extra_key in ("id", "runner_id", "number"):
            extra_val = entry.get(extra_key)
            if extra_val not in (None, "", number):
                runner.setdefault("id", str(extra_val).strip())
                break

        if "odds_win" not in runner and entry.get("odds") not in (None, ""):
            odds_val = entry.get("odds")
            if not isinstance(odds_val, Mapping):
                coerced_odds = _coerce_float(odds_val)
                if coerced_odds is not None:
                    runner["odds_win"] = coerced_odds

        if "odds_place" not in runner:
            odds_block = entry.get("odds") if isinstance(entry.get("odds"), Mapping) else None
            if isinstance(odds_block, Mapping):
                place_val = _coerce_float(
                    odds_block.get("place")
                    or odds_block.get("place_odds")
                    or odds_block.get("placeOdds")
                )
                if place_val is not None:
                    runner["odds_place"] = place_val

        if "odds_place" not in runner:
            market_block = entry.get("market") if isinstance(entry.get("market"), Mapping) else None
            if isinstance(market_block, Mapping):
                place_market = market_block.get(number) or market_block.get(str(number))
                place_val = _coerce_float(place_market)
                if place_val is not None:
                    runner["odds_place"] = place_val
        
        # Ensure consistency in odds keys
        if "cote" in runner and "odds_win" not in runner:
            runner["odds_win"] = runner["cote"]
        if "odds_win" in runner and "cote" not in runner:
            runner["cote"] = runner["odds_win"]

        handled_keys = {
            "num", "number", "name", "horse", "label", "runner", "cote", "odds", "odd", 
            "cote_dec", "price", "odds_place", "place_odds", "placeOdds", "place", 
            "cote_place", "odds_place_h30", "odds_win_h30", "odds_win", "p", 
            "probability", "p_imp", "p_imp_h5", "p_true", "id", "runner_id", "market",
        }

        for key, value in entry.items():
            if key in handled_keys or key in runner:
                continue
            coerced = _coerce_metadata_value(value)
            if coerced is not None:
                runner[key] = coerced

        return runner

    def _coerce_partants_int(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, list):
            return len(value) if value else None
        if isinstance(value, (int, float)):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        if isinstance(value, str):
            match = re.search(r"\d+", value)
            if match:
                try:
                    return int(match.group(0))
                except ValueError:
                    return None
        return None

    def _estimate_overround_from_runners(
        self,
        runners: Sequence[Mapping[str, Any]],
        *,
        use_place: bool,
    ) -> float | None:
        total = 0.0
        count = 0
        for runner in runners or []:
            if not isinstance(runner, Mapping):
                continue
            if use_place:
                value = self._lookup_runner_value(
                    runner,
                    ("odds_place", "place_odds", "cote_place", "rapport_place"),
                )
                if value is None:
                    value = self._lookup_runner_value(
                        runner,
                        ("odds_win", "odds", "cote", "rapport_gagnant"),
                    )
            else:
                value = self._lookup_runner_value(
                    runner,
                    ("odds_win", "odds", "cote", "rapport_gagnant"),
                )
            if value is None:
                continue
            total += 1.0 / value
            count += 1
        if count == 0:
            return None
        return round(total, 4)

    def _lookup_runner_value(
        self,
        runner: Mapping[str, Any],
        keys: Sequence[str],
    ) -> float | None:
        for key in keys:
            candidate = runner.get(key)
            if candidate in (None, ""):
                continue
            normalized = self._normalize_decimal(candidate)
            if normalized is not None:
                return normalized
        return None

    def _normalize_decimal(self, value: Any) -> float | None:
        if isinstance(value, str):
            value = value.replace(",", ".")
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number <= 0.0:
            return None
        return number

    def _parse_slots_hint(self, *values: Any, default: int = 3) -> int:
        for value in values:
            if value in (None, ""):
                continue
            if isinstance(value, int):
                return value if value > 0 else default
            if isinstance(value, float) and value.is_integer():
                int_value = int(value)
                return int_value if int_value > 0 else default
            if isinstance(value, str):
                match = re.search(r"(\d+)", value)
                if match:
                    try:
                        parsed = int(match.group(1))
                    except ValueError:
                        continue
                    if parsed > 0:
                        return parsed
        return default

    async def fetch_stats_for_runner(
        self,
        runner_name: str,
        discipline: str,
        runner_data: dict[str, Any],
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        ZeturfProvider does not implement direct runner stats fetching. Returning empty stats.
        """
        logger.info(
            "ZeturfProvider does not implement direct runner stats fetching. Returning empty stats.",
            extra={"runner_name": runner_name, "discipline": discipline, "correlation_id": correlation_id},
        )
        return {}
