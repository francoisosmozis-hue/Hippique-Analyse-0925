#!/usr/bin/env python3
"""Lightweight wrapper exposing a snapshot fetch helper for runner_chain."""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
import inspect
import json
from pathlib import Path
from urllib.parse import urljoin
from typing import Any, Dict, Iterable, Mapping

import yaml

from scripts import online_fetch_zeturf as _impl


def _load_full_impl() -> Any:
    """Return the fully-featured ``scripts.online_fetch_zeturf`` module."""

    module_name = "scripts.online_fetch_zeturf"
    module_path = Path(__file__).resolve().with_name("scripts").joinpath("online_fetch_zeturf.py")

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive guard
        raise ImportError(f"Unable to locate {module_name} implementation at {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _resolve_impl() -> Any:
    """Ensure the implementation module exposes the expected public API."""

    required_attrs = {
        "fetch_race_snapshot",
        "fetch_runners",
        "fetch_meetings",
        "resolve_source_url",
        "normalize_snapshot",
        "requests",
        "time",
    }

    if not all(hasattr(_impl, attr) for attr in required_attrs):
        return _load_full_impl()
    return _impl


_impl = _resolve_impl()

try:  # pragma: no cover - requests is always available in production
    import requests
except Exception:  # pragma: no cover - fallback when requests missing in tests
    requests = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RaceSnapshot:
    """Structured representation of a race snapshot."""

    meeting: str | None
    date: str | None
    reunion: str
    course: str
    discipline: str | None
    runners: list[dict[str, Any]]
    partants_count: int | None
    phase: str
    rc: str
    r_label: str
    c_label: str
    source_url: str | None = None
    course_id: str | None = None
    heure_officielle: str | None = None

    def as_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "meeting": self.meeting,
            "date": self.date,
            "reunion": self.reunion,
            "course": self.course,
            "r_label": self.r_label,
            "c_label": self.c_label,
            "discipline": self.discipline,
            "runners": self.runners,
            "partants_count": self.partants_count,
            "phase": self.phase,
            "rc": self.rc,
            "heure_officielle": self.heure_officielle,
        }
        payload["partants"] = payload["runners"]
        # ``hippodrome`` is often used as an alias for ``meeting`` downstream.
        # Persist it whenever available so callers no longer need to duplicate
        # the fallback logic.
        if self.meeting and "hippodrome" not in payload:
            payload["hippodrome"] = self.meeting
        if self.source_url:
            payload["source_url"] = self.source_url
        if self.course_id:
            payload["course_id"] = self.course_id
        return payload


def _exp_backoff_sleep(attempt: int, *, base: float = 1.0, cap: float = 5.0) -> None:
    """Sleep using an exponential backoff policy."""

    delay = min(cap, base * (2 ** max(0, attempt - 1)))
    if delay > 0:
        logger.debug("[ZEturf] backoff %.2fs before retry #%d", delay, attempt)
        time.sleep(delay)


def _fallback_parse_html(html: Any) -> dict[str, Any]:
    """Extract a minimal snapshot payload using regex heuristics."""

    if isinstance(html, bytes):
        try:
            html = html.decode("utf-8", errors="ignore")
        except Exception:  # pragma: no cover - defensive guard
            html = ""
    if not isinstance(html, str):
        html = str(html or "")

    def _clean_text(value: str | None, *, lowercase: bool = False, strip_accents: bool = False) -> str | None:
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
    numbers = _RUNNER_NUM_RE.findall(html)
    names = _RUNNER_NAME_RE.findall(html)
    odds = _RUNNER_ODDS_RE.findall(html)

    for idx, number in enumerate(numbers):
        runner: dict[str, Any] = {"num": str(number)}
        if idx < len(names):
            runner_name = _clean_text(names[idx])
            if runner_name:
                runner["name"] = runner_name
            else:
                runner["name"] = names[idx].strip()
        if idx < len(odds):
            try:
                runner["cote"] = float(odds[idx].replace(",", "."))
            except Exception:  # pragma: no cover - defensive conversion
                runner["cote"] = None
        runners.append(runner)

    partants: int | None = None
    partants_match = _PARTANTS_RE.search(html)
    if partants_match:
        try:
            partants = int(partants_match.group(1))
        except Exception:  # pragma: no cover - defensive conversion
            partants = None

    discipline: str | None = None
    discipline_match = _DISCIPLINE_RE.search(html)
    if discipline_match:
        discipline = _clean_text(discipline_match.group(1), lowercase=True, strip_accents=True)

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


def _looks_like_suspicious_html(payload: Any) -> bool:
    """Return ``True`` when a payload resembles throttled anti-bot HTML."""

    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8", errors="ignore")
        except Exception:  # pragma: no cover - defensive conversion
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


def _http_get(
    url: str,
    *,
    timeout: float = 12.0,
    session: Any | None = None,
) -> str:
    """Return raw HTML for ``url`` raising on suspicious throttled payloads."""

    if requests is None:
        raise RuntimeError("requests module unavailable for HTML fallback fetch")

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GPI/5.1; +https://example.local)",
        "Accept-Language": "fr-FR,fr;q=0.9",
    }

    if session is not None:
        resp = session.get(url, headers=headers, timeout=timeout)
    else:
        resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code in (403, 429) or 500 <= resp.status_code < 600:
        raise RuntimeError(f"HTTP {resp.status_code} returned by {url}")
    text = resp.text
    if _looks_like_suspicious_html(text):
        raise RuntimeError(f"Payload suspect reçu de {url}")
    if not text or len(text) < 512:
        raise RuntimeError(f"Payload trop court reçu de {url}")
    return text


