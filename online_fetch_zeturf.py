"""Tools for fetching meetings from Zeturf and computing odds drifts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List

import requests
import yaml
from bs4 import BeautifulSoup


GENY_FALLBACK_URL = "https://www.geny.com/reunions-courses-pmu"


def _fetch_from_geny() -> Dict[str, Any]:
    """Scrape meetings from Geny when the Zeturf API is unavailable."""
    resp = requests.get(GENY_FALLBACK_URL, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    today = dt.date.today().isoformat()
    meetings: List[Dict[str, Any]] = []
    for li in soup.select("li[data-date]"):
        date = li["data-date"]
        if date != today:
            continue
        meetings.append(
            {
                "id": li.get("data-id"),
                "name": li.get_text(strip=True),
                "date": date,
            }
        )
    return {"meetings": meetings}


def fetch_meetings(url: str) -> Any:
    """Retrieve meeting data from ``url`` with a Geny fallback."""
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.Timeout:
        return _fetch_from_geny()
    except requests.HTTPError as exc:  # pragma: no cover - exercised via tests
        status = exc.response.status_code if exc.response is not None else None
        if status == 404:
            return _fetch_from_geny()
            
        raise


def filter_today(meetings: Any) -> List[Dict[str, Any]]:
    """Return meetings occurring today."""
    today = dt.date.today().isoformat()
    items = meetings
    if isinstance(meetings, dict):
        items = meetings.get("meetings") or meetings.get("data") or []
    return [m for m in items if m.get("date") == today]


def fetch_runners(url: str) -> Dict[str, Any]:
    """Fetch raw runners data from ``url``."""
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def normalize_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a normalized snapshot of runners with metadata."""
    rc = payload.get("rc", "")
    meta = {
        "rc": rc,
        "hippodrome": payload.get("hippodrome", ""),
        "date": payload.get("date", dt.date.today().isoformat()),
        "discipline": payload.get("discipline", ""),
    }
    runners = []
    id2name: Dict[str, str] = {}
    for r in payload.get("runners", []):
        cid = str(r.get("id"))
        name = r.get("name", cid)
        odds = float(r.get("odds", 0.0))
        runners.append({"id": cid, "name": name, "odds": odds})
        id2name[cid] = name
    meta.update({"runners": runners, "id2name": id2name})
    return meta

def compute_diff(h30: Dict[str, Any], h5: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Compute steams and drifts between two snapshots."""
    odds30 = {str(r["id"]): float(r.get("odds", 0)) for r in h30.get("runners", [])}
    odds05 = {str(r["id"]): float(r.get("odds", 0)) for r in h5.get("runners", []
    deltas: Dict[str, float] = {}
    for cid, o30 in odds30.items():
        if cid in odds05:
            deltas[cid] = o30 - odds05[cid]
    steams = [
        {"id": cid, "delta": d}
        for cid, d in sorted(deltas.items(), key=lambda x: x[1], reverse=True)
        if d > 0
    ][:5]
    drifts = [
        {"id": cid, "delta": d}
        for cid, d in sorted(deltas.items(), key=lambda x: x[1])
        if d < 0
    ][:5]
    return {"top_steams": steams, "top_drifts": drifts}


def make_diff(course_id: str, h30_path: Path | str, h5_path: Path | str, outdir: Path | str = ".") -> Path:
    """Write steam and drift lists to ``outdir`` and return the output path."""
    h30 = json.loads(Path(h30_path).read_text(encoding="utf-8"))
    h5 = json.loads(Path(h5_path).read_text(encoding="utf-8"))
    res = compute_diff(h30, h5)
    data = {
        "steams": [{"id_cheval": r["id"], "delta": r["delta"]} for r in res["top_steams"]],
        "drifts": [{"id_cheval": r["id"], "delta": r["delta"]} for r in res["top_drifts"]],
    }
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    out_fp = outdir / f"{course_id}_diff_drift.json"
    out_fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_fp


def main() -> None:  # pragma: no cover - minimal CLI wrapper
    parser = argparse.ArgumentParser(description="Fetch data from Zeturf")
    parser.add_argument("--mode", choices=["h30", "h5", "diff"], required=True)  
    parser.add_argument("--out", required=True, help="Output JSON file")
    parser.add_argument("--sources", default="config/sources.yml", help="YAML sources")
    args = parser.parse_args()
    
    if args.mode in {"h30", "h5"}:
        with open(args.sources, "r", encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
        url = config.get("zeturf", {}).get("url")
        if not url:
            raise ValueError("No Zeturf source URL configured in sources.yml")
        payload = fetch_runners(url)
        data = normalize_snapshot(payload)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:  # diff mode
        out_path = Path(args.out)
        root = out_path.parent.parent
        h30_path = root / "h30" / "h30.json"
        h5_path = root / "h5" / "h5.json"
        h30 = json.loads(h30_path.read_text(encoding="utf-8"))
        h5 = json.loads(h5_path.read_text(encoding="utf-8"))
        res = compute_diff(h30, h5)
        out_data = {
            "steams": [
                {"id_cheval": r["id"], "delta": r["delta"]}
                for r in res["top_steams"]
            ],
            "drifts": [
                {"id_cheval": r["id"], "delta": r["delta"]}
                for r in res["top_drifts"]
            ],
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    


if __name__ == "__main__":  # pragma: no cover
    main()
