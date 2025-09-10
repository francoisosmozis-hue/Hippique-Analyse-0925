"""Utility helpers for working with ZEturf snapshots.

This module only provides a tiny subset of the original project required by
unit tests. The real project also exposes network fetching functions which
are deliberately omitted here."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

def save_json(p: str | Path, obj: Any) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def save_snapshot(label: str, data: Dict[str, Any], outdir: str | Path) -> Path:
    """Save ``data`` under ``outdir`` using a normalised filename."""

    name = "h30.json" if label.upper() == "H30" else "h5.json"
    path = Path(outdir) / name
    save_json(path, data)
    return path


def compute_diff(h30: Dict[str, Any], h5: Dict[str, Any]) -> Dict[str, Any]:
    """Compute odds drift between two snapshots.

    Returns a mapping with keys ``diff``, ``top_steams`` and ``top_drifts``.
    """

    o30 = {r["id"]: float(r["odds"]) for r in h30.get("runners", []) if "odds" in r}
    o05 = {r["id"]: float(r["odds"]) for r in h5.get("runners", []) if "odds" in r}
    rows: List[Dict[str, Any]] = []
    for cid in set(o30) & set(o05):
        delta = o05[cid] - o30[cid]
        rows.append({"id": cid, "cote_h30": o30[cid], "cote_h5": o05[cid], "delta": delta})
    rows = sorted(rows, key=lambda x: x["delta"])
    for i, r in enumerate(rows, 1):
        r["rank_delta"] = i
    top_steams = [r for r in rows if r["delta"] < 0][:3]
    top_drifts = [r for r in reversed(rows) if r["delta"] > 0][:3]
    return {"diff": rows, "top_steams": top_steams, "top_drifts": top_drifts}


__all__ = ["save_json", "save_snapshot", "compute_diff"]
