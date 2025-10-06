#!/usr/bin/env python3
"""Pipeline helper for analysing today's horse races.

This script optionally discovers all French meetings of the day from Geny and
runs a small pipeline on each course. The behaviour without the ``--from-geny-today``
flag is intentionally minimal in order to preserve the previous behaviour (if
any) of the script.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from logging_io import CSV_HEADER, append_csv_line
from scripts.gcs_utils import disabled_reason, is_gcs_enabled
from scripts.online_fetch_zeturf import normalize_snapshot

# Tests may insert a lightweight stub of ``scripts.online_fetch_zeturf`` to avoid
# pulling heavy scraping dependencies.  Ensure the stub does not linger in
# ``sys.modules`` so that later imports retrieve the fully-featured module.
_fetch_module = sys.modules.get("scripts.online_fetch_zeturf")
if _fetch_module is not None and not hasattr(_fetch_module, "fetch_race_snapshot"):
    sys.modules.pop("scripts.online_fetch_zeturf", None)
import pipeline_run
from runner_chain import compute_overround_cap
from scripts.fetch_je_stats import collect_stats
from simulate_wrapper import PAYOUT_CALIBRATION_PATH, evaluate_combo

logger = logging.getLogger(__name__)


class MissingH30SnapshotError(RuntimeError):
    """Raised when the H-30 snapshot required for ``enrich_h5`` is missing."""

    def __init__(self, message: str, *, rc_dir: Path | str | None = None) -> None:
        super().__init__(message)
        self.rc_dir = Path(rc_dir) if isinstance(rc_dir, (str, Path)) else None


USE_GCS = is_gcs_enabled()

TRACKING_HEADER = CSV_HEADER + ["phase", "status", "reason"]

try:  # pragma: no cover - optional dependency in tests
    from scripts.online_fetch_zeturf import write_snapshot_from_geny
except Exception:  # pragma: no cover - used when optional deps are missing

    def write_snapshot_from_geny(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("write_snapshot_from_geny is unavailable")


if USE_GCS:
    try:  # pragma: no cover - optional dependency in tests
        from scripts.drive_sync import build_remote_path as gcs_build_remote_path
        from scripts.drive_sync import push_tree
    except Exception as exc:  # pragma: no cover - used when optional deps are missing
        print(
            f"[WARN] Synchronisation GCS indisponible ({exc}), bascule en mode local.",
            file=sys.stderr,
        )
        USE_GCS = False
    gcs_build_remote_path = None  # type: ignore[assignment]
    push_tree = None  # type: ignore[assignment]
else:  # pragma: no cover - Cloud sync explicitly disabled
    gcs_build_remote_path = None  # type: ignore[assignment]
    push_tree = None  # type: ignore[assignment]


# --- RÈGLES ANTI-COTES FAIBLES (SP min 4/1 ; CP somme > 6.0 déc) ---------------
MIN_SP_DEC_ODDS = 5.0  # 4/1 = 5.0
MIN_CP_SUM_DEC = 6.0  # (o1-1)+(o2-1) ≥ 4  <=> (o1+o2) ≥ 6.0


def _write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_minimal_csv(
    path: Path, headers: Iterable[Any], rows: Iterable[Iterable[Any]] | None = None
) -> None:
    """Persist a tiny CSV artefact with the provided ``headers`` and ``rows``."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(list(headers))
        if rows:
            for row in rows:
                writer.writerow(list(row))


def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _coerce_int(value: Any) -> int | None:
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            text = value.strip()
            match = re.search(r"\d+", text)
            if match:
                return int(match.group(0))
    except Exception:  # pragma: no cover - defensive
        return None
    return None


def _derive_rc_parts(label: str) -> tuple[str, str]:
    text = str(label or "").replace(" ", "").upper()
    match = re.match(r"^(R\d+)(C\d+)$", text)
    if match:
        return match.group(1), match.group(2)
    if text.startswith("R") and "C" in text:
        r_part, c_part = text.split("C", 1)
        return r_part, f"C{c_part}"
    return text or "", ""


def _gather_tracking_base(rc_dir: Path) -> dict[str, Any]:
    payloads: list[dict[str, Any]] = []
    for name in ("p_finale.json", "partants.json", "normalized_h5.json"):
        data = _load_json_if_exists(rc_dir / name)
        if not data:
            continue
        payloads.append(data)
        meta = data.get("meta")
        if isinstance(meta, dict):
            payloads.append(meta)

    def _first(*keys: str) -> Any:
        for mapping in payloads:
            for key in keys:
                value = mapping.get(key)
                if value not in (None, ""):
                    return value
        return None

    rc_value = _first("rc") or rc_dir.name
    reunion, course = _derive_rc_parts(rc_value)
    hippo = _first("hippodrome", "meeting") or ""
    date = _first("date", "jour", "day") or ""
    discipline = _first("discipline", "type", "categorie", "category") or ""
    model = _first("model") or ""

    partants_value = _first(
        "partants",
        "nb_participants",
        "nb_partants",
        "nombre_partants",
        "participants",
        "number_of_runners",
    )
    partants_count = _coerce_int(partants_value)
    if partants_count is None:
        for mapping in payloads:
            runners = mapping.get("runners")
            if isinstance(runners, list) and runners:
                partants_count = len(runners)
                break

    base = {
        "reunion": reunion,
        "course": course,
        "hippodrome": hippo,
        "date": date,
        "discipline": discipline,
        "partants": partants_count or "",
        "nb_tickets": 0,
        "total_stake": 0,
        "total_optimized_stake": 0,
        "ev_sp": 0,
        "ev_global": 0,
        "roi_sp": 0,
        "roi_global": 0,
        "risk_of_ruin": 0,
        "clv_moyen": 0,
        "model": model,
    }
    return base


def _log_tracking_missing(
    rc_dir: Path,
    *,
    status: str,
    reason: str,
    phase: str,
    budget: float | None = None,
    ev: float | None = None,
    roi: float | None = None,
) -> None:
    base = _gather_tracking_base(rc_dir)
    if budget is not None and budget > 0:
        base["total_stake"] = f"{float(budget):.2f}"
        base["total_optimized_stake"] = f"{float(budget):.2f}"
    if ev is not None:
        base["ev_sp"] = base["ev_global"] = ev
    if roi is not None:
        base["roi_sp"] = base["roi_global"] = roi
    base["phase"] = phase
    base["status"] = status
    base["reason"] = reason
    append_csv_line(str(rc_dir / "tracking.csv"), base, header=TRACKING_HEADER)


def _extract_id2name(payload: Any) -> dict[str, str]:
    """Return an ``id -> name`` mapping from the provided payload."""

    mapping: dict[str, str] = {}
    if not isinstance(payload, dict):
        return mapping

    raw = payload.get("id2name")
    if isinstance(raw, dict) and raw:
        for cid, name in raw.items():
            if cid is None:
                continue
            mapping[str(cid)] = "" if name is None else str(name)
        if mapping:
            return mapping

    runners = payload.get("runners")
    if isinstance(runners, list):
        for runner in runners:
            if not isinstance(runner, dict):
                continue
            cid = runner.get("id") or runner.get("num") or runner.get("number")
            if cid is None:
                continue
            name = runner.get("name") or runner.get("nom") or runner.get("label")
            mapping[str(cid)] = "" if name is None else str(name)
    return mapping


def _extract_stats_mapping(stats_payload: Any) -> dict[str, dict[str, Any]]:
    """Normalise the stats payload into a ``dict[id] -> stats`` mapping."""

    mapping: dict[str, dict[str, Any]] = {}
    if isinstance(stats_payload, dict):
        for key, value in stats_payload.items():
            if not isinstance(value, dict):
                continue
            mapping[str(key)] = value
    return mapping


def _write_je_csv_file(
    path: Path, *, id2name: dict[str, str], stats_payload: Any
) -> None:
    """Materialise the ``*_je.csv`` companion using the provided mappings."""

    stats_mapping = _extract_stats_mapping(stats_payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["num", "nom", "j_rate", "e_rate"])
        for cid, name in sorted(id2name.items(), key=lambda item: item[0]):
            stats = stats_mapping.get(cid, {})
            if not isinstance(stats, dict):
                stats = {}
            writer.writerow(
                [
                    cid,
                    name,
                    stats.get("j_win", ""),
                    stats.get("e_win", ""),
                ]
            )


def _norm_float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except Exception:  # pragma: no cover - defensive
        return None


