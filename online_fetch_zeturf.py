#!/usr/bin/env python3
"""Lightweight wrapper exposing a snapshot fetch helper for runner_chain."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Mapping

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

    snapshot = _impl.fetch_race_snapshot(
        rc,
        phase=phase_norm,
        sources=sources,
        url=url,
        retries=max(1, int(retry)),
        backoff=backoff if backoff > 0 else 0.6,
        initial_delay=0.3,
    )

    # Ensure hard minimum thresholds are echoed for downstream audits
    meta = snapshot.setdefault("meta", {}) if isinstance(snapshot, dict) else {}
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