def _double_extract(
    url: str,
    *,
    snapshot: str,
    session: Any | None = None,
) -> dict[str, Any]:
    """Return parsed data using the official parser with a regex fallback."""

    html = _http_get(url, session=session)

    data: dict[str, Any] | None = None
    fallback_used = False
    fallback_data: dict[str, Any] | None = None

    def _ensure_fallback() -> dict[str, Any]:
        nonlocal fallback_data
        if fallback_data is None:
            fallback_data = _fallback_parse_html(html)
        return fallback_data
    parse_fn = getattr(_impl, "parse_course_page", None)
    snapshot_mode = "H-30" if str(snapshot).upper().replace("-", "") == "H30" else "H-5"
    if callable(parse_fn):
        try:
            parsed = parse_fn(url, snapshot=snapshot_mode)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("parse_course_page a échoué (%s) pour %s", exc, url)
        else:
            if isinstance(parsed, Mapping):
                data = {str(k): v for k, v in parsed.items()}

    if not data or not data.get("runners"):
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
            snapshot_mode,
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
                snapshot_mode,
            )
    if not data.get("runners"):
        logger.warning(
            "[ZEturf] Aucun partant détecté (url=%s, snapshot=%s) — retournera une liste vide",
            url,
            snapshot_mode,
        )
        data["runners"] = []
    data.setdefault("source_url", url)
    if fallback_used:
        logger.warning(
            "[ZEturf] Extraction fallback utilisée pour %s (snapshot=%s)",
            url,
            snapshot_mode,
        )
    return data


