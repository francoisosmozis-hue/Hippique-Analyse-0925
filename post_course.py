#!/usr/bin/env python3
"""Post-course processing utilities.

This script reads the official arrival of a race and updates the tickets
with the realised gains and ROI.  It also produces convenient artefacts
for bookkeeping such as a CSV summary line and the command required to
update the tracking spreadsheet.  The number of paid positions can be
controlled via the ``--places`` option (defaults to one winner).
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict

from post_course_payload import (
    CSV_HEADER,
    apply_summary_to_ticket_container,
    build_payload,
    compute_post_course_summary,
    format_csv_line,
)


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


def main() -> None:
    ap = argparse.ArgumentParser(description="Post-course processing")
    ap.add_argument("--arrivee", required=True, help="Path to official arrival JSON")
    ap.add_argument("--tickets", required=True, help="Path to tickets.json to update")
    ap.add_argument(
        "--outdir",
        default=None,
        help="Output directory (defaults to tickets directory)",
    )
    ap.add_argument(
        "--excel",
        default="modele_suivi_courses_hippiques.xlsx",
        help="Excel workbook for update command",
    )
    ap.add_argument(
        "--places",
        type=int,
        default=1,
        help="Nombre de positions rémunérées à prendre en compte",
    )
    args = ap.parse_args()

    arrivee_path = Path(args.arrivee)
    tickets_path = Path(args.tickets)
    tickets_data = _load_json(tickets_path)

    if not arrivee_path.exists():
        outdir = Path(args.outdir or tickets_path.parent)
        meta = tickets_data.get("meta", {})
        today = date.today().isoformat()
        arrivee_out = {"status": "missing", "rc": meta.get("rc"), "date": today}
        _save_json(outdir / "arrivee.json", arrivee_out)
        _save_text(
            outdir / "arrivee.csv",
            "status;rc;date\n"
            f"{arrivee_out['status']};{arrivee_out.get('rc', '')};{arrivee_out['date']}\n",
        )
        print(f"Arrivee file not found, produced minimal outputs in {outdir}")
        return

    arrivee_data = _load_json(arrivee_path)

    winners = [str(x) for x in arrivee_data.get("result", [])[: args.places]]
    summary = compute_post_course_summary(tickets_data.get("tickets", []), winners)
    apply_summary_to_ticket_container(tickets_data, summary)
    _save_json(args.tickets, tickets_data)

    outdir = Path(args.outdir or Path(args.tickets).parent)
    payload = build_payload(
        meta=meta,
        arrivee=arrivee_data,
        tickets=tickets_data.get("tickets", []),
        summary=summary,
        winners=winners,
        ev_estimees=tickets_data.get("ev"),
        places=args.places,
    )
    payload_path = outdir / "arrivee.json"
    _save_json(payload_path, payload)

    ligne = format_csv_line(meta, summary)
    _save_text(
        outdir / "ligne_resultats.csv",
        CSV_HEADER + "\n" + ligne + "\n",
    )

    cmd = (
        f"python update_excel_with_results.py "
        f'--excel "{args.excel}" '
        f'--payload "{payload_path}"\n'
    )
    _save_text(outdir / "cmd_update_excel.txt", cmd)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