def _filter_sp_and_cp_by_odds(payload: dict[str, Any]) -> None:
    tickets = payload.get("tickets", []) or []
    kept: list[dict[str, Any]] = []

    def _append_note(message: str) -> None:
        notes = payload.get("notes")
        if isinstance(notes, list):
            notes.append(message)
        else:
            payload["notes"] = [message]

    for ticket in tickets:
        if not isinstance(ticket, dict):
            kept.append(ticket)
            continue

        typ = str(ticket.get("type") or "").upper()
        lab = str(ticket.get("label") or "").upper()

        # 1) SP (toutes variantes de dutching place)
        if lab == "SP_DUTCHING_GPIv51" or typ in (
            "SP",
            "SIMPLE_PLACE_DUTCHING",
            "DUTCHING_SP",
            "PLACE_DUTCHING",
        ):
            legs = ticket.get("legs") or ticket.get("bets") or []
            if not isinstance(legs, list):
                if isinstance(legs, Iterable) and not isinstance(legs, (str, bytes)):
                    legs = list(legs)
                else:
                    legs = []

            new_legs = []
            for leg in legs:
                if not isinstance(leg, dict):
                    continue
                odds = None
                for key in ("cote_place", "odds", "cote", "odd"):
                    if leg.get(key) is not None:
                        odds = _norm_float(leg.get(key))
                        break
                if odds is None:
                    market = payload.get("market") or {}
                    horses = market.get("horses") if isinstance(market, dict) else []
                    num = str(leg.get("num") or leg.get("horse") or "")
                    mh = None
                    if isinstance(horses, list):
                        mh = next(
                            (
                                h
                                for h in horses
                                if isinstance(h, dict) and str(h.get("num")) == num
                            ),
                            None,
                        )
                    if mh and mh.get("cote") is not None:
                        odds = _norm_float(mh.get("cote"))
                if odds is not None and odds >= MIN_SP_DEC_ODDS:
                    new_legs.append(leg)

            if new_legs:
                ticket_filtered = dict(ticket)
                ticket_filtered["legs"] = new_legs
                kept.append(ticket_filtered)
            else:
                _append_note("SP retiré: toutes les cotes < 4/1 (5.0 déc).")
            continue

        # 2) COUPLÉ PLACÉ (ou libellés équivalents)
        if typ in ("COUPLE", "COUPLE_PLACE", "CP", "COUPLÉ PLACÉ", "COUPLE PLACÉ"):
            legs_raw = ticket.get("legs") or []
            legs = [leg for leg in legs_raw if isinstance(leg, dict)]
            if len(legs) != 2:
                kept.append(ticket)
                _append_note("Avertissement: CP non-binaire (≠2 jambes).")
                continue
            odds_list: list[float | None] = []
            for leg in legs:
                odds = None
                for key in ("cote_place", "odds", "cote", "odd"):
                    if leg.get(key) is not None:
                        odds = _norm_float(leg.get(key))
                        break
                if odds is None:
                    market = payload.get("market") or {}
                    horses = market.get("horses") if isinstance(market, dict) else []
                    num = str(leg.get("num") or leg.get("horse") or "")
                    mh = None
                    if isinstance(horses, list):
                        mh = next(
                            (
                                h
                                for h in horses
                                if isinstance(h, dict) and str(h.get("num")) == num
                            ),
                            None,
                        )
                    if mh and mh.get("cote") is not None:
                        odds = _norm_float(mh.get("cote"))
                odds_list.append(odds)
            if all(o is not None for o in odds_list):
                assert len(odds_list) == 2  # for type checkers
                if (odds_list[0] + odds_list[1]) >= MIN_CP_SUM_DEC:
                    kept.append(ticket)
                else:
                    _append_note(
                        "CP retiré: somme des cotes décimales"
                        f" {odds_list[0]:.2f}+{odds_list[1]:.2f} < 6.00 (règle ≥ 4/1 cumulés)."
                    )
            else:
                _append_note("CP retiré: cotes manquantes (règle >4/1 non vérifiable).")
            continue

        kept.append(ticket)

    payload["tickets"] = kept


# ---------------------------------------------------------------------------
# Helper stubs - these functions are expected to be provided elsewhere in the
# larger project. They are defined here so the module can be imported and easily
# monkeypatched during tests.
# ---------------------------------------------------------------------------