def _merge_snapshot_data(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    """Fill missing fields of ``target`` with values from ``source`` when present."""

    if not isinstance(source, Mapping):
        return

    for key in ("hippodrome", "meeting"):
        if target.get(key) in (None, "") and source.get(key) not in (None, ""):
            target[key] = source[key]

    for key in ("date", "discipline", "partants", "course_id", "id_course"):
        if target.get(key) in (None, "", 0) and source.get(key) not in (None, ""):
            target[key] = source[key]

    runners = source.get("runners")
    if (not target.get("runners")) and isinstance(runners, list) and runners:
        target["runners"] = runners


def _fetch_snapshot_via_html(
    urls: Iterable[str],
    *,
    phase: str,
    retries: int,
    backoff: float,
    session: Any | None = None,
) -> dict[str, Any] | None:
    """Fetch a course page via HTML and return a parsed snapshot."""

    if requests is None:
        return None

    snapshot_mode = "H-30" if phase.upper().replace("-", "") == "H30" else "H-5"
    attempts = max(1, int(retries))
    base_delay = backoff if backoff > 0 else 1.0

    owns_session = False
    sess: Any | None = session
    if sess is None:
        try:
            sess = requests.Session()
        except Exception:  # pragma: no cover - defensive guard
            sess = None
        else:
            owns_session = True

    try:
        for url in urls:
            if not url:
                continue
            for attempt in range(1, attempts + 1):
                try:
                    parsed = _double_extract(
                        url,
                        snapshot=snapshot_mode,
                        session=sess,
                    )
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.warning(
                        "[ZEturf] fallback HTML fetch échec (%s) tentative %d/%d",
                        url,
                        attempt,
                        attempts,
                    )
                    logger.debug("[ZEturf] détail erreur fallback HTML: %s", exc)
                    _exp_backoff_sleep(attempt, base=base_delay)
                    continue
                if parsed:
                    parsed.setdefault("source_url", url)
                    parsed.setdefault("phase", snapshot_mode)
                    return parsed
        return None
    finally:
        if owns_session and sess is not None:
            try:
                sess.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass


_DEFAULT_SOURCES_FILE = Path("config/sources.yml")
_DEFAULT_ZETURF_TEMPLATE = "https://m.zeeturf.fr/rest/api/2/race/{course_id}"
_BASE_EV_THRESHOLD = 0.40
_BASE_PAYOUT_THRESHOLD = 10.0

_COURSE_PAGE_TEMPLATES = (
    "https://www.zeturf.fr/fr/course/{course_id}",
    "https://m.zeeturf.fr/fr/course/{course_id}",
)
_COURSE_PAGE_FROM_RC = "https://www.zeturf.fr/fr/course/{rc}"
_ZT_BASE_URL = "https://www.zeturf.fr"


def _ensure_absolute_url(value: str | os.PathLike[str] | None) -> str | None:
    """Normalise ``value`` into an absolute URL when possible."""

    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return text
    if text.startswith("//"):
        return "https:" + text
    if text.startswith("/"):
        return urljoin(_ZT_BASE_URL, text)
    head = text.split("/")[0]
    if "." in head:
        return "https://" + text
    return text


def _coerce_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _slugify_hippodrome(value: str | None) -> str | None:
    if not value:
        return None
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned or None


def _build_canonical_course_url(
    date_text: str | None, reunion: str, course: str, hippo: str | None
) -> str | None:
    if not date_text or not hippo:
        return None
    slug = _slugify_hippodrome(hippo)
    if not slug:
        return None
    base = _ensure_absolute_url(_ZT_BASE_URL) or _ZT_BASE_URL
    return f"{base}/fr/course/{date_text}/{reunion}{course}-{slug}"
    
_RUNNER_NUM_RE = re.compile(r"data-runner-num=['\"]?(\d+)", re.IGNORECASE)
_RUNNER_NAME_RE = re.compile(r"data-runner-name=['\"]?([^'\"]+)", re.IGNORECASE)
_RUNNER_ODDS_RE = re.compile(r"data-odds=(?:'|\")?([0-9]+(?:[.,][0-9]+)?)", re.IGNORECASE)
_PARTANTS_RE = re.compile(r"(?:\b|\D)(\d{1,2})\s+partant(?:e?s?)?\b", re.IGNORECASE)
_DISCIPLINE_RE = re.compile(r"(trot|plat|obstacles?|mont[ée])", re.IGNORECASE)
_MEETING_RE = re.compile(
    r"(?:data-)?(?:meeting|hippodrome)[-_]?name\s*[=:]\s*['\"]([^'\"]+)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
_SUSPICIOUS_HTML_PATTERNS = (
    "too many requests",
    "captcha",
    "temporarily unavailable",
    "access denied",
    "service unavailable",
    "cloudflare",
)


def _ensure_default_templates(config: Mapping[str, Any] | None) -> Dict[str, Any]:
    """Return ``config`` augmented with default Zeturf templates."""

    result: Dict[str, Any]
    if isinstance(config, Mapping):
        result = {str(k): v for k, v in config.items()}
    else:
        result = {}

    def _normalise_section(value: Mapping[str, Any] | None) -> Dict[str, Any]:
        if isinstance(value, Mapping):
            return {str(k): v for k, v in value.items()}
        return {}

    zet_section = _normalise_section(result.get("zeturf") if isinstance(result.get("zeturf"), Mapping) else None)
    if not any(isinstance(zet_section.get(key), str) for key in ("url", "course")):
        zet_section.setdefault("url", _DEFAULT_ZETURF_TEMPLATE)
    result["zeturf"] = zet_section

    online_section = _normalise_section(result.get("online") if isinstance(result.get("online"), Mapping) else None)
    zet_online = _normalise_section(online_section.get("zeturf") if isinstance(online_section.get("zeturf"), Mapping) else None)
    if not any(isinstance(zet_online.get(key), str) for key in ("course", "url")):
        zet_online.setdefault("course", _DEFAULT_ZETURF_TEMPLATE)
    online_section["zeturf"] = zet_online
    result["online"] = online_section

    return result


def _load_sources_config(path: str | os.PathLike[str] | None = None) -> Dict[str, Any]:
    """Return the sources configuration used to resolve RC→URL mappings."""

    if path is None:
        path = os.getenv("SOURCES_FILE") or _DEFAULT_SOURCES_FILE
    candidate = Path(path)
    if not candidate.is_file():
        return _ensure_default_templates(None)
    try:
        data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive guard
        logger.warning("Unable to parse %s: %s", candidate, exc)
        return _ensure_default_templates(None)
    return _ensure_default_templates(data if isinstance(data, Mapping) else None)


def _normalise_label(value: str, prefix: str) -> str:
    text = str(value).strip().upper()
    if not text:
        raise ValueError(f"{prefix.strip()} value is required")
    if not text.startswith(prefix):
        text = f"{prefix}{text}"
    if not text[len(prefix) :].isdigit():
        raise ValueError(f"{prefix.strip()} must match pattern {prefix}\\d+")
    return text


def _normalise_phase_alias(value: str) -> str:
    """Return a canonical ``phase`` representation understood by the backend."""

    text = str(value).strip()
    if not text:
        raise ValueError("phase value is required")
    # Accept common aliases such as ``H-30`` while keeping the canonical tag
    # expected by the scripts implementation.
    return text.upper().replace("-", "")


def _coerce_runner_entry(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalise a runner payload into the structure expected downstream."""

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

    name_raw = (
        entry.get("name")
        or entry.get("horse")
        or entry.get("label")
        or entry.get("runner")
    )
    name = str(name_raw).strip() if name_raw not in (None, "") else number

    runner: dict[str, Any] = {"num": number, "name": name}

    def _coerce_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return None

    for odds_key in ("cote", "odds", "odd", "cote_dec", "price"):
        odds_val = _coerce_float(entry.get(odds_key))
        if odds_val is not None:
            runner.setdefault("cote", odds_val)
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

    if "odds" not in runner and entry.get("odds") not in (None, ""):
        odds_val = _coerce_float(entry.get("odds"))
        if odds_val is not None:
            runner["odds"] = odds_val

    if "cote" not in runner and "odds" in runner:
        runner["cote"] = runner["odds"]

    return runner


def _build_snapshot_payload(
    raw_snapshot: Mapping[str, Any],
    reunion: str,
    course: str,
    *,
    phase: str,
    source_url: str | None = None,
) -> dict[str, Any]:
    def _coerce_str(value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        return text or None

    def _coerce_int(value: Any) -> int | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                return int(value)
            except (TypeError, ValueError):  # pragma: no cover - defensive
                return None
        if isinstance(value, str):
            match = re.search(r"\d+", value)
            if match:
                try:
                    return int(match.group(0))
                except ValueError:  # pragma: no cover - defensive
                    return None
        return None

    def _first_meta_value(mapping: Mapping[str, Any] | None, *keys: str) -> Any:
        if not isinstance(mapping, Mapping):
            return None
        for key in keys:
            value = mapping.get(key)
            if value not in (None, ""):
                return value
        return None

    meeting = _coerce_str(raw_snapshot.get("hippodrome") or raw_snapshot.get("meeting"))
    date = _coerce_str(raw_snapshot.get("date"))
    discipline = _coerce_str(raw_snapshot.get("discipline"))
    heure_officielle = _coerce_str(
        raw_snapshot.get("heure_officielle")
        or raw_snapshot.get("official_time")
        or raw_snapshot.get("start_time")
    )
    course_id = raw_snapshot.get("course_id") or raw_snapshot.get("id_course")
    runners_raw = raw_snapshot.get("runners")
    runners: list[dict[str, Any]] = []
    if isinstance(runners_raw, Iterable) and not isinstance(runners_raw, (str, bytes)):
        for entry in runners_raw:
            if isinstance(entry, Mapping):
                parsed = _coerce_runner_entry(entry)
                if parsed:
                    runners.append(parsed)
                    
    if runners:
        deduped: list[dict[str, Any]] = []
        seen_numbers: set[str] = set()

        for runner in runners:
            number = str(runner.get("num") or runner.get("id") or "").strip()
            if number:
                if number in seen_numbers:
                    continue
                seen_numbers.add(number)
            deduped.append(runner)

        def _runner_sort_key(item: Mapping[str, Any]) -> tuple[int, str]:
            raw_number = str(item.get("num") or item.get("id") or "").strip()
            match = re.search(r"\d+", raw_number)
            num_val = int(match.group(0)) if match else 10**6
            return (num_val, raw_number)

        deduped.sort(key=_runner_sort_key)
        runners = deduped
        
    partants_count = _coerce_int(raw_snapshot.get("partants"))

    meta_raw = raw_snapshot.get("meta") if isinstance(raw_snapshot.get("meta"), Mapping) else None
    course_meta = (
        meta_raw.get("course")
        if isinstance(meta_raw, Mapping) and isinstance(meta_raw.get("course"), Mapping)
        else None
    )

    if meeting is None:
        candidate = _coerce_str(
            _first_meta_value(meta_raw, "hippodrome", "meeting", "venue")
        ) or _coerce_str(_first_meta_value(course_meta, "hippodrome", "meeting", "venue"))
        if candidate:
            meeting = candidate

    if date is None:
        candidate = _coerce_str(_first_meta_value(meta_raw, "date", "jour", "day"))
        if not candidate:
            candidate = _coerce_str(_first_meta_value(course_meta, "date", "jour", "day"))
        if candidate:
            date = candidate

    if discipline is None:
        candidate = _coerce_str(
            _first_meta_value(meta_raw, "discipline", "sport", "type")
        ) or _coerce_str(_first_meta_value(course_meta, "discipline", "type", "specialite"))
        if candidate:
            discipline = candidate

    if heure_officielle is None:
        candidate = _first_meta_value(
            meta_raw,
            "heure_officielle",
            "official_time",
            "start_time",
        )
        if candidate is None:
            candidate = _first_meta_value(
                course_meta,
                "heure_officielle",
                "official_time",
                "start_time",
            )
        heure_officielle = _coerce_str(candidate)
        
    if partants_count is None:
        candidate = _first_meta_value(meta_raw, "partants", "nb_partants", "n_partants", "participants")
        if candidate is None:
            candidate = _first_meta_value(course_meta, "partants", "participants", "nb_partants")
        partants_count = _coerce_int(candidate)

    if partants_count is None and runners:
        partants_count = len(runners)

    rc = f"{reunion}{course}"
    snapshot = RaceSnapshot(
        meeting=meeting,
        date=date,
        reunion=reunion,
        course=course,
        discipline=discipline,
        runners=runners,
        partants_count=partants_count,
        phase=phase,
        rc=rc,
        r_label=reunion,
        c_label=course,
        source_url=source_url,
        course_id=str(course_id) if course_id else None,
        heure_officielle=heure_officielle,
    )

    missing_fields = []
    for name, value in (
        ("meeting", snapshot.meeting),
        ("discipline", snapshot.discipline),
        ("partants", snapshot.partants_count),
    ):
        if value in (None, "", 0):
            missing_fields.append(name)
    if missing_fields:
        source_hint = (
            snapshot.source_url
            or (raw_snapshot.get("source_url") if isinstance(raw_snapshot, Mapping) else None)
        )
        logger.warning(
            "[ZEturf] Champ(s) manquant(s): %s (rc=%s, url=%s)",
            ", ".join(sorted(set(missing_fields))),
            rc,
            source_hint or "?",
        )

    return snapshot.as_dict()
 
    
_RC_COMBINED_RE = re.compile(r"R?\s*(\d+)\s*C\s*(\d+)", re.IGNORECASE)


def _fetch_race_snapshot_impl(
    reunion: str,
    course: str | None = None,
    phase: str = "H30",
    *,
    url: str | None = None,
    session: Any | None = None,
    retry: int | None = 3,
    retries: int | None = None,
    backoff: float = 1.0,
    sources: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a normalised snapshot for ``reunion``/``course``.

    The signature enforces ``url`` as a keyword-only argument to mirror the
    public contract advertised to downstream callers (runner_chain/pipeline).
    Additional keyword-only knobs (``retry``/``retries``/``backoff``) remain
    available for advanced use-cases while keeping the positional parameters
    identical to the historical CLI wrapper.  Callers may supply a custom
    ``sources`` mapping to override the default configuration loaded from
    :mod:`config/sources.yml`.
    """

    reunion_text = str(reunion).strip()
    course_text = "" if course is None else str(course).strip()

    retry_count = retries if retries is not None else retry
    try:
        retry_count_int = int(retry_count) if retry_count is not None else 3
    except (TypeError, ValueError):  # pragma: no cover - defensive fallback
        retry_count_int = 3
    if retry_count_int <= 0:
        retry_count_int = 1

    if not reunion_text:
        raise ValueError("reunion value is required")

    if not course_text:
        match = _RC_COMBINED_RE.search(reunion_text.upper())
        if match:
            reunion_text = f"R{match.group(1)}"
            course_text = f"C{match.group(2)}"
        else:
            raise ValueError("course value is required")

    reunion_norm = _normalise_label(reunion_text, "R")
    course_norm = _normalise_label(course_text, "C")
    rc = f"{reunion_norm}{course_norm}"

    if sources is not None:
        sources_payload = _ensure_default_templates(sources)
    else:
        sources_payload = _load_sources_config()
    rc_map_raw = (
        sources_payload.get("rc_map")
        if isinstance(sources_payload, Mapping)
        else None
    )
    rc_map: Dict[str, Any]
    if isinstance(rc_map_raw, Mapping):
        rc_map = {str(k): v for k, v in rc_map_raw.items()}
    else:
        rc_map = {}

    entry: Dict[str, Any] = {}
    if rc in rc_map and isinstance(rc_map[rc], Mapping):
        entry = dict(rc_map[rc])

    entry.setdefault("reunion", reunion_norm)
    entry.setdefault("course", course_norm)
    if url:
        entry["url"] = _ensure_absolute_url(url) or url

    course_id_hint = None
    try:
        course_id_hint = _impl._extract_course_id_from_entry(entry)
    except AttributeError:  # pragma: no cover - defensive fallback
        course_id_hint = None

    date_hint = _coerce_str(entry.get("date")) or _coerce_str(entry.get("jour"))
    hippo_hint = _coerce_str(entry.get("hippodrome")) or _coerce_str(entry.get("meeting"))
    meta_hint = entry.get("meta") if isinstance(entry.get("meta"), Mapping) else None
    if isinstance(meta_hint, Mapping):
        date_hint = date_hint or _coerce_str(
            meta_hint.get("date") or meta_hint.get("jour") or meta_hint.get("day")
        )
        hippo_hint = hippo_hint or _coerce_str(
            meta_hint.get("hippodrome")
            or meta_hint.get("meeting")
            or meta_hint.get("venue")
        )
        
    candidate_urls: list[str] = []
    try:
        entry_url = _impl._extract_url_from_entry(entry)
    except AttributeError:  # pragma: no cover - defensive fallback
        entry_url = entry.get("url") if isinstance(entry, Mapping) else None
    normalised_entry_url = _ensure_absolute_url(entry_url) if isinstance(entry_url, str) else None
    if normalised_entry_url and normalised_entry_url not in candidate_urls:
        candidate_urls.append(normalised_entry_url)
    normalised_user_url = _ensure_absolute_url(url) if url else None
    if normalised_user_url:
        if normalised_user_url in candidate_urls:
            candidate_urls.remove(normalised_user_url)
        candidate_urls.insert(0, normalised_user_url)

    canonical_url = _build_canonical_course_url(
        date_hint, reunion_norm, course_norm, hippo_hint
    )
    if canonical_url and canonical_url not in candidate_urls:
        if normalised_user_url:
            candidate_urls.append(canonical_url)
        else:
            candidate_urls.insert(0, canonical_url)

    if not course_id_hint:
        for candidate in candidate_urls:
            if not candidate:
                continue
            try:
                match = _impl._COURSE_ID_PATTERN.search(candidate)
            except AttributeError:  # pragma: no cover - defensive fallback
                match = None
            if match:
                course_id_hint = match.group(0)
                entry.setdefault("course_id", course_id_hint)
                break

    if not course_id_hint:
        recovered = getattr(_impl, "discover_course_id", lambda _rc: None)(rc)
        if recovered:
            entry["course_id"] = recovered
            course_id_hint = recovered

    if course_id_hint and not isinstance(entry.get("url"), str):
        entry["url"] = _DEFAULT_ZETURF_TEMPLATE

    seen_urls: set[str] = set()
    fallback_urls: list[str] = []
    for candidate in candidate_urls:
        if not candidate:
            continue
        normalised = _ensure_absolute_url(candidate) or candidate
        if normalised not in seen_urls:
            fallback_urls.append(normalised)
            seen_urls.add(normalised)

    if course_id_hint:
        for template in _COURSE_PAGE_TEMPLATES:
            candidate = template.format(course_id=course_id_hint)
            normalised = _ensure_absolute_url(candidate) or candidate
            if normalised not in seen_urls:
                fallback_urls.append(normalised)
                seen_urls.add(normalised)

    guessed_from_rc = _COURSE_PAGE_FROM_RC.format(rc=rc)
    normalised_guess = _ensure_absolute_url(guessed_from_rc) or guessed_from_rc
    if normalised_guess not in seen_urls:
        fallback_urls.append(normalised_guess)
        seen_urls.add(normalised_guess)

    primary_url: str | None = None
    if normalised_user_url:
        primary_url = normalised_user_url
    elif fallback_urls:
        primary_url = fallback_urls[0]
    rc_map[rc] = entry
    
    sources_payload["rc_map"] = rc_map

    phase_norm = _normalise_phase_alias(phase)

    raw_snapshot: dict[str, Any] | None = None
    last_error: Exception | None = None
    
    html_attempted: set[str] = set()

    owns_session = False
    session_obj: Any | None = session
    if session_obj is None and requests is not None:
        try:
            session_obj = requests.Session()
        except Exception:  # pragma: no cover - defensive guard
            session_obj = None
        else:
            owns_session = True

    try:
        def _try_html(urls: Iterable[str]) -> dict[str, Any] | None:
            ordered: list[str] = []
            for candidate in urls:
                if not candidate or candidate in html_attempted:
                    continue
                ordered.append(candidate)
            if not ordered:
                return None
            html_attempted.update(ordered)
            return _fetch_snapshot_via_html(
                ordered,
                phase=phase_norm,
                retries=retry_count_int,
                backoff=backoff,
                session=session_obj,
            )

        html_snapshot: dict[str, Any] | None = None
        if url:
            direct_url = _ensure_absolute_url(url) or url
            base_delay = backoff if backoff > 0 else 1.0
            for attempt in range(1, retry_count_int + 1):
                try:
                    html_snapshot = _double_extract(
                        direct_url,
                        snapshot=phase_norm,
                        session=session_obj,
                    )
                except Exception as exc:  # pragma: no cover - defensive logging
                    last_error = exc
                    logger.warning(
                        "[ZEturf] lecture directe échouée pour %s (tentative %d/%d): %s",
                        direct_url,
                        attempt,
                        retry_count_int,
                        exc,
                    )
                    if attempt < retry_count_int:
                        _exp_backoff_sleep(attempt, base=base_delay)
                    continue
                else:
                    html_attempted.add(direct_url)
                    if html_snapshot:
                        html_snapshot.setdefault("source_url", direct_url)
                        html_snapshot.setdefault("phase", phase_norm)
                        raw_snapshot = dict(html_snapshot)
                    break            
            else:
                html_attempted.add(direct_url)
                
        if html_snapshot is None:
            html_snapshot = _try_html(fallback_urls)
        if isinstance(html_snapshot, dict) and html_snapshot:
            raw_snapshot = dict(html_snapshot)

        fetch_fn = getattr(_impl, "fetch_race_snapshot")
        try:
            signature = inspect.signature(fetch_fn)
        except (TypeError, ValueError):  # pragma: no cover - builtins without signature
            signature = None

        fetch_kwargs = {
            "phase": phase_norm,
            "sources": sources_payload,
            "url": _ensure_absolute_url(url) if url else url,
            "retries": retry_count_int,
            "backoff": backoff if backoff > 0 else 1.0,
            "initial_delay": 0.3,
        }

        arg_candidates: list[tuple[Any, ...]] = []
        if signature is not None and "course" in signature.parameters:
            arg_candidates.append((reunion_norm, course_norm))
        arg_candidates.append((rc,)) 
                
        if raw_snapshot is None or not raw_snapshot.get("runners"):
            for args in arg_candidates:
                try:
                    result = fetch_fn(*args, **fetch_kwargs)
                except TypeError as exc:  # pragma: no cover - defensive
                    last_error = exc
                    continue
                except Exception as exc:  # pragma: no cover - propagate after logging
                    last_error = exc
                    break
                snapshot_candidate = dict(result) if isinstance(result, Mapping) else {}
                if snapshot_candidate:
                    if raw_snapshot is None:
                        raw_snapshot = snapshot_candidate
                    else:
                        _merge_snapshot_data(raw_snapshot, snapshot_candidate)
                    last_error = None
                    break

            if raw_snapshot is None or not raw_snapshot.get("runners"):
                fallback_snapshot: dict[str, Any] | None = _try_html(fallback_urls)
                if fallback_snapshot:
                    if raw_snapshot is None:
                        raw_snapshot = dict(fallback_snapshot)
                    else:
                        _merge_snapshot_data(raw_snapshot, fallback_snapshot)
                    html_snapshot = fallback_snapshot

        if raw_snapshot is None:
            if last_error is not None:
                logger.error("[ZEturf] échec fetch_race_snapshot pour %s: %s", rc, last_error)
            else:
                logger.error(
                    "[ZEturf] échec fetch_race_snapshot pour %s: aucune donnée recueillie",
                    rc,
                )
            return RaceSnapshot(
                meeting=None,
                date=None,
                reunion=reunion_norm,
                course=course_norm,
                discipline=None,
                runners=[],
                partants_count=None,
                phase=phase_norm,
                rc=rc,
                r_label=reunion_norm,
                c_label=course_norm,
                source_url=primary_url,
            ).as_dict()

        source_url = entry.get("url") if isinstance(entry.get("url"), str) else None
        if not source_url and html_snapshot and isinstance(html_snapshot.get("source_url"), str):
            source_url = str(html_snapshot["source_url"])
        if not source_url and url:
            source_url = url
        if not source_url and primary_url:
            source_url = primary_url
        snapshot = _build_snapshot_payload(
            raw_snapshot,
            reunion_norm,
            course_norm,
            phase=phase_norm,
            source_url=source_url,
        )
        
        # ``runner_chain`` expects ``partants`` to always hold a list of runner
        # dictionaries.  Some legacy payloads expose ``partants`` as an integer
        # count which would cascade into downstream failures (``list`` is
        # required for the pre-enrichment step).  Normalise the field eagerly to
        # make the contract explicit and resilient to upstream variations.
        partants_field = snapshot.get("partants")
        if not isinstance(partants_field, list):
            runners_list = snapshot.get("runners")
            if isinstance(runners_list, list):
                snapshot["partants"] = runners_list
            else:
                snapshot["partants"] = []

        meta = raw_snapshot.get("meta") if isinstance(raw_snapshot, Mapping) else None
        if isinstance(meta, dict):
            thresholds = meta.setdefault("exotic_thresholds", {})
            if isinstance(thresholds, dict):
                thresholds.setdefault("ev_min", _BASE_EV_THRESHOLD)
                thresholds.setdefault("payout_min", _BASE_PAYOUT_THRESHOLD)

        return snapshot
    finally:
        if owns_session and session_obj is not None:
            try:
                session_obj.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass


def _coerce_partants_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, list):
        return len(value) if value else None
    if isinstance(value, (int, float)):
        try:
            return int(value)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return None
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        if match:
            try:
                return int(match.group(0))
            except ValueError:  # pragma: no cover - defensive
                return None
    return None


def _format_source_url_from_template(
    template: str,
    *,
    course_id: Any,
    rc: str | None,
    reunion: str | None,
    course: str | None,
) -> str | None:
    if not isinstance(template, str) or not template:
        return None

    context: dict[str, Any] = {}
    if course_id not in (None, ""):
        context["course_id"] = course_id
    if rc:
        context["rc"] = rc
    if reunion:
        context["reunion"] = reunion
    if course:
        context["course"] = course

    formatted = template
    try:
        formatted = template.format(**context)
    except (KeyError, IndexError, ValueError):
        # Leave ``formatted`` untouched so callers can detect unresolved placeholders.
        pass

    if "{" in formatted or "}" in formatted:
        return None

    return _ensure_absolute_url(formatted) or formatted


def _merge_h30_odds(
    runners: list[dict[str, Any]],
    reunion_label: str | None,
    course_label: str | None,
) -> None:
    if not runners or not reunion_label or not course_label:
        return

    try:
        reunion_norm = _normalise_label(reunion_label, "R")
        course_norm = _normalise_label(course_label, "C")
    except ValueError:
        return

    h30_path = Path("data") / f"{reunion_norm}{course_norm}" / "h30.json"

    def _coerce_number(value: Any) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        return text or None

    def _pick(keys: tuple[str, ...], source: Mapping[str, Any]) -> Any | None:
        for key in keys:
            if key not in source:
                continue
            value = source.get(key)
            if value not in (None, ""):
                return value
        return None

    try:
        raw_text = h30_path.read_text(encoding="utf-8")
    except OSError:
        return

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.debug("[ZEturf] unable to parse %s", h30_path)
        return

    if not isinstance(payload, Mapping):
        return

    odds_map: dict[str, dict[str, Any]] = {}

   def _register(number: str, *, win: Any | None = None, place: Any | None = None) -> None:
        updates = odds_map.setdefault(number, {})
        if win is not None:
            updates["odds_win_h30"] = win
        if place is not None and "odds_place_h30" not in updates:
            updates["odds_place_h30"] = place
        if not updates:
            odds_map.pop(number, None)
            
        candidates = payload.get("runners")
    runners_iterable = (
        candidates
        if isinstance(candidates, Iterable) and not isinstance(candidates, (str, bytes))
        else None
    )

        if runners_iterable is not None:
        for entry in runners_iterable:
            if not isinstance(entry, Mapping):
                continue

        number = _coerce_number(
                entry.get("num")
                or entry.get("id")
                or entry.get("number")
                or entry.get("runner_id")
            )
            if not number:
                continue

            win_value = _pick(
                (
                    "odds_win",
                    "odds",
                    "cote",
                    "gagnant",
                    "win",
                    "odds_win_h30",
                ),
                entry,
            )
            place_value = _pick(
                (
                    "odds_place",
                    "place",
                    "cote_place",
                    "place_odds",
                    "odds_place_h30",
                ),
                entry,
            )

            if win_value is not None or place_value is not None:
                _register(number, win=win_value, place=place_value)
    else:
        for key, value in payload.items():
            if key == "runners":
                continue

            number = _coerce_number(key)
            if not number:
                continue
                
            win_value: Any | None
            place_value: Any | None = None
            if isinstance(value, Mapping):
                win_value = _pick(
                    (
                        "odds_win",
                        "odds",
                        "cote",
                        "gagnant",
                        "win",
                        "odds_win_h30",
                    ),
                    value,
                )
                place_value = _pick(
                    (
                        "odds_place",
                        "place",
                        "cote_place",
                        "place_odds",
                        "odds_place_h30",
                    ),
                    value,
                )
            else:
                win_value = value

            if win_value is not None or place_value is not None:
                _register(number, win=win_value, place=place_value)

    normalized_places: dict[str, Any] = {}
    normalized_path = h30_path.with_name("normalized_h30.json")
    try:
        normalized_raw = normalized_path.read_text(encoding="utf-8")
    except OSError:
        normalized_payload: Mapping[str, Any] | None = None
    else:
        try:
            parsed = json.loads(normalized_raw)
        except json.JSONDecodeError:
            logger.debug("[ZEturf] unable to parse %s", normalized_path)
            normalized_payload = None
        else:
            normalized_payload = parsed if isinstance(parsed, Mapping) else None

    if normalized_payload:
        normalized_runners = normalized_payload.get("runners")
        if isinstance(normalized_runners, Iterable) and not isinstance(
            normalized_runners, (str, bytes)
        ):
            for entry in normalized_runners:
                if not isinstance(entry, Mapping):
                    continue
                number = _coerce_number(
                    entry.get("num")
                    or entry.get("number")
                    or entry.get("id")
                    or entry.get("runner_id")
                )
                if not number:
                    continue
                place_value = _pick(
                    (
                        "odds_place_h30",
                        "odds_place",
                        "place",
                        "cote_place",
                        "place_odds",
                    ),
                    entry,
                )
                if place_value is not None:
                    normalized_places[number] = place_value

    for number, place_value in normalized_places.items():
        updates = odds_map.setdefault(number, {})
        if "odds_place_h30" not in updates:
            updates["odds_place_h30"] = place_value

    if not odds_map:
        return

    for runner in runners:
        if not isinstance(runner, dict):
            continue
        number = str(runner.get("num") or runner.get("id") or "").strip()
        if not number:
            continue
        extras = odds_map.get(number)
        if not extras:
            continue
        runner.update(extras)


def fetch_race_snapshot(
    reunion: str,
    course: str | None = None,
    phase: str = "H30",
    **kwargs: Any,
) -> dict[str, Any]:
    """Return a snapshot decorated with metadata suitable for runner_chain."""

    phase_norm = _normalise_phase_alias(phase)

    reunion_text = str(reunion or "").strip()
    course_text = "" if course is None else str(course).strip()

    if not course_text:
        match = _RC_COMBINED_RE.search(reunion_text.upper())
        if match:
            reunion_text = f"R{match.group(1)}"
            course_text = f"C{match.group(2)}"

    def _safe_normalise(value: str, prefix: str) -> str | None:
        text = str(value or "").strip().upper()
        if not text:
            return None
        try:
            return _normalise_label(text, prefix)
        except ValueError:
            return text or None

    reunion_norm = _safe_normalise(reunion_text, "R")
    course_norm = _safe_normalise(course_text, "C") if course_text else None

    reunion_arg = reunion_norm or reunion_text or str(reunion)
    course_arg: str | None
    if course is None:
        course_arg = course_norm
    else:
        course_arg = _safe_normalise(str(course), "C") or str(course).strip() or None

    fetch_kwargs = dict(kwargs)

    sources_config = fetch_kwargs.get("sources")
    if not isinstance(sources_config, Mapping):
        try:
            sources_config = _load_sources_config()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("[ZEturf] unable to load sources configuration: %s", exc)
            sources_config = None
        else:
            fetch_kwargs.setdefault("sources", sources_config)

    raw_snapshot = _fetch_race_snapshot_impl(
        reunion_arg,
        course_arg,
        phase=phase_norm,
        **fetch_kwargs,
    )

    result: dict[str, Any]
    if isinstance(raw_snapshot, Mapping):
        result = dict(raw_snapshot)
    else:
        result = {}

    original_partants_field = result.get("partants") if isinstance(result.get("partants"), list) else None
    runners_raw = result.get("runners")
    runners: list[dict[str, Any]] = []
    if isinstance(runners_raw, Iterable) and not isinstance(runners_raw, (str, bytes)):
        for entry in runners_raw:
            if isinstance(entry, Mapping):
                runners.append(dict(entry))
    result["runners"] = runners

    existing_meta = result.get("meta") if isinstance(result.get("meta"), Mapping) else {}
    meta: dict[str, Any] = dict(existing_meta) if isinstance(existing_meta, Mapping) else {}

    def _clean_str(value: Any) -> str | None:
        if value in (None, ""):
            return None
        return str(value).strip()

    reunion_meta = _clean_str(meta.get("reunion")) or reunion_norm or _clean_str(result.get("reunion"))
    course_meta = _clean_str(meta.get("course")) or course_norm or _clean_str(result.get("course"))
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
    if course_meta:
        result["course"] = course_meta
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
        value = _coerce_partants_int(candidate)
        if value is not None:
            partants_count = value
            break

    if partants_count is None and runners:
        partants_count = len(runners)

    result["partants_count"] = partants_count

    if isinstance(original_partants_field, list):
        result["partants"] = original_partants_field
    else:
        result["partants"] = runners

    if phase_norm == "H5":
        _merge_h30_odds(runners, reunion_meta, course_meta)

    resolver = getattr(_impl, "resolve_source_url", None)
    if callable(resolver) and isinstance(sources_config, Mapping):
        try:
            mode_key = "h5" if phase_norm == "H5" else "h30"
            template = resolver(sources_config, mode_key)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("[ZEturf] unable to resolve source url: %s", exc)
        else:
            formatted_url = _format_source_url_from_template(
                template,
                course_id=result.get("course_id") or result.get("id_course"),
                rc=rc_value,
                reunion=reunion_meta,
                course=course_meta,
            )
            if formatted_url and not result.get("source_url"):
                result["source_url"] = formatted_url

    return result


if hasattr(_impl, "main"):
    main = _impl.main
else:  # pragma: no cover - defensive fallback for stripped builds
    def main(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("scripts.online_fetch_zeturf.main is unavailable")


__all__ = ["fetch_race_snapshot", "main"]

# Re-export normalisation helper when available so downstream tooling can rely
# on the same convenience shim regardless of whether it imports the lightweight
# wrapper (this module) or the historical implementation under ``scripts``.
if hasattr(_impl, "normalize_snapshot"):
    normalize_snapshot = _impl.normalize_snapshot  # type: ignore[attr-defined]
    if "normalize_snapshot" not in __all__:
        __all__.append("normalize_snapshot")

if __name__ == "__main__":  # pragma: no cover
    main()

