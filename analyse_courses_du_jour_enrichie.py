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
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

try:  # pragma: no cover - optional dependency in tests
    from scripts.online_fetch_zeturf import write_snapshot_from_geny
except Exception:  # pragma: no cover - used when optional deps are missing

    def write_snapshot_from_geny(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("write_snapshot_from_geny is unavailable")


try:  # pragma: no cover - optional dependency in tests
    from scripts.drive_sync import (
        ensure_folder as drive_ensure_folder,
        push_tree,
    )
except Exception:  # pragma: no cover - used when optional deps are missing

    def drive_ensure_folder(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("drive_ensure_folder is unavailable")

    def push_tree(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("push_tree is unavailable")


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
) -> None:  # pragma: no cover - stub
    raise NotImplementedError("enrich_h5 must be provided by the host application")


def build_p_finale(
    rc_dir: Path, *, budget: float, kelly: float
) -> None:  # pragma: no cover - stub
    raise NotImplementedError("build_p_finale must be provided by the host application")


def run_pipeline(
    rc_dir: Path, *, budget: float, kelly: float
) -> None:  # pragma: no cover - stub
    raise NotImplementedError("run_pipeline must be provided by the host application")


def build_prompt_from_meta(
    rc_dir: Path, *, budget: float, kelly: float
) -> None:  # pragma: no cover - stub
    raise NotImplementedError(
        "build_prompt_from_meta must be provided by the host application"
    )


def _upload_artifacts(rc_dir: Path, *, drive_folder_id: str | None) -> None:
    """Upload ``rc_dir`` contents to Drive under a race-specific subfolder.

    The helper is a no-op when ``drive_folder_id`` is falsy.
    """

    if not drive_folder_id:
        return
    try:
        sub_id = drive_ensure_folder(rc_dir.name, parent=drive_folder_id)
        push_tree(rc_dir, folder_id=sub_id)
    except Exception as exc:  # pragma: no cover - best effort
        print(f"[WARN] Failed to upload {rc_dir}: {exc}")


def _snap_prefix(rc_dir: Path) -> str | None:
    """Return the stem of the H-5 snapshot if available."""

    snap = next(rc_dir.glob("*_H-5.json"), None)
    return snap.stem if snap else None


def _check_enrich_outputs(rc_dir: Path) -> None:
    """Ensure enrich_h5 produced required CSV artefacts."""

    snap = _snap_prefix(rc_dir)
    je_csv = rc_dir / f"{snap}_je.csv" if snap else None
    chronos_csv = rc_dir / "chronos.csv"
    missing = []
    if not je_csv or not je_csv.exists():
        missing.append(f"{snap}_je.csv" if snap else "*_je.csv")
    if not chronos_csv.exists():
        missing.append("chronos.csv")
    if missing:
        print(
            "[ERROR] fichiers manquants après enrich_h5: " + ", ".join(missing),
            file=sys.stderr,
        )
        raise SystemExit(1)


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
    drive_folder_id: str | None,
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
        if phase.upper() == "H5":
            enrich_h5(rc_dir, budget=budget, kelly=kelly)
            _check_enrich_outputs(rc_dir)
            build_p_finale(rc_dir, budget=budget, kelly=kelly)
            run_pipeline(rc_dir, budget=budget, kelly=kelly)
            build_prompt_from_meta(rc_dir, budget=budget, kelly=kelly)
            csv_path = export_per_horse_csv(rc_dir)
            print(f"[INFO] per-horse report écrit: {csv_path}")
        if drive_folder_id:
            _upload_artifacts(rc_dir, drive_folder_id=drive_folder_id)


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
    ap.add_argument("--phase", choices=["H30", "H5"], help="Fenêtre à traiter")
    ap.add_argument(
        "--reunions-file",
        help="Fichier JSON listant les réunions à traiter (mode batch)",
    )
    ap.add_argument(
        "--upload-drive",
        action="store_true",
        help="Upload des artefacts générés sur Google Drive",
    )
    ap.add_argument(
        "--drive-folder-id",
        help="Identifiant du dossier Drive racine pour les uploads",
    )
    args = ap.parse_args()

    drive_folder_id = None
    if args.upload_drive:
        drive_folder_id = args.drive_folder_id or os.environ.get("DRIVE_FOLDER_ID")
        if not drive_folder_id:
            print("[WARN] drive-folder-id manquant, envoi vers Drive ignoré")

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
                if drive_folder_id:
                    cmd.extend(["--upload-drive", "--drive-folder-id", drive_folder_id])
                subprocess.run(cmd, check=True)
        return

    if args.reunion_url and args.phase:
        _process_reunion(
            args.reunion_url,
            args.phase,
            Path(args.data_dir),
            budget=args.budget,
            kelly=args.kelly,
            drive_folder_id=drive_folder_id,
        )
        return

    if args.from_geny_today:
        raw = subprocess.check_output(
            [sys.executable, "discover_geny_today.py"], text=True
        )
        payload = json.loads(raw)
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
                enrich_h5(rc_dir, budget=args.budget, kelly=args.kelly)
                _check_enrich_outputs(rc_dir)
                build_p_finale(rc_dir, budget=args.budget, kelly=args.kelly)
                run_pipeline(rc_dir, budget=args.budget, kelly=args.kelly)
                build_prompt_from_meta(rc_dir, budget=args.budget, kelly=args.kelly)
                csv_path = export_per_horse_csv(rc_dir)
                print(f"[INFO] per-horse report écrit: {csv_path}")
                if drive_folder_id:
                    _upload_artifacts(rc_dir, drive_folder_id=drive_folder_id)
        print("[DONE] from-geny-today pipeline terminé.")
        return

    # Fall back to original behaviour: simply run the pipeline on ``data_dir``
    run_pipeline(Path(args.data_dir), budget=args.budget, kelly=args.kelly)
    if drive_folder_id:
        _upload_artifacts(Path(args.data_dir), drive_folder_id=drive_folder_id)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