def ensure_dir(path: Path) -> Path:
    """Create ``path`` if it does not exist and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def enrich_h5(rc_dir: Path, *, budget: float, kelly: float) -> None:
    """Prepare all artefacts required for the H-5 pipeline.

    The function normalises the latest H-30/H-5 snapshots, extracts odds maps,
    fetches jockey/entraineur statistics and materialises CSV companions used
    by downstream tooling.  by downstream tooling.  The H-30 snapshot is a hard requirement; when it is
    absent the function abstains and signals the caller to mark the course as
    non playable.
    """

    rc_dir = ensure_dir(Path(rc_dir))

    def _latest_snapshot(tag: str) -> Path | None:
        pattern = f"*_{tag}.json"
        candidates = sorted(rc_dir.glob(pattern))
        if not candidates:
            return None
        # ``glob`` returns in alphabetical order which correlates with the
        # timestamp prefix we use for snapshots.  The most recent file is the
        # last one.
        return candidates[-1]

    def _load_snapshot(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Snapshot invalide: {path} ({exc})") from exc

    def _normalise_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
        normalised = normalize_snapshot(payload)
        # Preserve a few metadata fields expected by downstream consumers.
        for key in [
            "id_course",
            "course_id",
            "source",
            "rc",
            "r_label",
            "meeting",
            "reunion",
            "race",
        ]:
            value = payload.get(key)
            if value is not None and key not in normalised:
                normalised[key] = value
        return normalised

    h5_raw_path = _latest_snapshot("H-5")
    if h5_raw_path is None:
        raise FileNotFoundError("Aucun snapshot H-5 trouvé pour l'analyse")
    h5_payload = _load_snapshot(h5_raw_path)
    h5_normalised = _normalise_snapshot(h5_payload)

    h30_raw_path = _latest_snapshot("H-30")
    h30_payload: dict[str, Any]
    if h30_raw_path is not None:
        h30_payload = _load_snapshot(h30_raw_path)
        h30_normalised = _normalise_snapshot(h30_payload)
    else:
        label = rc_dir.name or str(rc_dir)
        message = f"Snapshot H-30 manquant dans {rc_dir}"
        logger.warning("[H-5] %s", message)
        print(f"[ABSTENTION] {message} – {label}", file=sys.stderr)
        raise MissingH30SnapshotError(message, rc_dir=rc_dir)

    def _odds_map(snapshot: dict[str, Any]) -> dict[str, float]:
        odds = snapshot.get("odds")
        if isinstance(odds, dict):
            return {str(k): float(v) for k, v in odds.items() if _is_number(v)}
        runners = snapshot.get("runners")
        if isinstance(runners, list):
            mapping: dict[str, float] = {}
            for runner in runners:
                if not isinstance(runner, dict):
                    continue
                cid = runner.get("id")
                odds_val = runner.get("odds")
                if cid is None or not _is_number(odds_val):
                    continue
                mapping[str(cid)] = float(odds_val)
            return mapping
        return {}

    odds_h5 = _odds_map(h5_normalised)
    odds_h30 = _odds_map(h30_normalised)
    if not odds_h30:
        odds_h30 = dict(odds_h5)

    _write_json_file(rc_dir / "normalized_h5.json", h5_normalised)
    _write_json_file(rc_dir / "normalized_h30.json", h30_normalised)
    _write_json_file(rc_dir / "h5.json", odds_h5)
    _write_json_file(rc_dir / "h30.json", odds_h30)

    partants_payload = {
        "rc": h5_normalised.get("rc") or rc_dir.name,
        "hippodrome": h5_normalised.get("hippodrome") or h5_payload.get("hippodrome"),
        "date": h5_normalised.get("date") or h5_payload.get("date"),
        "discipline": h5_normalised.get("discipline") or h5_payload.get("discipline"),
        "runners": h5_normalised.get("runners", []),
        "id2name": h5_normalised.get("id2name", {}),
        "course_id": h5_payload.get("id_course")
        or h5_payload.get("course_id")
        or h5_payload.get("id"),
    }
    _write_json_file(rc_dir / "partants.json", partants_payload)

    stats_path = rc_dir / "stats_je.json"
    course_id = str(partants_payload.get("course_id") or "").strip()
    if not course_id:
        raise ValueError(
            "Impossible de déterminer l'identifiant course pour les stats J/E"
        )
    snap_stem = h5_raw_path.stem
    je_path = rc_dir / f"{snap_stem}_je.csv"
    try:
        coverage, mapped = collect_stats(
            course_id, h5_path=rc_dir / "normalized_h5.json"
        )
    except Exception:  # pragma: no cover - network or scraping issues
        logger.exception("collect_stats failed for course %s", course_id)
        stats_payload = {"coverage": 0, "ok": 0}
        _write_json_file(stats_path, stats_payload)
        placeholder_headers = ["num", "nom", "j_rate", "e_rate", "ok"]
        placeholder_rows = [["", "", "", "", 0]]
        _write_minimal_csv(je_path, placeholder_headers, placeholder_rows)
    else:
        stats_payload = {"coverage": coverage}
        stats_payload.update(mapped)
        _write_json_file(stats_path, stats_payload)

        id2name = _extract_id2name(partants_payload)
        _write_je_csv_file(je_path, id2name=id2name, stats_payload=mapped)

    chronos_path = rc_dir / "chronos.csv"
    try:
        _write_chronos_csv(chronos_path, partants_payload.get("runners", []))
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to materialise chronos CSV in %s", rc_dir)
        placeholder_headers = ["num", "chrono", "ok"]
        placeholder_rows = [["", "", 0]]
        _write_minimal_csv(chronos_path, placeholder_headers, placeholder_rows)


def build_p_finale(rc_dir: Path, *, budget: float, kelly: float) -> None:
    """Run the ticket allocation pipeline and persist ``p_finale.json``."""

    rc_dir = Path(rc_dir)
    _run_single_pipeline(rc_dir, budget=budget)


def run_pipeline(rc_dir: Path, *, budget: float, kelly: float) -> None:
    """Execute the analysis pipeline for ``rc_dir`` or its subdirectories."""

    rc_dir = Path(rc_dir)

    # If ``rc_dir`` already holds a freshly generated ``p_finale.json`` we do
    # not run the pipeline again – this is the case when ``build_p_finale`` was
    # just invoked on the directory.
    if (rc_dir / "p_finale.json").exists():
        return

    inputs_available = any(
        rc_dir.joinpath(name).exists()
        for name in ("h5.json", "partants.json", "stats_je.json")
    )
    if inputs_available:
        _run_single_pipeline(rc_dir, budget=budget)
        return

    ran_any = False
    for subdir in sorted(p for p in rc_dir.iterdir() if p.is_dir()):
        try:
            build_p_finale(subdir, budget=budget, kelly=kelly)
        except FileNotFoundError:
            continue
        ran_any = True
    if not ran_any:
        raise FileNotFoundError(f"Aucune donnée pipeline détectée dans {rc_dir}")


def build_prompt_from_meta(rc_dir: Path, *, budget: float, kelly: float) -> None:
    """Generate a human-readable prompt from ``p_finale.json`` metadata."""

    rc_dir = Path(rc_dir)
    p_finale_path = rc_dir / "p_finale.json"
    if not p_finale_path.exists():
        raise FileNotFoundError(f"p_finale.json introuvable dans {rc_dir}")
    data = json.loads(p_finale_path.read_text(encoding="utf-8"))
    meta = data.get("meta", {})
    ev = data.get("ev", {})
    tickets = data.get("tickets", [])

    prompt_lines = [
        f"Course {meta.get('rc', rc_dir.name)} – {meta.get('hippodrome', '')}".strip(),
        f"Date : {meta.get('date', '')} | Discipline : {meta.get('discipline', '')}",
        f"Budget : {budget:.2f} € | Fraction de Kelly : {kelly:.2f}",
    ]

    prompt_lines.append("Filtres GPI v5.1 (obligatoires) :")
    prompt_lines.append(
        "  - Interdiction SP < 4/1 (placé décimal < 5.0). Couplé Placé autorisé uniquement si cote1 + cote2 > 6.0 (équiv. somme > 4/1 cumulés)."
    )

    if isinstance(ev, dict) and ev:
        global_ev = ev.get("global")
        roi = ev.get("roi_global")
        prompt_lines.append(
            "EV globale : "
            + (
                f"{float(global_ev):.2f}"
                if isinstance(global_ev, (int, float))
                else "n/a"
            )
            + " | ROI estimé : "
            + (f"{float(roi):.2f}" if isinstance(roi, (int, float)) else "n/a")
        )

    def _format_ticket(ticket: dict[str, Any]) -> str:
        label = ticket.get("type") or ticket.get("id") or "Ticket"
        stake = ticket.get("stake")
        odds = ticket.get("odds")
        parts = [str(label)]
        if _is_number(stake):
            parts.append(f"mise {float(stake):.2f}€")
        if _is_number(odds):
            parts.append(f"cote {float(odds):.2f}")
        legs = ticket.get("legs") or ticket.get("selection")
        if isinstance(legs, Iterable) and not isinstance(legs, (str, bytes)):
            legs_fmt = ", ".join(str(leg) for leg in legs)
            if legs_fmt:
                parts.append(f"legs: {legs_fmt}")
        return " – ".join(parts)

    if tickets:
        prompt_lines.append("Tickets proposés :")
        for ticket in tickets:
            if isinstance(ticket, dict):
                prompt_lines.append(f"  - {_format_ticket(ticket)}")

    prompt_dir = rc_dir / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_text_path = prompt_dir / "prompt.txt"
    prompt_text_path.write_text("\n".join(prompt_lines) + "\n", encoding="utf-8")

    prompt_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "budget": budget,
        "kelly_fraction": kelly,
        "meta": meta,
        "ev": ev,
        "tickets": tickets,
        "text_path": str(prompt_text_path),
    }
    (prompt_dir / "prompt.json").write_text(
        json.dumps(prompt_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _write_chronos_csv(path: Path, runners: Iterable[Any]) -> None:
    """Persist a chronos CSV placeholder using runner identifiers."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["num", "chrono"])
        for runner in runners or []:
            if not isinstance(runner, dict):
                continue
            cid = runner.get("id") or runner.get("num") or runner.get("number")
            if cid is None:
                continue
            chrono = runner.get("chrono") or runner.get("time") or ""
            writer.writerow([cid, chrono])


