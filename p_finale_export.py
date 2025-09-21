#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utilities to export pipeline artefacts in a post-results friendly layout."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator


JsonDict = dict[str, Any]


def _save_json(path: str | Path, obj: Any) -> None:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_text(path: str | Path, txt: str) -> None:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(txt, encoding="utf-8")


def _load_json(path: str | Path) -> JsonDict:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _normalise_rc(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().upper()
    if not text:
        return None
    return text


def _iter_pipeline_exports(root: Path) -> Iterator[tuple[Path, JsonDict]]:
    for path in root.rglob("p_finale.json"):
        try:
            data = _load_json(path)
        except Exception as exc:  # pragma: no cover - defensive guard
            print(f"[WARN] Ignoring {path}: {exc}", file=sys.stderr)
            continue
        meta = data.get("meta")
        rc = None
        if isinstance(meta, dict):
            rc = _normalise_rc(meta.get("rc"))
        if not rc:
            rc = _normalise_rc(path.parent.name)
        if not rc:
            print(f"[WARN] Could not determine RC for {path}", file=sys.stderr)
            continue
        data.setdefault("meta", {})
        data["meta"]["rc"] = rc
        yield path, data


@dataclass
class ExportEntry:
    rc: str
    path: Path
    data: JsonDict
    mtime: float


def _collect_exports(root: Path) -> dict[str, list[ExportEntry]]:
    mapping: dict[str, list[ExportEntry]] = {}
    for path, data in _iter_pipeline_exports(root):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        rc = data["meta"].get("rc")
        if not isinstance(rc, str):
            continue
        entry = ExportEntry(rc=rc, path=path, data=data, mtime=mtime)
        mapping.setdefault(rc, []).append(entry)
    return mapping


def _build_arrivee_payload(
    base_entry: JsonDict | None,
    *,
    rc: str,
    meta: JsonDict,
    context: JsonDict | None,
) -> JsonDict:
    arrivee: JsonDict = {}
    if isinstance(base_entry, dict):
        arrivee.update(base_entry)
    arrivee.setdefault("rc", rc)
    arr_meta = arrivee.get("meta") if isinstance(arrivee.get("meta"), dict) else {}
    if not isinstance(arr_meta, dict):
        arr_meta = {}
    arr_meta.setdefault("rc", rc)
    if "date" in meta and meta["date"]:
        arr_meta.setdefault("date", meta["date"])
    for key in ("hippodrome", "discipline", "model"):
        value = meta.get(key)
        if value:
            arr_meta.setdefault(key, value)
    arrivee["meta"] = arr_meta
    if "result" in arrivee and isinstance(arrivee["result"], Iterable):
        arrivee["result"] = [str(item) for item in arrivee["result"] if item not in (None, "")]
    else:
        arrivee["result"] = []
    if context:
        for key in ("generated_at", "source"):
            value = context.get(key)
            if value and key not in arrivee:
                arrivee[key] = value
    return arrivee


def export(
    outdir: str | Path,
    p_finale: JsonDict,
    *,
    cfg: JsonDict | None = None,
    arrivee: JsonDict | None = None,
) -> Path:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    meta = p_finale.get("meta") if isinstance(p_finale.get("meta"), dict) else {}
    tickets = p_finale.get("tickets") if isinstance(p_finale.get("tickets"), list) else []
    ev = p_finale.get("ev") if isinstance(p_finale.get("ev"), dict) else {}
    p_true = p_finale.get("p_true")

    _save_json(out / "p_finale.json", p_finale)

    payload: JsonDict = {
        "meta": meta,
        "tickets": tickets,
        "ev": ev,
    }
    if isinstance(p_true, dict):
        payload["p_true"] = p_true
    if cfg:
        budget = cfg.get("BUDGET_TOTAL")
        if budget is not None:
            payload["budget_total"] = budget
        ratios = {
            "sp": cfg.get("SP_RATIO"),
            "combo": cfg.get("COMBO_RATIO"),
        }
        if any(value is not None for value in ratios.values()):
            payload["ratios"] = ratios
    _save_json(out / "tickets.json", payload)

    total = sum(float(t.get("stake", 0) or 0.0) for t in tickets)
    ligne = (
        f'{meta.get("rc", "")};{meta.get("hippodrome", "")};{meta.get("date", "")};'
        f'{meta.get("discipline", "")};{total:.2f};{float(ev.get("global", 0) or 0):.4f};'
        f'{meta.get("model", meta.get("MODEL", ""))}'
    )
    _save_text(
        out / "ligne.csv",
        "R/C;hippodrome;date;discipline;mises;EV_globale;model\n" + ligne + "\n",
    )

    excel_path = None
    if cfg:
        excel_path = cfg.get("EXCEL_PATH")
    if not excel_path:
        excel_path = "modele_suivi_courses_hippiques.xlsx"

    arrivee_payload = arrivee if arrivee is not None else {
        "rc": meta.get("rc"),
        "date": meta.get("date"),
        "result": [],
        "gains": 0.0,
        "note": "placeholder",
    }
    _save_json(out / "arrivee_officielle.json", arrivee_payload)

    cmd = (
        "python update_excel_with_results.py "
        f'--excel "{excel_path}" '
        f'--arrivee "{out / "arrivee_officielle.json"}" '
        f'--tickets "{out / "tickets.json"}"\n'
    )
    _save_text(out / "cmd_update_excel.txt", cmd)
    return out


def _export_single(outputs_dir: Path, excel_path: str | None) -> Path:
    p_finale_path = outputs_dir / "p_finale.json"
    if not p_finale_path.exists():
        raise SystemExit(f"p_finale.json introuvable dans {outputs_dir}")
    data = _load_json(p_finale_path)
    cfg = {"EXCEL_PATH": excel_path} if excel_path else {"EXCEL_PATH": None}
    if not cfg["EXCEL_PATH"]:
        cfg.pop("EXCEL_PATH")
    out = export(outputs_dir, data, cfg=cfg)
    print(f"[export] Artefacts mis à jour dans {out}")
    return out


def _export_from_arrivals(
    arrivals_path: Path,
    analyses_dir: Path,
    out_dir: Path,
    *,
    excel_path: str | None = None,
) -> list[Path]:
    arrivals_payload = _load_json(arrivals_path)
    arrivees = arrivals_payload.get("arrivees") if isinstance(arrivals_payload, dict) else []
    if not isinstance(arrivees, list):
        raise SystemExit("Le fichier d'arrivées doit contenir une liste 'arrivees'")
    exports = _collect_exports(analyses_dir)
    if not exports:
        print(f"[WARN] Aucun p_finale.json trouvé sous {analyses_dir}", file=sys.stderr)

    results: list[Path] = []
    context = {k: v for k, v in arrivals_payload.items() if k != "arrivees"}
    for item in arrivees:
        if not isinstance(item, dict):
            continue
        rc = _normalise_rc(item.get("rc"))
        if not rc:
            meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            rc = _normalise_rc(meta.get("rc"))
        if not rc:
            print(f"[WARN] Arrivée sans RC identifiable: {item}", file=sys.stderr)
            continue
        entries = exports.get(rc)
        if not entries:
            print(f"[WARN] Aucun export trouvé pour {rc} sous {analyses_dir}", file=sys.stderr)
            continue
        entry = max(entries, key=lambda e: e.mtime)
        meta = entry.data.get("meta") if isinstance(entry.data.get("meta"), dict) else {}
        race_date = meta.get("date")
        if not race_date:
            arr_meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
            race_date = arr_meta.get("date") or arrivals_path.stem.split("_")[0]
        dest = out_dir / str(race_date or "unknown") / rc
        cfg: JsonDict = {"EXCEL_PATH": excel_path} if excel_path else {}
        arrivee_payload = _build_arrivee_payload(item, rc=rc, meta=meta, context=context)
        out_path = export(dest, entry.data, cfg=cfg, arrivee=arrivee_payload)
        results.append(out_path)
        print(f"[export] {rc}: {entry.path} → {out_path}")
    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exporter les tickets/p_finale pour le post-traitement")
    parser.add_argument("--outputs-dir", help="Répertoire contenant p_finale.json à convertir")
    parser.add_argument("--arrivees", help="Fichier JSON des arrivées consolidées")
    parser.add_argument("--analyses-dir", default="data/analyses", help="Racine des analyses H-5")
    parser.add_argument("--out-dir", default="data/results", help="Destination des exports")
    parser.add_argument(
        "--excel",
        default="modele_suivi_courses_hippiques.xlsx",
        help="Classeur Excel pour la commande d'update",
    )
    args = parser.parse_args(argv)
    if not args.outputs_dir and not args.arrivees:
        parser.error("--outputs-dir ou --arrivees doit être fourni")
    if args.outputs_dir and args.arrivees:
        parser.error("--outputs-dir est exclusif avec --arrivees")
    if args.arrivees and not args.analyses_dir:
        parser.error("--analyses-dir requis avec --arrivees")
    if args.arrivees and not args.out_dir:
        parser.error("--out-dir requis avec --arrivees")
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    excel_path = args.excel
    if args.outputs_dir:
        _export_single(Path(args.outputs_dir), excel_path)
        return
    _export_from_arrivals(
        Path(args.arrivees),
        Path(args.analyses_dir),
        Path(args.out_dir),
        excel_path=excel_path,
    )


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
