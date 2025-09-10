#!/usr/bin/env python3
"""Post-course processing utilities.

This script reads the official arrival of a race and updates the tickets
with the realised gains and ROI.  It also produces convenient artefacts
for bookkeeping such as a CSV summary line and the command required to
update the tracking spreadsheet.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, List, Dict, Any


def _load_json(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _save_json(path: str | Path, obj: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_text(path: str | Path, txt: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt, encoding="utf-8")


def _compute_gains(tickets: Iterable[Dict[str, Any]], winners: List[str]) -> tuple[float, float, float]:
    """Update ``tickets`` in place with realised gains and return aggregates.

    Parameters
    ----------
    tickets:
        Iterable of ticket dictionaries containing at least ``id``,
        ``stake`` and ``odds`` fields.
    winners:
        List of runner identifiers that finished in a winning position.

    Returns
    -------
    tuple
        ``(total_gain, total_stake, roi)`` where ``roi`` is the return on
        investment computed as ``(gain - stake) / stake``.
    """

    total_stake = 0.0
    total_gain = 0.0
    winner_set = {str(w) for w in winners}
    for t in tickets:
        stake = float(t.get("stake", 0.0))
        odds = float(t.get("odds", 0.0))
        gain = stake * odds if str(t.get("id")) in winner_set else 0.0
        t["gain_reel"] = round(gain, 2)
        total_stake += stake
        total_gain += gain
    roi = (total_gain - total_stake) / total_stake if total_stake else 0.0
    return total_gain, total_stake, roi


def main() -> None:
    ap = argparse.ArgumentParser(description="Post-course processing")
    ap.add_argument("--arrivee", required=True, help="Path to official arrival JSON")
    ap.add_argument("--tickets", required=True, help="Path to tickets.json to update")
    ap.add_argument("--outdir", default=None, help="Output directory (defaults to tickets directory)")
    ap.add_argument(
        "--excel",
        default="modele_suivi_courses_hippiques.xlsx",
        help="Excel workbook for update command",
    )
    args = ap.parse_args()

    arrivee_data = _load_json(args.arrivee)
    tickets_data = _load_json(args.tickets)

    winners = [str(x) for x in arrivee_data.get("result", [])[:1]]
    total_gain, total_stake, roi = _compute_gains(tickets_data.get("tickets", []), winners)
    tickets_data["roi_reel"] = roi
    _save_json(args.tickets, tickets_data)

    outdir = Path(args.outdir or Path(args.tickets).parent)
    meta = tickets_data.get("meta", {})
    arrivee_out = {
        "rc": arrivee_data.get("rc") or meta.get("rc"),
        "date": arrivee_data.get("date") or meta.get("date"),
        "result": winners,
        "gains": total_gain,
        "roi_reel": roi,
    }
    _save_json(outdir / "arrivee.json", arrivee_out)

    ligne = (
        f'{meta.get("rc", "")};{meta.get("hippodrome", "")};{meta.get("date", "")};'
        f'{meta.get("discipline", "")};{total_stake:.2f};{roi:.4f};{meta.get("model", meta.get("MODEL", ""))}'
    )
    _save_text(outdir / "ligne_resultats.csv", "R/C;hippodrome;date;discipline;mises;ROI_reel;model\n" + ligne + "\n")

    cmd = (
        f'python update_excel_with_results.py '
        f'--excel "{args.excel}" '
        f'--arrivee "{Path(args.arrivee)}" '
        f'--tickets "{Path(args.tickets)}"\n'
    )
    _save_text(outdir / "cmd_update_excel.txt", cmd)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
