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
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import requests
from bs4 import BeautifulSoup

from scripts.gcs_utils import disabled_reason, is_gcs_enabled
from scripts.online_fetch_zeturf import normalize_snapshot
from scripts.fetch_je_stats import collect_stats

import pipeline_run

USE_GCS = is_gcs_enabled()

try:  # pragma: no cover - optional dependency in tests
    from scripts.online_fetch_zeturf import write_snapshot_from_geny
except Exception:  # pragma: no cover - used when optional deps are missing
    
    def write_snapshot_from_geny(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("write_snapshot_from_geny is unavailable")


if USE_GCS:
    try:  # pragma: no cover - optional dependency in tests
        from scripts.drive_sync import (
            build_remote_path as gcs_build_remote_path,
            push_tree,
        )
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


# --- RÈGLES ANTI-COTES FAIBLES (SP min 4/1 ; CP somme > 6/1) -----------------
MIN_SP_DEC_ODDS = 5.0        # 4/1 = 5.0
MIN_CP_SUM_DEC = 8.0         # (o1-1)+(o2-1) > 6  <=> (o1+o2) > 8.0


def _write_json_file(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
                    horses = (
                        market.get("horses")
                        if isinstance(market, dict)
                        else []
                    )
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
                    horses = (
                        market.get("horses")
                        if isinstance(market, dict)
                        else []
                    )
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
                if (odds_list[0] + odds_list[1]) > MIN_CP_SUM_DEC:
                    kept.append(ticket)
                else:
                    _append_note(
                        "CP retiré: somme des cotes décimales"
                        f" {odds_list[0]:.2f}+{odds_list[1]:.2f} ≤ 8.00 (règle > 6/1 cumulés)."
                    )
            else:
                _append_note("CP retiré: cotes manquantes (règle >6/1 non vérifiable).")
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


def enrich_h5(
    rc_dir: Path, *, budget: float, kelly: float
) -> None:
    """Prepare all artefacts required for the H-5 pipeline.

    The function normalises the latest H-30/H-5 snapshots, extracts odds maps,
    fetches jockey/entraineur statistics and materialises CSV companions used
    by downstream tooling.  When the H-30 snapshot is unavailable the H-5 odds
    are reused as a conservative fallback which still allows the analysis to
    run (the drift will simply be null).
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
        # Without H-30 we reuse H-5 odds so the pipeline can still proceed.
        print(
            f"[WARN] Snapshot H-30 manquant dans {rc_dir}, réutilisation des cotes H-5",
            file=sys.stderr,
        )
        h30_payload = dict(h5_payload)
        h30_normalised = dict(h5_normalised)

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
        raise ValueError("Impossible de déterminer l'identifiant course pour les stats J/E")
    coverage, mapped = collect_stats(course_id, h5_path=rc_dir / "normalized_h5.json")
    stats_payload: dict[str, Any] = {"coverage": coverage}
    stats_payload.update(mapped)
    _write_json_file(stats_path, stats_payload)

    snap_stem = h5_raw_path.stem
    id2name = _extract_id2name(partants_payload)
    _write_je_csv_file(rc_dir / f"{snap_stem}_je.csv", id2name=id2name, stats_payload=mapped)

    chronos_path = rc_dir / "chronos.csv"
    _write_chronos_csv(chronos_path, partants_payload.get("runners", []))


def build_p_finale(
    rc_dir: Path, *, budget: float, kelly: float
) -> None:
    """Run the ticket allocation pipeline and persist ``p_finale.json``."""

    rc_dir = Path(rc_dir)
    _run_single_pipeline(rc_dir, budget=budget)


def run_pipeline(
    rc_dir: Path, *, budget: float, kelly: float
) -> None:
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


def build_prompt_from_meta(
    rc_dir: Path, *, budget: float, kelly: float
) -> None:
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
        "  - Interdiction SP < 4/1 (placé décimal < 5.0). Couplé Placé autorisé uniquement si cote1 + cote2 > 8.0 (équiv. somme > 6/1)."
    )

    if isinstance(ev, dict) and ev:
        global_ev = ev.get("global")
        roi = ev.get("roi_global")
        prompt_lines.append(
            "EV globale : "
            + (f"{float(global_ev):.2f}" if isinstance(global_ev, (int, float)) else "n/a")
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
        _write_je_csv_file(rc_dir / f"{snap}_je.csv", id2name=id2name, stats_payload=stats_payload)
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
                    if runner.get("id") is None and runner.get("num") is None and runner.get(
                        "number"
                    ) is None:
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
        _write_chronos_csv(chronos_path, runners)
        return True

    print(
        f"[WARN] Impossible de régénérer chronos.csv pour {rc_dir.name}: données partants indisponibles",
        file=sys.stderr,
    )
    return False


def _mark_course_unplayable(rc_dir: Path, missing: Iterable[str]) -> None:
    """Write the abstention marker and emit the canonical abstain log."""

    marker = rc_dir / "UNPLAYABLE.txt"
    marker_message = "non jouable: data JE/chronos manquante"
    missing_items = [str(item) for item in missing if item]
    if missing_items:
        marker_message = f"{marker_message} ({', '.join(missing_items)})"

    try:
        marker.write_text(marker_message + "\n", encoding="utf-8")
    except OSError as exc:  # pragma: no cover - filesystem issues are non fatal
        print(
            f"[WARN] impossible d'écrire {marker.name} dans {rc_dir.name}: {exc}",
            file=sys.stderr,
        )

    label = rc_dir.name or "?"
    print(
        f"[ABSTAIN] Course marquée non jouable (data manquante) – {label}",
        file=sys.stderr,
    )


def _ensure_h5_artifacts(
    rc_dir: Path, *, retry_cb: Callable[[], None] | None = None
) -> dict[str, Any] | None:
    """Ensure H-5 enrichment produced JE/chronos files or mark course unplayable."""

    outcome = _check_enrich_outputs(rc_dir, retry_cb=retry_cb)
    if outcome is None:
        return None

    missing = list(outcome.get("details", {}).get("missing", []))
    retried = False

    if _missing_requires_stats(missing):
        retried = True
        stats_success = _run_fetch_script(_FETCH_JE_STATS_SCRIPT, rc_dir)
        if stats_success:
            rebuilt = _rebuild_je_csv_from_stats(rc_dir)
            if not rebuilt and retry_cb is not None:
                try:
                    retry_cb()
                except Exception as exc:  # pragma: no cover - defensive logging
                    print(
                        f"[WARN] relance enrich_h5 a échoué pour {rc_dir.name}: {exc}",
                        file=sys.stderr,
                    )
    if _missing_requires_chronos(missing):
        retried = True
        success = False
        if _FETCH_JE_CHRONO_SCRIPT.exists():
            success = _run_fetch_script(_FETCH_JE_CHRONO_SCRIPT, rc_dir)
        chronos_path = rc_dir / "chronos.csv"
        if not success or not chronos_path.exists():
            _regenerate_chronos_csv(rc_dir)
            
    if retried:
        outcome = _check_enrich_outputs(rc_dir, retry_delay=0.0)
        if outcome is None:
            return None
        missing = list(outcome.get("details", {}).get("missing", []))

    _mark_course_unplayable(rc_dir, missing)
    return outcome


def safe_enrich_h5(
    rc_dir: Path,
    *,
    budget: float,
    kelly: float,
) -> tuple[bool, dict[str, Any] | None]:
    """Execute ``enrich_h5`` ensuring JE/chronos data or mark the course out."""

    enrich_h5(rc_dir, budget=budget, kelly=kelly)
    outcome = _ensure_h5_artifacts(
        rc_dir,
        retry_cb=lambda d=rc_dir: enrich_h5(d, budget=budget, kelly=kelly),
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

    r_match = re.search(r"(R\d+)", url)
    r_label = r_match.group(1) if r_match else "R?"

    courses: list[tuple[str, str]] = []
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        c_match = re.search(r"(C\d+)", text)
        href = a.get("href", "")
        id_match = re.search(r"(\d+)(?:\.html)?$", href)
        if c_match and id_match:
            courses.append((c_match.group(1), id_match.group(1)))

    base_dir = ensure_dir(data_dir)
    for c_label, course_id in courses:
        rc_dir = ensure_dir(base_dir / f"{r_label}{c_label}")
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
    ap.add_argument("--budget", type=float, default=100.0, help="Budget à utiliser")
    ap.add_argument(
        "--kelly", type=float, default=1.0, help="Fraction de Kelly à appliquer"
    )
    ap.add_argument(
        "--from-geny-today",
        action="store_true",
        help="Découvre toutes les réunions FR du jour via Geny et traite H30/H5",
    )
    ap.add_argument("--reunion-url", help="URL ZEturf d'une réunion")
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
        "--upload-gcs",
        action="store_true",
        help="Upload des artefacts générés sur Google Cloud Storage",
    )
    ap.add_argument(
        "--upload-drive",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    ap.add_argument(
        "--gcs-prefix",
        help="Préfixe GCS racine pour les uploads",
    )
    ap.add_argument(
        "--drive-folder-id",
        dest="gcs_prefix",
        help=argparse.SUPPRESS,
    )
    args = ap.parse_args()

    gcs_prefix = None
    if args.upload_gcs or args.upload_drive:
        if args.gcs_prefix is not None:
            gcs_prefix = args.gcs_prefix
        else:
            gcs_prefix = os.environ.get("GCS_PREFIX")
        if gcs_prefix is None:
            print("[WARN] gcs-prefix manquant, envoi vers GCS ignoré")

    if args.reunions_file:
        script = Path(__file__).resolve()
        data = json.loads(Path(args.reunions_file).read_text(encoding="utf-8"))
        for reunion in data.get("reunions", []):
            url_zeturf = reunion.get("url_zeturf")
            if not url_zeturf:
                continue
            for phase in ["H30", "H5"]:
                cmd = [
                    sys.executable,
                    str(script),
                    "--reunion-url",
                    url_zeturf,
                    "--phase",
                    phase,
                    "--data-dir",
                    args.data_dir,
                    "--budget",
                    str(args.budget),
                    "--kelly",
                    str(args.kelly),
                ]
                if gcs_prefix is not None:
                    cmd.append("--upload-gcs")
                    cmd.extend(["--gcs-prefix", gcs_prefix])
                subprocess.run(cmd, check=True)
        return

    if args.reunion or args.course:
        if not (args.reunion and args.course and args.phase):
            print(
                "[ERROR] --reunion, --course et --phase doivent être utilisés ensemble",
                file=sys.stderr,
            )
            raise SystemExit(2)
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
            gcs_prefix=gcs_prefix,
        )
        return

    if args.reunion_url and args.phase:
        _process_reunion(
            args.reunion_url,
            args.phase,
            Path(args.data_dir),
            budget=args.budget,
            kelly=args.kelly,
            gcs_prefix=gcs_prefix,
        )
        return

    if args.from_geny_today:
        payload = _load_geny_today_payload()
        meetings = payload.get("meetings", [])
        base_dir = ensure_dir(Path(args.data_dir))
        for meeting in meetings:
            r_label = meeting.get("r", "")
            for course in meeting.get("courses", []):
                c_label = course.get("c", "")
                rc_dir = ensure_dir(base_dir / f"{r_label}{c_label}")
                course_id = course.get("id_course")
                if not course_id:
                    continue
                write_snapshot_from_geny(course_id, "H30", rc_dir)
                write_snapshot_from_geny(course_id, "H5", rc_dir)
                success, decision = safe_enrich_h5(
                    rc_dir, budget=args.budget, kelly=args.kelly
                )
                if success:
                    build_p_finale(rc_dir, budget=args.budget, kelly=args.kelly)
                    run_pipeline(rc_dir, budget=args.budget, kelly=args.kelly)
                    build_prompt_from_meta(rc_dir, budget=args.budget, kelly=args.kelly)
                    csv_path = export_per_horse_csv(rc_dir)
                    print(f"[INFO] per-horse report écrit: {csv_path}")
                else:
                    if decision is not None:
                        _write_json_file(rc_dir / "decision.json", decision)
                if gcs_prefix is not None:
                    _upload_artifacts(rc_dir, gcs_prefix=gcs_prefix)
        print("[DONE] from-geny-today pipeline terminé.")
        return

    # Fall back to original behaviour: simply run the pipeline on ``data_dir``
    run_pipeline(Path(args.data_dir), budget=args.budget, kelly=args.kelly)
    if gcs_prefix is not None:
        _upload_artifacts(Path(args.data_dir), gcs_prefix=gcs_prefix)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
