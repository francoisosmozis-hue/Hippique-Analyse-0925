#!/usr/bin/env python3
"""Lightweight wrapper exposing a snapshot fetch helper for runner_chain."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import inspect
from typing import Any, Dict, Iterable, Mapping

import yaml

from scripts import online_fetch_zeturf as _impl

logger = logging.getLogger(__name__)

_DEFAULT_SOURCES_FILE = Path("config/sources.yml")
_BASE_EV_THRESHOLD = 0.40
_BASE_PAYOUT_THRESHOLD = 10.0


def _load_sources_config(path: str | os.PathLike[str] | None = None) -> Dict[str, Any]:
    """Return the sources configuration used to resolve RC→URL mappings."""

    if path is None:
        path = os.getenv("SOURCES_FILE") or _DEFAULT_SOURCES_FILE
    candidate = Path(path)
    if not candidate.is_file():
        return {}
    try:
        data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - defensive guard
        logger.warning("Unable to parse %s: %s", candidate, exc)
        return {}
    if isinstance(data, Mapping):
        return dict(data)
    return {}


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

    snapshot: dict[str, Any] = {
        "meeting": meeting,
        "date": date,
        "discipline": discipline,
        "reunion": reunion,
        "course": course,
        "r_label": reunion,
        "c_label": course,
        "runners": runners,
        "partants": partants_val,
        "phase": phase,
        "rc": f"{reunion}{course}",
    }
    if course_id:
        snapshot["course_id"] = str(course_id)
    if source_url:
        snapshot["source_url"] = source_url

    for field in ("meeting", "discipline", "partants"):
        if snapshot.get(field) in (None, ""):
            logger.warning("[ZEturf] Champ clé manquant: %s (rc=%s)", field, snapshot["rc"])

    return snapshot


def fetch_race_snapshot(
    reunion: str,
    course: str,
    phase: str = "H30",
    url: str | None = None,
    *,
    retry: int = 2,
    backoff: float = 0.6,
) -> dict:
    """Return a normalised snapshot for ``reunion``/``course``.

    The helper mirrors the historical CLI behaviour used by :mod:`runner_chain`.
    When a dedicated ``url`` is not provided the RC mapping is loaded from the
    standard ``config/sources.yml`` file.  The returned payload contains the
    metadata expected downstream (``runners``, ``partants``, ``meeting``, …).
    """

    reunion_norm = _normalise_label(reunion, "R")
    course_norm = _normalise_label(course, "C")
    rc = f"{reunion_norm}{course_norm}"

    sources = _load_sources_config()
    rc_map_raw = sources.get("rc_map") if isinstance(sources, Mapping) else None
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
        entry["url"] = url

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
    if isinstance(entry_url, str) and entry_url not in candidate_urls:
        candidate_urls.append(entry_url)
    if url and url not in candidate_urls:
        candidate_urls.append(url)

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

    rc_map[rc] = entry
    sources["rc_map"] = rc_map

    phase_norm = _normalise_phase_alias(phase)

    fetch_fn = getattr(_impl, "fetch_race_snapshot")
    use_new_signature = False
    try:
        raw_snapshot = _impl.fetch_race_snapshot(
            rc,
            phase=phase_norm,
            sources=sources,
            url=url,
            retries=max(1, int(retry)),
            backoff=backoff if backoff > 0 else 0.6,
            initial_delay=0.3,
        )
        signature = inspect.signature(fetch_fn)
    except (TypeError, ValueError):  # pragma: no cover - builtins without signature
        signature = None
    if signature is not None and "course" in signature.parameters:
        use_new_signature = True

    try:
        if use_new_signature:
            raw_snapshot = fetch_fn(
                reunion_norm,
                course_norm,
                phase_norm,
                sources=sources,
                url=url,
                retries=max(1, int(retry)),
                backoff=backoff if backoff > 0 else 0.6,
                initial_delay=0.3,
            )
        else:
            raw_snapshot = fetch_fn(
                rc,
                phase=phase_norm,
                sources=sources,
                url=url,
                retries=max(1, int(retry)),
                backoff=backoff if backoff > 0 else 0.6,
                initial_delay=0.3,
            )
    except Exception as exc:  # pragma: no cover - defensive catch
        logger.error("[ZEturf] échec fetch_race_snapshot pour %s: %s", rc, exc)
        return {
            "meeting": None,
            "date": None,
            "discipline": None,
            "reunion": reunion_norm,
            "course": course_norm,
            "r_label": reunion_norm,
            "c_label": course_norm,
            "runners": [],
            "partants": None,
            "phase": phase_norm,
            "rc": rc,
        }

    if not isinstance(raw_snapshot, Mapping):
        raw_snapshot = {}

    source_url = entry.get("url") if isinstance(entry.get("url"), str) else None
    snapshot = _build_snapshot_payload(
        raw_snapshot,
        reunion_norm,
        course_norm,
        phase=phase_norm,
        source_url=source_url,
    )

    # Ensure hard minimum thresholds are echoed for downstream audits
    meta = raw_snapshot.get("meta") if isinstance(raw_snapshot, Mapping) else None
    if isinstance(meta, dict):
        thresholds = meta.setdefault("exotic_thresholds", {})
        if isinstance(thresholds, dict):
            thresholds.setdefault("ev_min", _BASE_EV_THRESHOLD)
            thresholds.setdefault("payout_min", _BASE_PAYOUT_THRESHOLD)

    return snapshot


main = _impl.main


__all__ = ["fetch_race_snapshot", "main"]


if __name__ == "__main__":  # pragma: no cover
    main()
