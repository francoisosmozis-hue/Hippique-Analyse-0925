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


def _compute_gains(
    tickets: Iterable[Dict[str, Any]],
    winners: List[str],
) -> tuple[float, float, float, float, float, float, float, float, float]:
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
        ``(total_gain, total_stake, roi, ev_total, diff_ev_total, result_mean, roi_ticket_mean, brier_total, brier_mean)``
        where ``roi`` is the overall return on investment computed as
        ``(gain - stake) / stake``.
    """

    total_stake = 0.0
    total_gain = 0.0
    total_ev = 0.0
    total_diff_ev = 0.0
    total_result = 0.0
    total_roi_ticket = 0.0
    total_brier = 0.0
    n_tickets = 0
    winner_set = {str(w) for w in winners}
    for t in tickets:
        stake = float(t.get("stake", 0.0))
        odds = float(t.get("odds", 0.0))
        gain = stake * odds if str(t.get("id")) in winner_set else 0.0
        t["gain_reel"] = round(gain, 2)
        t["result"] = 1 if gain else 0
        roi_reel = (gain - stake) / stake if stake else 0.0
        t["roi_reel"] = round(roi_reel, 4)
        
        total_stake += stake
        total_gain += gain

        total_result += t["result"]
        total_roi_ticket += roi_reel
        n_tickets += 1
        
        ev = None
        if "ev" in t:
            ev = float(t.get("ev", 0.0))
        elif "p" in t:
            p = float(t.get("p", 0.0))
            ev = stake * (p * (odds - 1) - (1 - p))
        if ev is not None:
            diff_ev = gain - ev
            t["ev_ecart"] = round(diff_ev, 2)
            total_ev += ev
            total_diff_ev += diff_ev

        if "p" in t:
            p = float(t.get("p", 0.0))
            brier = (t["result"] - p) ** 2
            t["brier"] = round(brier, 4)
            total_brier += brier


    roi = (total_gain - total_stake) / total_stake if total_stake else 0.0
    result_mean = total_result / n_tickets if n_tickets else 0.0
    roi_ticket_mean = total_roi_ticket / n_tickets if n_tickets else 0.0
    brier_mean = total_brier / n_tickets if n_tickets else 0.0
    return (
        total_gain,
        total_stake,
        roi,
        total_ev,
        total_diff_ev,
        result_mean,
        roi_ticket_mean,
        total_brier,
        brier_mean,
    )


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
    ap.add_argument(
        "--places",
        type=int,
        default=1,
        help="Nombre de positions rémunérées à prendre en compte",
    )
    args = ap.parse_args()

    arrivee_data = _load_json(args.arrivee)
    tickets_data = _load_json(args.tickets)

    winners = [str(x) for x in arrivee_data.get("result", [])[: args.places]]
    (
        total_gain,
        total_stake,
        roi,
        ev_total,
        diff_ev_total,
        result_moyen,
        brier_total,
        brier_moyen,
        roi_reel_moyen,
    ) = _compute_gains(tickets_data.get("tickets", []), winners)
    tickets_data["roi_reel"] = roi
    tickets_data["result_moyen"] = result_moyen
    tickets_data["roi_reel_moyen"] = roi_reel_moyen
    tickets_data["brier_total"] = brier_total
    tickets_data["brier_moyen"] = brier_moyen
    _save_json(args.tickets, tickets_data)

    outdir = Path(args.outdir or Path(args.tickets).parent)
    meta = tickets_data.get("meta", {})
    arrivee_out = {
        "rc": arrivee_data.get("rc") or meta.get("rc"),
        "date": arrivee_data.get("date") or meta.get("date"),
        "result": winners,
        "gains": total_gain,
        "roi_reel": roi,
        "result_moyen": result_moyen,
        "roi_reel_moyen": roi_reel_moyen,
        "brier_total": brier_total,
        "brier_moyen": brier_moyen,
        "ev_total": ev_total,
        "ev_ecart_total": diff_ev_total,
    }
    _save_json(outdir / "arrivee.json", arrivee_out)

    ligne = (
        f'{meta.get("rc", "")};{meta.get("hippodrome", "")};{meta.get("date", "")};'
        f'{meta.get("discipline", "")};{total_stake:.2f};{roi:.4f};'
        f'{result_moyen:.4f};{roi_reel_moyen:.4f};'
        f'{brier_total:.4f};{brier_moyen:.4f};'
        f'{ev_total:.2f};{diff_ev_total:.2f};'
        f'{meta.get("model", meta.get("MODEL", ""))}'
    )
    _save_text(
        outdir / "ligne_resultats.csv",
        (
            "R/C;hippodrome;date;discipline;mises;ROI_reel;result_moyen;"
            "ROI_reel_moyen;Brier_total;Brier_moyen;EV_total;EV_ecart;model\n" + ligne + "\n"
        ),
    )
    
    cmd = (
        f'python update_excel_with_results.py '
        f'--excel "{args.excel}" '
        f'--arrivee "{Path(args.arrivee)}" '
        f'--tickets "{Path(args.tickets)}"\n'
    )
    _save_text(outdir / "cmd_update_excel.txt", cmd)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