def _run_single_pipeline(rc_dir: Path, *, budget: float) -> None:
    """Execute :func:`pipeline_run.cmd_analyse` for ``rc_dir``."""

    rc_dir = ensure_dir(rc_dir)
    required = {"h30.json", "h5.json", "partants.json", "stats_je.json"}
    missing = [name for name in required if not (rc_dir / name).exists()]
    if missing:
        raise FileNotFoundError(
            f"Fichiers manquants pour l'analyse dans {rc_dir}: {', '.join(missing)}"
        )

    stats_payload = json.loads((rc_dir / "stats_je.json").read_text(encoding="utf-8"))
    allow_je_na = False
    if isinstance(stats_payload, dict):
        coverage = stats_payload.get("coverage")
        allow_je_na = isinstance(coverage, (int, float)) and coverage < 100

    gpi_candidates = [
        rc_dir / "gpi.yml",
        rc_dir / "gpi.yaml",
        Path("config/gpi.yml"),
        Path("config/gpi.yaml"),
    ]
    gpi_path = next((path for path in gpi_candidates if path.exists()), None)
    if gpi_path is None:
        raise FileNotFoundError("Configuration GPI introuvable (gpi.yml)")

    args = argparse.Namespace(
        h30=str(rc_dir / "h30.json"),
        h5=str(rc_dir / "h5.json"),
        stats_je=str(rc_dir / "stats_je.json"),
        partants=str(rc_dir / "partants.json"),
        gpi=str(gpi_path),
        outdir=str(rc_dir),
        diff=None,
        budget=float(budget),
        ev_global=None,
        roi_global=None,
        max_vol=None,
        min_payout=None,
        ev_min_exotic=None,
        payout_min_exotic=None,
        allow_heuristic=False,
        allow_je_na=allow_je_na,
        calibration=str(PAYOUT_CALIBRATION_PATH),
    )
    pipeline_run.cmd_analyse(args)

    p_finale_path = rc_dir / "p_finale.json"
    try:
        payload = json.loads(p_finale_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except json.JSONDecodeError:  # pragma: no cover - defensive
        return

    if not isinstance(payload, dict):
        return

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    existing_meta_notes: set[str] = set()
    if isinstance(meta, dict):
        bucket = meta.get("notes")
        if isinstance(bucket, list):
            existing_meta_notes = {str(note) for note in bucket}

    _filter_sp_and_cp_by_odds(payload)

    notes_bucket = payload.get("notes")
    if isinstance(notes_bucket, list) and notes_bucket:
        if not isinstance(meta, dict):
            meta = {}
            payload["meta"] = meta
        dest = meta.get("notes")
        if isinstance(dest, list):
            for note in notes_bucket:
                if note not in existing_meta_notes:
                    dest.append(note)
                    existing_meta_notes.add(note)
        else:
            meta["notes"] = list(dict.fromkeys(str(n) for n in notes_bucket))

    p_finale_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _find_je_csv(rc_dir: Path) -> Path | None:
    """Return the JE CSV produced during enrichment when available."""

    snap = _snap_prefix(rc_dir)
    if snap:
        candidate = rc_dir / f"{snap}_je.csv"
        if candidate.exists():
            return candidate
    for candidate in rc_dir.glob("*je.csv"):
        if candidate.name.lower().endswith("je.csv") and candidate.is_file():
            return candidate
    return None


def _is_combo_ticket(ticket: Mapping[str, Any]) -> bool:
    """Return ``True`` when ``ticket`` refers to an exotic combination."""

    ticket_type = str(ticket.get("type") or "").upper()
    if ticket_type.startswith("SP") or "SIMPLE" in ticket_type:
        return False
    if ticket.get("legs"):
        return True
    return ticket_type not in {"SP", "SIMPLE", "SIMPLE_PLACE", "PLACE"}


def _evaluate_combo_guard(
    ticket: Mapping[str, Any],
    *,
    bankroll: float,
) -> dict[str, Any]:
    """Evaluate ``ticket`` via :func:`simulate_wrapper.evaluate_combo`."""

    try:
        return evaluate_combo(
            [dict(ticket)],
            bankroll,
            calibration=str(PAYOUT_CALIBRATION_PATH),
            allow_heuristic=False,
        )
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception("Guard combo evaluation failed for %s", ticket.get("id"))
        return {
            "status": "error",
            "ev_ratio": 0.0,
            "roi": 0.0,
            "payout_expected": 0.0,
            "notes": [f"evaluation_error:{exc}"],
        }


def _run_h5_guard_phase(
    rc_dir: Path,
    *,
    budget: float,
    min_roi: float = 0.20,
) -> tuple[bool, dict[str, Any], dict[str, Any] | None]:
    """Evaluate post-enrichment guardrails returning analysis payload/outcome."""

    rc_dir = Path(rc_dir)
    je_csv = _find_je_csv(rc_dir)
    chronos_path = rc_dir / "chronos.csv"
    p_finale_path = rc_dir / "p_finale.json"
    partants_path = rc_dir / "partants.json"
    h5_odds_path = rc_dir / "h5.json"

    try:
        p_finale_payload = json.loads(p_finale_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        p_finale_payload = {}

    meta_block = p_finale_payload.get("meta")
    meta: dict[str, Any] = dict(meta_block) if isinstance(meta_block, Mapping) else {}
    if not meta:
        base = _gather_tracking_base(rc_dir)
        if isinstance(base, dict):
            meta = {
                k: v
                for k, v in base.items()
                if k
                in {"reunion", "course", "hippodrome", "date", "discipline", "partants"}
            }
        meta.setdefault("rc", rc_dir.name)
    else:
        meta.setdefault("rc", meta.get("rc") or rc_dir.name)

    tickets_block = p_finale_payload.get("tickets")
    tickets: list[dict[str, Any]] = []
    if isinstance(tickets_block, list):
        for ticket in tickets_block:
            if isinstance(ticket, Mapping):
                tickets.append({str(k): v for k, v in ticket.items()})

    guards_context: dict[str, Any] = {}

    data_missing: list[str] = []
    data_ok = True
    if je_csv is None:
        data_missing.append("je_csv")
        data_ok = False
    if not chronos_path.exists():
        data_missing.append("chronos")
        data_ok = False

    calibration_ok = PAYOUT_CALIBRATION_PATH.exists()
    if not calibration_ok:
        guards_context["calibration"] = str(PAYOUT_CALIBRATION_PATH)

    overround_value: float | None = None
    overround_cap: float | None = None
    if h5_odds_path.exists():
        try:
            odds_payload = json.loads(h5_odds_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:  # pragma: no cover - defensive
            odds_payload = {}
        if isinstance(odds_payload, Mapping):
            overround_value = pipeline_run._compute_market_overround(odds_payload)

    partants_payload: Mapping[str, Any] = {}
    if partants_path.exists():
        try:
            partants_data = json.loads(partants_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:  # pragma: no cover - defensive
            partants_data = {}
        if isinstance(partants_data, Mapping):
            partants_payload = partants_data

    discipline_hint = (
        meta.get("discipline")
        or partants_payload.get("discipline")
        or partants_payload.get("discipline_label")
        or partants_payload.get("type_course")
        or partants_payload.get("type")
        or partants_payload.get("categorie")
        or partants_payload.get("category")
    )
    course_label_hint = (
        partants_payload.get("course_label")
        or partants_payload.get("label")
        or partants_payload.get("name")
        or meta.get("course")
    )
    partants_hint: Any = (
        meta.get("partants")
        or partants_payload.get("partants")
        or partants_payload.get("nombre_partants")
        or partants_payload.get("nb_partants")
        or partants_payload.get("number_of_runners")
    )
    if partants_hint in (None, "", 0):
        runners_source = partants_payload.get("runners")
        if isinstance(runners_source, list) and runners_source:
            partants_hint = len(runners_source)

    try:
        default_cap = float(os.getenv("MAX_COMBO_OVERROUND", "1.30"))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        default_cap = 1.30

    if overround_value is not None:
        overround_cap = compute_overround_cap(
            discipline_hint,
            partants_hint,
            default_cap=default_cap,
            course_label=course_label_hint,
        )
        guards_context["overround"] = {
            "value": overround_value,
            "cap": overround_cap,
        }
    overround_ok = (
        overround_value is None
        or overround_cap is None
        or overround_value <= overround_cap + 1e-9
    )

    combo_tickets = [ticket for ticket in tickets if _is_combo_ticket(ticket)]
    combo_bankroll = sum(
        float(ticket.get("stake", 0.0))
        for ticket in combo_tickets
        if isinstance(ticket.get("stake"), (int, float))
    )
    if combo_bankroll <= 0:
        combo_bankroll = float(budget)

    ev_ok = True
    combo_results: list[dict[str, Any]] = []
    for ticket in combo_tickets:
        result = _evaluate_combo_guard(ticket, bankroll=combo_bankroll)
        combo_results.append(
            {
                "id": ticket.get("id"),
                "type": ticket.get("type"),
                "status": result.get("status"),
                "ev_ratio": result.get("ev_ratio"),
                "roi": result.get("roi"),
                "payout_expected": result.get("payout_expected"),
                "notes": result.get("notes", []),
            }
        )
        if str(result.get("status", "")).lower() != "ok":
            ev_ok = False
    if combo_results:
        guards_context["combo_eval"] = combo_results
        result_by_id = {}
        for res in combo_results:
            ticket_id = str(res.get("id") or "")
            if ticket_id:
                result_by_id[ticket_id] = res
        for ticket in tickets:
            if not _is_combo_ticket(ticket):
                continue
            ticket_id = str(ticket.get("id") or "")
            if ticket_id and ticket_id in result_by_id:
                ticket["guard_eval"] = result_by_id[ticket_id]

    ev_block = p_finale_payload.get("ev")
    roi_value: float | None = None
    if isinstance(ev_block, Mapping):
        roi_candidate = ev_block.get("roi_global")
        try:
            roi_value = float(roi_candidate)
        except (TypeError, ValueError):
            roi_value = None
    guards_context["roi_global"] = roi_value
    roi_ok = roi_value is not None and roi_value >= min_roi

    existing_context = meta.get("guard_context")
    if isinstance(existing_context, Mapping):
        merged_context = {str(k): v for k, v in existing_context.items()}
        merged_context.update(guards_context)
        guards_context = merged_context
    meta["guard_context"] = guards_context

    guard_flags = {
        "data_ok": data_ok,
        "calibration_ok": calibration_ok,
        "overround_ok": overround_ok,
        "ev_ok": ev_ok,
        "roi_ok": roi_ok,
    }

    analysis_payload = {
        "meta": meta,
        "guards": guard_flags,
        "decision": "PLAY",
        "tickets": tickets,
    }

    failure_reason: str | None = None
    if not data_ok:
        failure_reason = "data_missing"
    elif not calibration_ok:
        failure_reason = "calibration_missing"
    elif not overround_ok:
        failure_reason = "overround"
    elif not ev_ok:
        failure_reason = "combo_evaluation"
    elif not roi_ok:
        failure_reason = "roi_below_threshold"

    if failure_reason:
        analysis_payload["decision"] = "ABSTENTION"
        if data_missing:
            guards_context["missing"] = data_missing
        outcome = {
            "status": "no-bet",
            "decision": "ABSTENTION",
            "reason": failure_reason,
            "jouable": False,
            "analysis": {
                "status": "NO_PLAY_GUARDRAIL",
                "guards": guard_flags,
                "decision": "ABSTENTION",
            },
            "details": {
                "guards": guards_context,
            },
        }
        if data_missing:
            logger.warning(
                "[H-5][guards] data missing for %s (reason=data_missing, missing=%s)",
                rc_dir.name,
                ",".join(data_missing),
            )
        else:
            logger.warning(
                "[H-5][guards] guard failure for %s (reason=%s)",
                rc_dir.name,
                failure_reason,
            )
        return False, analysis_payload, outcome

    analysis_payload["decision"] = "PLAY"
    logger.info("[H-5][guards] course %s validated", rc_dir.name)
    return True, analysis_payload, None


def _upload_artifacts(rc_dir: Path, *, gcs_prefix: str | None) -> None:
    """Upload ``rc_dir`` contents to Google Cloud Storage."""

    if gcs_prefix is None:
        return
    if not USE_GCS or not push_tree:
        reason = disabled_reason()
        if reason:
            detail = f"{reason}=false"
        else:
            detail = f"USE_GCS={USE_GCS}"
        print(f"[gcs] Upload ignoré pour {rc_dir} ({detail})", file=sys.stderr)
        return
    try:
        if gcs_build_remote_path:
            prefix = gcs_build_remote_path(gcs_prefix, rc_dir.name)
        else:  # pragma: no cover - best effort fallback
            prefix = "/".join(
                p for p in ((gcs_prefix or "").rstrip("/"), rc_dir.name) if p
            )
        push_tree(rc_dir, folder_id=prefix)
    except Exception as exc:  # pragma: no cover - best effort
        print(f"[WARN] Failed to upload {rc_dir}: {exc}")


def _snap_prefix(rc_dir: Path) -> str | None:
    """Return the stem of the most recent H-5 snapshot if available."""

    snapshots = list(rc_dir.glob("*_H-5.json"))
    if not snapshots:
        return None

    def _key(path: Path) -> tuple[float, str]:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (mtime, path.name)

    latest = max(snapshots, key=_key)
    return latest.stem


_SCRIPTS_DIR = Path(__file__).resolve().with_name("scripts")
_FETCH_JE_STATS_SCRIPT = _SCRIPTS_DIR.joinpath("fetch_je_stats.py")
_FETCH_JE_CHRONO_SCRIPT = _SCRIPTS_DIR.joinpath("fetch_je_chrono.py")


def _check_enrich_outputs(
    rc_dir: Path,
    *,
    retry_delay: float = 1.0,
    retry_cb: Callable[[], None] | None = None,
) -> dict[str, Any] | None:
    """Ensure ``enrich_h5`` produced required CSV artefacts.

    The check retries once after a short delay to accommodate slow I/O. When
    the required files remain missing, a structured ``no-bet`` payload is
    returned so that callers can gracefully skip the course instead of
    terminating the whole pipeline.
    """

    for attempt in range(2):
        snap = _snap_prefix(rc_dir)
        je_csv = rc_dir / f"{snap}_je.csv" if snap else None
        chronos_csv = rc_dir / "chronos.csv"

        missing: list[str] = []
        if not je_csv or not je_csv.exists():
            missing.append(f"{snap}_je.csv" if snap else "*_je.csv")
        if not chronos_csv.exists():
            missing.append("chronos.csv")

        if not missing:
            return None

        message = ", ".join(missing)
        if attempt == 0:
            print(
                "[WARN] fichiers manquants après enrich_h5 (nouvelle tentative) : "
                + message,
                file=sys.stderr,
            )
            if retry_cb is not None:
                try:
                    retry_cb()
                except Exception as exc:  # pragma: no cover - defensive logging
                    print(
                        f"[WARN] relance enrich_h5 a échoué pour {rc_dir.name}: {exc}",
                        file=sys.stderr,
                    )
            if retry_delay is not None:
                time.sleep(max(0.0, retry_delay))
            continue

        print(
            "[ERROR] fichiers manquants après enrich_h5 malgré la nouvelle tentative : "
            + message,
            file=sys.stderr,
        )
        return {
            "status": "no-bet",
            "decision": "ABSTENTION",
            "reason": "data-missing",
            "details": {"missing": missing},
        }

    return None


def _missing_requires_stats(missing: Iterable[str]) -> bool:
    return any(str(name).endswith("_je.csv") for name in missing)


def _missing_requires_chronos(missing: Iterable[str]) -> bool:
    return any(str(name) == "chronos.csv" for name in missing)


def _run_fetch_script(script_path: Path, rc_dir: Path) -> bool:
    """Invoke an auxiliary fetch script and report whether it succeeded."""

    cmd: list[str] = [sys.executable, str(script_path)]

    if script_path.name == "fetch_je_stats.py":

        def _extract_course_id(payload: dict[str, Any]) -> str | None:
            for key in ("course_id", "id_course", "id"):
                value = payload.get(key)
                if value not in (None, ""):
                    return str(value).strip()
            meta = payload.get("meta")
            if isinstance(meta, dict):
                return _extract_course_id(meta)
            return None

        course_id: str | None = None
        partants_path = rc_dir / "partants.json"
        if partants_path.exists():
            try:
                payload = json.loads(partants_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                print(
                    f"[WARN] partants.json invalide dans {rc_dir}: {exc}",
                    file=sys.stderr,
                )
            else:
                if isinstance(payload, dict):
                    course_id = _extract_course_id(payload)

        if not course_id:
            candidates: list[Path] = []
            normalized = rc_dir / "normalized_h5.json"
            if normalized.exists():
                candidates.append(normalized)
            candidates.extend(sorted(rc_dir.glob("*_H-5.json")))
            for candidate in candidates:
                try:
                    payload = json.loads(candidate.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    course_id = _extract_course_id(payload)
                if course_id:
                    break

        if not course_id:
            print(
                f"[WARN] Impossible de déterminer l'identifiant course pour {rc_dir}",
                file=sys.stderr,
            )
            return False

        h5_json_path = rc_dir / "normalized_h5.json"
        if not h5_json_path.exists():
            fallback = sorted(rc_dir.glob("*_H-5.json"))
            if fallback:
                h5_json_path = fallback[-1]
                print(
                    f"[WARN] normalized_h5.json absent dans {rc_dir}, utilisation de {h5_json_path.name}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[WARN] Aucun snapshot H-5 disponible pour {rc_dir}",
                    file=sys.stderr,
                )

        stats_json_path = rc_dir / "stats_je.json"
        cmd.extend(
            [
                "--course-id",
                course_id,
                "--h5",
                str(h5_json_path),
                "--out",
                str(stats_json_path),
            ]
        )
    else:
        cmd.extend(["--course-dir", str(rc_dir)])

    try:
        result = subprocess.run(cmd, check=False)
    except Exception as exc:  # pragma: no cover - defensive logging
        print(
            f"[WARN] Impossible d'exécuter {script_path.name} pour {rc_dir.name}: {exc}",
            file=sys.stderr,
        )
        return False

    if result.returncode != 0:
        print(
            f"[WARN] {script_path.name} a terminé avec le code {result.returncode} pour {rc_dir.name}",
            file=sys.stderr,
        )
        return False

    return True


def _recover_je_csv_from_stats(
    rc_dir: Path, *, retry_cb: Callable[[], None] | None = None
) -> tuple[bool, bool, bool]:
    """Fetch stats and rebuild the JE CSV if possible.

    Returns a tuple ``(fetch_success, recovered, retry_invoked)`` so the caller
    can decide whether to re-run post fetch checks and whether ``retry_cb`` was
    already invoked inside the helper.
    """

    stats_fetch_success = _run_fetch_script(_FETCH_JE_STATS_SCRIPT, rc_dir)
    if not stats_fetch_success:
        return False, False, False

    if _rebuild_je_csv_from_stats(rc_dir):
        return True, True, False

    if retry_cb is None:
        return True, False, False

    try:
        retry_cb()
    except Exception as exc:  # pragma: no cover - defensive logging
        print(
            f"[WARN] relance enrich_h5 a échoué pour {rc_dir.name}: {exc}",
            file=sys.stderr,
        )
        return True, False, False

    if _rebuild_je_csv_from_stats(rc_dir):
        return True, True, True

    return True, False, True


def _rebuild_je_csv_from_stats(rc_dir: Path) -> bool:
    """Attempt to rebuild ``*_je.csv`` using freshly fetched stats."""

    snap = _snap_prefix(rc_dir)
    if not snap:
        print(
            f"[WARN] Impossible de déterminer le snapshot H-5 pour {rc_dir.name}",
            file=sys.stderr,
        )
        return False

    stats_path = rc_dir / "stats_je.json"
    try:
        stats_payload = json.loads(stats_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"[WARN] stats_je.json introuvable ou invalide dans {rc_dir.name}: {exc}",
            file=sys.stderr,
        )
        return False

    id2name: dict[str, str] = {}
    for candidate in [rc_dir / "partants.json", rc_dir / "normalized_h5.json"]:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mapping = _extract_id2name(payload)
        if mapping:
            id2name = mapping
            break

    if not id2name:
        print(
            f"[WARN] Impossible de reconstruire {snap}_je.csv pour {rc_dir.name}: id2name manquant",
            file=sys.stderr,
        )
        return False

    try:
        _write_je_csv_file(
            rc_dir / f"{snap}_je.csv", id2name=id2name, stats_payload=stats_payload
        )
    except OSError as exc:
        print(
            f"[WARN] Échec d'écriture du CSV J/E pour {rc_dir.name}: {exc}",
            file=sys.stderr,
        )
        return False

    return True


def _regenerate_chronos_csv(rc_dir: Path) -> bool:
    """Attempt to rebuild ``chronos.csv`` from locally available runner data."""

    chronos_path = rc_dir / "chronos.csv"

    def _load_payload(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _extract_runners(payload: dict[str, Any]) -> list[dict[str, Any]]:
        def _clean(items: Any) -> list[dict[str, Any]]:
            cleaned: list[dict[str, Any]] = []
            if isinstance(items, list):
                for runner in items:
                    if not isinstance(runner, dict):
                        continue
                    if (
                        runner.get("id") is None
                        and runner.get("num") is None
                        and runner.get("number") is None
                    ):
                        continue
                    cleaned.append(runner)
            return cleaned

        for key in ("runners", "participants", "partants"):
            if key in payload:
                runners = _clean(payload.get(key))
                if runners:
                    return runners

        for key in ("data", "course", "payload"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                runners = _extract_runners(nested)
                if runners:
                    return runners

        return []

    candidates: list[Path] = []
    partants_path = rc_dir / "partants.json"
    if partants_path.exists():
        candidates.append(partants_path)

    normalized_path = rc_dir / "normalized_h5.json"
    if normalized_path.exists():
        candidates.append(normalized_path)

    candidates.extend(sorted(rc_dir.glob("*_H-5.json"), reverse=True))

    for candidate in candidates:
        payload = _load_payload(candidate)
        if not payload:
            continue
        runners = _extract_runners(payload)
        if not runners:
            continue
        try:
            _write_chronos_csv(chronos_path, runners)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to materialise chronos CSV in %s", rc_dir)
            placeholder_headers = ["num", "chrono", "ok"]
            placeholder_rows = [["", "", 0]]
            _write_minimal_csv(chronos_path, placeholder_headers, placeholder_rows)
        return True

    print(
        f"[WARN] Impossible de régénérer chronos.csv pour {rc_dir.name}: données partants indisponibles",
        file=sys.stderr,
    )
    return False


def _mark_course_unplayable(rc_dir: Path, missing: Iterable[str]) -> dict[str, Any]:
    """Write the abstention marker and emit the canonical abstain log.

    Returns a mapping containing diagnostic information (marker path, message and
    whether the file was written successfully) so callers can enrich their
    ``decision.json`` payload with the same context.
    """

    marker = rc_dir / "UNPLAYABLE.txt"
    marker_message = "non jouable: data JE/chronos manquante"
    missing_items = [str(item) for item in missing if item]
    if missing_items:
        marker_message = f"{marker_message} ({', '.join(missing_items)})"

    details: dict[str, Any] = {
        "marker_path": str(marker),
        "marker_message": marker_message,
        "marker_written": False,
    }

    try:
        marker.write_text(marker_message + "\n", encoding="utf-8")
    except OSError as exc:  # pragma: no cover - filesystem issues are non fatal
        print(
            f"[WARN] impossible d'écrire {marker.name} dans {rc_dir.name}: {exc}",
            file=sys.stderr,
        )
        logger.warning(
            "[H-5] impossible d'écrire le marqueur %s pour %s: %s",
            marker.name,
            rc_dir,
            exc,
        )
    else:
        details["marker_written"] = True
        logger.warning(
            "[H-5] course marquée non jouable (rc=%s, raison=%s)",
            rc_dir.name or "?",
            marker_message,
        )

    label = rc_dir.name or "?"
    print(
        f"[ABSTAIN] Course non jouable (data manquante) – {label}",
        file=sys.stderr,
    )

    return details


def _ensure_h5_artifacts(
    rc_dir: Path,
    *,
    retry_cb: Callable[[], None] | None = None,
    budget: float | None = None,
    phase: str = "H5",
) -> dict[str, Any] | None:
    """Ensure H-5 enrichment produced JE/chronos files or mark course unplayable."""

    outcome = _check_enrich_outputs(rc_dir)
    if outcome is None:
        return None

    missing = list(outcome.get("details", {}).get("missing", []))
    retried = False
    retry_invoked = False

    stats_fetch_success = False
    stats_recovered = False
    stats_retry_invoked = False

    def _refresh_missing_state() -> bool:
        """Re-run the output check and update ``missing`` accordingly."""

        nonlocal outcome, missing
        outcome = _check_enrich_outputs(rc_dir, retry_delay=0.0)
        if outcome is None:
            missing = []
            return True
        missing = list(outcome.get("details", {}).get("missing", []))
        return False

    def _attempt_stats_rebuild(*, allow_without_fetch: bool = False) -> bool:
        """Try rebuilding the JE CSV when stats data appears to be available."""

        nonlocal stats_recovered
        if not missing or not _missing_requires_stats(missing):
            return False

        if stats_recovered and not allow_without_fetch:
            snap = _snap_prefix(rc_dir)
            if snap and (rc_dir / f"{snap}_je.csv").exists():
                return False

        stats_ready = stats_fetch_success
        if not stats_ready:
            stats_path = rc_dir / "stats_je.json"
            stats_ready = stats_path.exists()
            if stats_ready and not allow_without_fetch:
                # ``stats_fetch_success`` guards against rebuilding when the
                # fetch script failed earlier.  When ``allow_without_fetch`` is
                # False we keep that behaviour to avoid consuming stale files
                # left behind by a previous run.
                stats_ready = False

        if not stats_ready:
            return False

        if _rebuild_je_csv_from_stats(rc_dir):
            stats_recovered = True
            if _refresh_missing_state():
                return True
        return False

    if _missing_requires_stats(missing):
        (
            stats_fetch_success,
            stats_recovered,
            stats_retry_invoked,
        ) = _recover_je_csv_from_stats(rc_dir, retry_cb=retry_cb)
        retry_invoked = retry_invoked or stats_retry_invoked
        retried = (
            retried or stats_fetch_success or stats_recovered or stats_retry_invoked
        )
        if stats_retry_invoked and not stats_recovered:
            if _attempt_stats_rebuild(allow_without_fetch=True):
                return None
    if _missing_requires_chronos(missing):
        retried = True
        success = False
        if _FETCH_JE_CHRONO_SCRIPT.exists():
            success = _run_fetch_script(_FETCH_JE_CHRONO_SCRIPT, rc_dir)
        chronos_path = rc_dir / "chronos.csv"
        if not success or not chronos_path.exists():
            _regenerate_chronos_csv(rc_dir)

    if retried:
        if _refresh_missing_state():
            return None
        if _attempt_stats_rebuild():
            return None

    if missing and retry_cb is not None and not retry_invoked:
        try:
            retry_cb()
        except MissingH30SnapshotError as exc:
            existing_missing = list(outcome.get("details", {}).get("missing", []))
            merged_missing = list(dict.fromkeys(str(item) for item in existing_missing))
            if "snapshot-H30" not in merged_missing:
                merged_missing.append("snapshot-H30")
            marker_details = _mark_course_unplayable(rc_dir, merged_missing)
            outcome["status"] = "no-bet"
            outcome["decision"] = "ABSTENTION"
            outcome["reason"] = "data-missing"
            analysis_block = outcome.setdefault("analysis", {})
            if isinstance(analysis_block, dict):
                analysis_block["status"] = "NO_PLAY_DATA_MISSING"
            details_block = outcome.setdefault("details", {})
            if isinstance(details_block, dict):
                details_block["missing"] = merged_missing
                details_block.setdefault("phase", phase)
                details_block["message"] = str(exc)
                details_block.update(marker_details)
            return outcome
        except Exception as exc:  # pragma: no cover - defensive logging
            print(
                f"[WARN] relance enrich_h5 a échoué pour {rc_dir.name}: {exc}",
                file=sys.stderr,
            )
        else:
            if _refresh_missing_state():
                return None
            if _attempt_stats_rebuild(allow_without_fetch=True):
                return None
            missing = list(outcome.get("details", {}).get("missing", []))

    marker_details = _mark_course_unplayable(rc_dir, missing)
    status_label = "NO_PLAY_DATA_MISSING"
    reason_label = "DATA_MISSING"
    if not outcome.get("status"):
        outcome["status"] = "no-bet"
    if not outcome.get("reason"):
        outcome["reason"] = "data-missing"
    analysis_block = outcome.setdefault("analysis", {})
    if isinstance(analysis_block, dict):
        analysis_block["status"] = status_label
    outcome_details = outcome.setdefault("details", {})
    if isinstance(outcome_details, dict):
        outcome_details.update(marker_details)
        outcome_details.setdefault("phase", phase)
        outcome_details.setdefault("reason", reason_label)
        outcome_details.setdefault("status_label", status_label)
    _log_tracking_missing(
        rc_dir,
        status=status_label,
        reason=reason_label,
        phase=phase,
        budget=budget,
    )
    return outcome


def safe_enrich_h5(
    rc_dir: Path,
    *,
    budget: float,
    kelly: float,
) -> tuple[bool, dict[str, Any] | None]:
    """Execute ``enrich_h5`` ensuring JE/chronos data or mark the course out."""

    rc_dir = Path(rc_dir)
    marker = rc_dir / "UNPLAYABLE.txt"
    if marker.exists():
        try:
            marker_message = marker.read_text(encoding="utf-8").strip()
        except OSError:  # pragma: no cover - file removed between exists/read
            marker_message = ""
        details = {"marker": marker_message or None}
        logger.warning(
            "[H-5] course déjà marquée non jouable (rc=%s, marker=%s)",
            rc_dir.name or "?",
            marker_message or "UNPLAYABLE",
        )
        print(
            f"[ABSTAIN] Course déjà marquée non jouable – {rc_dir.name}",
            file=sys.stderr,
        )
        return False, {
            "status": "no-bet",
            "decision": "ABSTENTION",
            "reason": "unplayable-marker",
            "details": details,
        }

    try:
        enrich_h5(rc_dir, budget=budget, kelly=kelly)
    except MissingH30SnapshotError as exc:
        missing = ["snapshot-H30"]
        marker_details = _mark_course_unplayable(rc_dir, missing)
        details: dict[str, Any] = {
            "missing": missing,
            "phase": "H5",
            "message": str(exc),
        }
        details.update(marker_details)
        logger.warning(
            "[H-5] course non jouable faute de snapshot H-30 (rc=%s)",
            rc_dir.name or "?",
        )
        return False, {
            "status": "no-bet",
            "decision": "ABSTENTION",
            "reason": "data-missing",
            "analysis": {"status": "NO_PLAY_DATA_MISSING"},
            "details": details,
        }
    outcome = _ensure_h5_artifacts(
        rc_dir,
        retry_cb=lambda d=rc_dir: enrich_h5(d, budget=budget, kelly=kelly),
        budget=budget,
        phase="H5",
    )
    if outcome is not None:
        return False, outcome
    return True, None


def _execute_h5_chain(
    rc_dir: Path, *, budget: float, kelly: float
) -> tuple[bool, dict[str, Any] | None]:
    """Run the full H-5 enrichment pipeline with fail-safe guards.

    The helper executes ``safe_enrich_h5`` and, when successful, chains the
    downstream p_finale, pipeline and prompt generation steps.
    """

    success, outcome = safe_enrich_h5(rc_dir, budget=budget, kelly=kelly)
    if not success:
        return False, outcome

    build_p_finale(rc_dir, budget=budget, kelly=kelly)
    guard_ok, analysis_payload, guard_outcome = _run_h5_guard_phase(
        rc_dir,
        budget=budget,
    )
    try:
        _write_json_file(rc_dir / "analysis_H5.json", analysis_payload)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning(
            "[H-5] unable to persist analysis_H5.json for %s: %s", rc_dir, exc
        )
    if not guard_ok:
        return False, guard_outcome
    run_pipeline(rc_dir, budget=budget, kelly=kelly)
    build_prompt_from_meta(rc_dir, budget=budget, kelly=kelly)
    return True, None


def export_per_horse_csv(rc_dir: Path) -> Path:
    """Export a per-horse report aggregating probabilities and J/E stats."""

    snap = _snap_prefix(rc_dir)
    if snap is None:
        raise FileNotFoundError("Snapshot H-5 introuvable dans rc_dir")
    je_path = rc_dir / f"{snap}_je.csv"
    chronos_path = rc_dir / "chronos.csv"
    p_finale_path = rc_dir / "p_finale.json"

    # Load data sources
    data = json.loads(p_finale_path.read_text(encoding="utf-8"))
    p_true = {str(k): float(v) for k, v in data.get("p_true", {}).items()}
    id2name = data.get("meta", {}).get("id2name", {})

    def _read_csv(path: Path) -> list[dict[str, str]]:
        text = path.read_text(encoding="utf-8")
        delim = ";" if ";" in text.splitlines()[0] else ","
        return list(csv.DictReader(text.splitlines(), delimiter=delim))

    je_rows = _read_csv(je_path)
    chrono_rows = _read_csv(chronos_path)
    chrono_ok = {
        str(row.get("num") or row.get("id"))
        for row in chrono_rows
        if any(v.strip() for k, v in row.items() if k not in {"num", "id"} and v)
    }

    out_path = rc_dir / "per_horse_report.csv"
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["num", "nom", "p_finale", "j_rate", "e_rate", "chrono_ok"])
        for row in je_rows:
            num = str(row.get("num") or row.get("id") or "")
            nom = row.get("nom") or row.get("name") or id2name.get(num, "")
            writer.writerow(
                [
                    num,
                    nom,
                    p_true.get(num, ""),
                    row.get("j_rate"),
                    row.get("e_rate"),
                    str(num in chrono_ok),
                ]
            )
    return out_path


_DISCOVER_SCRIPT = Path(__file__).resolve().with_name("discover_geny_today.py")


def _load_geny_today_payload() -> dict[str, Any]:
    """Return the JSON payload produced by :mod:`discover_geny_today`.

    The helper centralises the subprocess invocation so that it can easily be
    stubbed in tests.
    """

    raw = subprocess.check_output([sys.executable, str(_DISCOVER_SCRIPT)], text=True)
    return json.loads(raw)


def _normalise_rc_label(label: str | int, prefix: str) -> str:
    """Normalise ``label`` to the canonical ``R``/``C`` format.

    ``label`` may be provided without the leading prefix (``"1"``) or with a
    lowercase variant (``"c3"``). The return value always matches ``R\\d+`` or
    ``C\\d+`` with no leading zero. ``ValueError`` is raised when the label does
    not describe a strictly positive integer.
    """

    text = str(label).strip().upper().replace(" ", "")
    if not text:
        raise ValueError(f"Identifiant {prefix} vide")
    if text.startswith(prefix):
        text = text[len(prefix) :]
    elif text.startswith(prefix[0]):
        text = text[1:]
    if not text.isdigit():
        raise ValueError(f"Identifiant {prefix} invalide: {label!r}")
    number = int(text)
    if number <= 0:
        raise ValueError(f"Identifiant {prefix} invalide: {label!r}")
    return f"{prefix}{number}"


def _normalise_phase(value: str) -> str:
    """Return a canonical phase string (``H30`` or ``H5``)."""

    cleaned = value.strip().upper().replace("-", "").replace(" ", "")
    if cleaned not in {"H30", "H5"}:
        raise ValueError(f"Phase inconnue: {value!r} (attendu H30 ou H5)")
    return cleaned


def _phase_argument(value: str) -> str:
    """Argument parser wrapper that normalises ``value`` to ``H30``/``H5``."""

    try:
        return _normalise_phase(value)
    except ValueError as exc:  # pragma: no cover - handled by argparse
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _resolve_course_id(reunion: str, course: str) -> str:
    """Return the Geny course identifier matching ``reunion``/``course``."""

    payload = _load_geny_today_payload()
    reunion = reunion.upper()
    course = course.upper()
    for meeting in payload.get("meetings", []):
        if str(meeting.get("r", "")).upper() != reunion:
            continue
        for course_info in meeting.get("courses", []):
            label = str(course_info.get("c", "")).upper()
            if label != course:
                continue
            course_id = (
                course_info.get("id_course")
                or course_info.get("course_id")
                or course_info.get("id")
            )
            if course_id is None:
                break
            return str(course_id)
    raise ValueError(f"Course {reunion}{course} introuvable via discover_geny_today")


def _process_single_course(
    reunion: str,
    course: str,
    phase: str,
    data_dir: Path,
    *,
    budget: float,
    kelly: float,
    gcs_prefix: str | None,
) -> dict[str, Any] | None:
    """Fetch and analyse a specific course designated by ``reunion``/``course``."""

    course_id = _resolve_course_id(reunion, course)
    base_dir = ensure_dir(data_dir)
    rc_dir = ensure_dir(base_dir / f"{reunion}{course}")
    write_snapshot_from_geny(course_id, phase, rc_dir)
    outcome: dict[str, Any] | None = None
    pipeline_done = False
    if phase.upper() == "H5":
        pipeline_done, outcome = _execute_h5_chain(
            rc_dir,
            budget=budget,
            kelly=kelly,
        )
        if pipeline_done:
            csv_path = export_per_horse_csv(rc_dir)
            print(f"[INFO] per-horse report écrit: {csv_path}")
            outcome = None
        elif outcome is not None:
            _write_json_file(rc_dir / "decision.json", outcome)
        else:  # pragma: no cover - defensive fallback
            _write_json_file(
                rc_dir / "decision.json",
                {
                    "status": "no-bet",
                    "decision": "ABSTENTION",
                    "reason": "pipeline-error",
                },
            )
    if gcs_prefix is not None:
        _upload_artifacts(rc_dir, gcs_prefix=gcs_prefix)
    return outcome


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


_COURSE_URL_PATTERN = re.compile(r"/(?:course|race)/(\d+)", re.IGNORECASE)


def _extract_labels_from_text(text: str) -> tuple[str, str]:
    """Return ``(reunion, course)`` labels parsed from ``text``."""

    rc_match = re.search(r"R\d+\s*C\d+", text, re.IGNORECASE)
    if rc_match:
        return _derive_rc_parts(rc_match.group(0))

    r_match = re.search(r"R\d+", text, re.IGNORECASE)
    c_match = re.search(r"C\d+", text, re.IGNORECASE)
    r_label = r_match.group(0).upper() if r_match else "R?"
    c_label = c_match.group(0).upper() if c_match else "C?"
    return r_label, c_label


def _process_reunion(
    url: str,
    phase: str,
    data_dir: Path,
    *,
    budget: float,
    kelly: float,
    gcs_prefix: str | None,
) -> None:
    """Fetch ``url`` and run the pipeline for each course of the meeting."""

    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    text_blob = soup.get_text(" ", strip=True)
    context_blob = f"{url} {text_blob}".strip()

    courses: list[tuple[str, str, str, str]] = []
    course_match = _COURSE_URL_PATTERN.search(url)
    if course_match:
        course_id = course_match.group(1)
        r_label, c_label = _extract_labels_from_text(context_blob)
        courses.append((r_label, c_label, course_id, url))
    else:
        r_label, _ = _extract_labels_from_text(context_blob)

        for a in soup.find_all("a"):
            text = a.get_text(strip=True)
            c_match = re.search(r"(C\d+)", text, re.IGNORECASE)
            href = a.get("href", "")
            id_match = re.search(r"(\d+)(?:\.html)?$", href)
            if c_match and id_match:
                course_url = urljoin(url, href)
                courses.append(
                    (r_label, c_match.group(1).upper(), id_match.group(1), course_url)
                )

        if not courses:
            return

    base_dir = ensure_dir(data_dir)
    for r_label, c_label, course_id, course_url in courses:
        rc_dir = ensure_dir(base_dir / f"{r_label}{c_label}")
        try:

            write_snapshot_from_geny(course_id, phase, rc_dir, course_url=course_url)

        except TypeError:

            write_snapshot_from_geny(course_id, phase, rc_dir)

        outcome: dict[str, Any] | None = None
        pipeline_done = False
        if phase.upper() == "H5":
            pipeline_done, outcome = _execute_h5_chain(
                rc_dir,
                budget=budget,
                kelly=kelly,
            )
            if pipeline_done:
                csv_path = export_per_horse_csv(rc_dir)
                print(f"[INFO] per-horse report écrit: {csv_path}")
                outcome = None
            elif outcome is not None:
                _write_json_file(rc_dir / "decision.json", outcome)
            else:  # pragma: no cover - defensive fallback
                _write_json_file(
                    rc_dir / "decision.json",
                    {
                        "status": "no-bet",
                        "decision": "ABSTENTION",
                        "reason": "pipeline-error",
                    },
                )
        if gcs_prefix is not None:
            _upload_artifacts(rc_dir, gcs_prefix=gcs_prefix)


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyse courses du jour enrichie")
    ap.add_argument(
        "--data-dir", default="data", help="Répertoire racine pour les sorties"
    )
    ap.add_argument("--budget", type=float, default=5.0, help="Budget à utiliser")
    ap.add_argument(
        "--kelly", type=float, default=0.5, help="Fraction de Kelly à appliquer"
    )
    ap.add_argument(
        "--from-geny-today",
        action="store_true",
        help="Découvre toutes les réunions FR du jour via Geny et traite H30/H5",
    )
    ap.add_argument(
        "--course-url",
        dest="course_url",
        help="URL ZEturf d'une course unique",
    )
    ap.add_argument(
        "--reunion-url",
        dest="reunion_url",
        help="URL ZEturf d'une réunion (pour scraper plusieurs courses)",
    )
    ap.add_argument(
        "--phase",
        type=_phase_argument,
        help="Fenêtre à traiter (H30 ou H5, avec ou sans tiret)",
    )
    ap.add_argument("--reunion", help="Identifiant de la réunion (ex: R1)")
    ap.add_argument("--course", help="Identifiant de la course (ex: C3)")
    ap.add_argument(
        "--reunions-file",
        help="Fichier JSON listant les réunions à traiter (mode batch)",
    )
    ap.add_argument(
        "--gcs-prefix",
        help="Préfixe GCS racine pour les uploads",
    )
    args = ap.parse_args()

    data_dir = Path(args.data_dir)

    if args.course_url and args.phase:
        rc_match = re.search(r"(R\d+C\d+)", args.course_url)
        if not rc_match:
            print("[ERROR] Impossible d'extraire R#C# de l'URL de la course", file=sys.stderr)
            raise SystemExit(2)
        
        reunion, course = _derive_rc_parts(rc_match.group(1))
        
        print(f"Traitement de la course {reunion}{course} en phase {args.phase}")
        _process_single_course(
            reunion,
            course,
            args.phase,
            data_dir,
            budget=args.budget,
            kelly=args.kelly,
            gcs_prefix=args.gcs_prefix,
        )
        return

    if args.reunion_url and args.phase:
        _process_reunion(
            args.reunion_url,
            args.phase,
            data_dir,
            budget=args.budget,
            kelly=args.kelly,
            gcs_prefix=args.gcs_prefix,
        )
        return

    if args.reunion and args.course and args.phase:
        try:
            reunion_label = _normalise_rc_label(args.reunion, "R")
            course_label = _normalise_rc_label(args.course, "C")
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            raise SystemExit(2)
        _process_single_course(
            reunion_label,
            course_label,
            args.phase,
            Path(args.data_dir),
            budget=args.budget,
            kelly=args.kelly,
            gcs_prefix=args.gcs_prefix,
        )
        return

    parser.error("Veuillez spécifier une action: --course-url, --reunion-url, ou --reunion/--course")

if __name__ == "__main__":
    main()
