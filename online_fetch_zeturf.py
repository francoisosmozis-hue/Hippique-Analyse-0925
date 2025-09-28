#!/usr/bin/env python3
"""Lightweight wrapper exposing a snapshot fetch helper for runner_chain."""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
import inspect
from pathlib import Path
from urllib.parse import urljoin
from typing import Any, Dict, Iterable, Mapping

import yaml

from scripts import online_fetch_zeturf as _impl

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
    partants: int | None
    phase: str
    rc: str
    r_label: str
    c_label: str
    source_url: str | None = None
    course_id: str | None = None

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
            "partants": self.partants,
            "phase": self.phase,
            "rc": self.rc,
        }
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

    runners: list[dict[str, Any]] = []
    numbers = _RUNNER_NUM_RE.findall(html)
    names = _RUNNER_NAME_RE.findall(html)
    odds = _RUNNER_ODDS_RE.findall(html)

    for idx, number in enumerate(numbers):
        runner: dict[str, Any] = {"num": str(number)}
        if idx < len(names):
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
        discipline = discipline_match.group(1).lower()

    meeting: str | None = None
    meeting_match = _MEETING_RE.search(html)
    if meeting_match:
        meeting = meeting_match.group(1).strip() or None

    date: str | None = None
    date_match = _DATE_RE.search(html)
    if date_match:
        date = date_match.group(1)

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
    if resp.status_code in (403, 429):
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
        return {}

    missing_keys: list[str] = []
    for key in ("meeting", "discipline", "partants"):
        value = data.get(key)
        if value in (None, "", 0):
            missing_keys.append(key)

    if missing_keys:
        fallback = _ensure_fallback()
        for key in missing_keys:
            candidate = fallback.get(key)
            if candidate not in (None, "", 0):
                data[key] = candidate
                fallback_used = True

    for key in ("meeting", "discipline", "partants"):
        if data.get(key) in (None, "", 0):
            logger.warning("[ZEturf] Champ clé manquant: %s (url=%s)", key, url)
    data.setdefault("source_url", url)
    if fallback_used:
        logger.warning("[ZEturf] Extraction fallback utilisée pour %s", url)
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
    
_RUNNER_NUM_RE = re.compile(r"data-runner-num=['\"]?(\d+)", re.IGNORECASE)
_RUNNER_NAME_RE = re.compile(r"data-runner-name=['\"]?([^'\"]+)", re.IGNORECASE)
_RUNNER_ODDS_RE = re.compile(r"data-odds=(?:'|\")?([0-9]+(?:[.,][0-9]+)?)", re.IGNORECASE)
_PARTANTS_RE = re.compile(r"(\d{1,2})\s+partants", re.IGNORECASE)
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
    meeting = raw_snapshot.get("hippodrome") or raw_snapshot.get("meeting")
    date = raw_snapshot.get("date")
    discipline = raw_snapshot.get("discipline")
    course_id = raw_snapshot.get("course_id") or raw_snapshot.get("id_course")
    runners_raw = raw_snapshot.get("runners")
    runners: list[dict[str, Any]] = []
    if isinstance(runners_raw, Iterable) and not isinstance(runners_raw, (str, bytes)):
        for entry in runners_raw:
            if isinstance(entry, Mapping):
                parsed = _coerce_runner_entry(entry)
                if parsed:
                    runners.append(parsed)

    partants = raw_snapshot.get("partants")
    try:
        partants_val = int(partants) if partants not in (None, "") else None
    except (TypeError, ValueError):  # pragma: no cover - defensive
        partants_val = None
    if partants_val is None and runners:
        partants_val = len(runners)

    rc = f"{reunion}{course}"
    snapshot = RaceSnapshot(
        meeting=meeting,
        date=date,
        reunion=reunion,
        course=course,
        discipline=discipline,
        runners=runners,
        partants=partants_val,
        phase=phase,
        rc=rc,
        r_label=reunion,
        c_label=course,
        source_url=source_url,
        course_id=str(course_id) if course_id else None,
    )

    missing_fields = []
    for name, value in (
        ("meeting", snapshot.meeting),
        ("discipline", snapshot.discipline),
        ("partants", snapshot.partants),
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


def fetch_race_snapshot(
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

    candidate_urls: list[str] = []
    try:
        entry_url = _impl._extract_url_from_entry(entry)
    except AttributeError:  # pragma: no cover - defensive fallback
        entry_url = entry.get("url") if isinstance(entry, Mapping) else None
    normalised_entry_url = _ensure_absolute_url(entry_url) if isinstance(entry_url, str) else None
    if normalised_entry_url and normalised_entry_url not in candidate_urls:
        candidate_urls.append(normalised_entry_url)
    normalised_user_url = _ensure_absolute_url(url) if url else None
    if normalised_user_url and normalised_user_url not in candidate_urls:
        candidate_urls.append(normalised_user_url)

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
                partants=None,
                phase=phase_norm,
                rc=rc,
                r_label=reunion_norm,
                c_label=course_norm,
            ).as_dict()

        source_url = entry.get("url") if isinstance(entry.get("url"), str) else None
        if not source_url and html_snapshot and isinstance(html_snapshot.get("source_url"), str):
            source_url = str(html_snapshot["source_url"])
        if not source_url and url:
            source_url = url
        snapshot = _build_snapshot_payload(
            raw_snapshot,
            reunion_norm,
            course_norm,            
            phase=phase_norm,
            source_url=source_url,
        )
        
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



if hasattr(_impl, "main"):
    main = _impl.main
else:  # pragma: no cover - defensive fallback for stripped builds
    def main(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("scripts.online_fetch_zeturf.main is unavailable")


__all__ = ["fetch_race_snapshot", "main"]


if __name__ == "__main__":  # pragma: no cover
    main()

