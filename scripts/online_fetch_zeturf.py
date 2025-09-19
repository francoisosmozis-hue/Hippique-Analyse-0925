"""Tools for fetching meetings from Zeturf and computing odds drifts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Sequence

import requests
import yaml
from bs4 import BeautifulSoup
import re


GENY_BASE = "https://www.geny.com"
HDRS = {"User-Agent": "Mozilla/5.0 (+EV; GPI v5.1)"}
GENY_FALLBACK_URL = f"{GENY_BASE}/reunions-courses-pmu"

_URL_FIELDS: Sequence[str] = ("url", "endpoint", "href")
_MODE_HINTS: Dict[str, Sequence[str]] = {
    "planning": ("planning", "meetings", "schedule"),
    "h30": ("h30", "prestart", "snapshots", "snapshot", "race", "runners", "course"),
    "h5": ("h5", "final", "snapshots", "snapshot", "race", "runners", "course"),
}
_PROVIDER_PRIORITY: Dict[str, Sequence[str]] = {
    "planning": ("geny", "pmu", "zeturf"),
    "h30": ("pmu", "geny", "zeturf"),
    "h5": ("pmu", "geny", "zeturf"),
}
_DEFAULT_PROVIDER_ORDER: Sequence[str] = ("geny", "pmu", "zeturf")


def _resolve_from_provider(section: Any, hints: Sequence[str]) -> str | None:
    """Return the first URL found in ``section`` matching ``hints``."""

    def _search(value: Any, visited: set[int]) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            trimmed = value.strip()
            return trimmed or None
        if not isinstance(value, dict):
            return None

        obj_id = id(value)
        if obj_id in visited:
            return None
        visited.add(obj_id)

        for field in _URL_FIELDS:
            raw = value.get(field)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()

        for hint in hints:
            for key in (hint, f"{hint}_url", f"{hint}_endpoint"):
                if key in value:
                    url = _search(value[key], visited)
                    if url:
                        return url

        for key, nested in value.items():
            if key in _URL_FIELDS:
                continue
            if isinstance(nested, (dict, str)):
                url = _search(nested, visited)
                if url:
                    return url

        return None

    return _search(section, set())


def resolve_source_url(config: Dict[str, Any], mode: str) -> str:
    """Resolve the endpoint for ``mode`` from ``config``.

    The resolver understands both the legacy ``zeturf.url`` layout and the
    newer provider-focused structure exposing Geny/PMU endpoints.
    """

    if not isinstance(config, dict):
        raise ValueError("Invalid sources configuration: expected a mapping")

    mode_key = mode.lower()
    hints = _MODE_HINTS.get(mode_key, ())
    provider_order = _PROVIDER_PRIORITY.get(mode_key, _DEFAULT_PROVIDER_ORDER)

    search_roots: List[Dict[str, Any]] = []
    online = config.get("online")
    if isinstance(online, dict):
        search_roots.append(online)
    search_roots.append(config)

    for root in search_roots:
        for provider in provider_order:
            section = root.get(provider)
            url = _resolve_from_provider(section, hints)
            if url:
                return url

        mode_section = root.get(mode_key)
        if isinstance(mode_section, dict):
            for provider in provider_order:
                url = _resolve_from_provider(mode_section.get(provider), hints)
                if url:
                    return url
        url = _resolve_from_provider(mode_section, hints)
        if url:
            return url

    fallback = _resolve_from_provider(config.get("zeturf"), hints or ("url",))
    if fallback:
        return fallback

    raise ValueError(f"No source URL configured for mode '{mode}'")

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
    except requests.RequestException:
        return _fetch_from_geny()


def filter_today(meetings: Any) -> List[Dict[str, Any]]:
    """Return meetings occurring today."""
    today = dt.date.today().isoformat()
    items = meetings
    if isinstance(meetings, dict):
        items = meetings.get("meetings") or meetings.get("data") or []
    return [m for m in items if m.get("date") == today]


def fetch_runners(url: str) -> Dict[str, Any]:
    """Fetch raw runners data from ``url``."""
    if "{course_id}" in url:
        raise ValueError(
            "Zeturf source URL still contains '{course_id}'. Inject a real course_id before fetching."
        )
    match = re.search(r"/race/(\d+)", url)
    course_id = match.group(1) if match else None
    
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except requests.HTTPError as exc:  # pragma: no cover - exercised via tests
        status = exc.response.status_code if exc.response is not None else None
        if status == 404 and course_id:
            return fetch_from_geny_idcourse(course_id)            
        raise
    return resp.json()


def fetch_from_geny_idcourse(id_course: str) -> Dict[str, Any]:
    """Return a snapshot for ``id_course`` scraped from geny.com.

    Parameters
    ----------
    id_course:
        Identifier of the course on geny.com.
    """

    partants_url = f"{GENY_BASE}/partants-pmu/_c{id_course}"
    cotes_url = f"{GENY_BASE}/cotes?id_course={id_course}"

    resp_partants = requests.get(partants_url, headers=HDRS, timeout=10)
    resp_partants.raise_for_status()
    soup = BeautifulSoup(resp_partants.text, "html.parser")

    text = soup.get_text(" ", strip=True)
    match = re.search(r"R\d+", text)
    r_label = match.group(0) if match else None

    runners: List[Dict[str, Any]] = []
    for tr in soup.select("tr"):
        cols = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cols) < 4 or not cols[0].isdigit():
            continue
        runners.append(
            {
                "num": cols[0],
                "name": cols[1],
                "jockey": cols[2],
                "entraineur": cols[3],
            }
        )

    resp_cotes = requests.get(cotes_url, headers=HDRS, timeout=10)
    resp_cotes.raise_for_status()
    odds_map: Dict[str, float] = {}
    try:
        data = resp_cotes.json()
    except ValueError:
        soup_cotes = BeautifulSoup(resp_cotes.text, "html.parser")
        for tr in soup_cotes.select("tr"):
            cols = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cols) < 2 or not cols[0].isdigit():
                continue
            try:
                odds_map[cols[0]] = float(cols[1].replace(",", "."))
            except ValueError:
                continue
    else:
        items: Any
        if isinstance(data, dict):
            items = data.get("runners") or data.get("data") or data.get("cotes") or []
        else:
            items = data
        for item in items:
            num = str(item.get("num") or item.get("numero") or item.get("id") or item.get("number"))
            if not num:
                continue
            val = item.get("cote") or item.get("odds") or item.get("rapport") or item.get("value")
            if isinstance(val, str):
                val = val.replace(",", ".")
            try:
                odds_map[num] = float(val)
            except (TypeError, ValueError):
                continue

    for r in runners:
        num = r.get("num")
        if num in odds_map:
            r["odds"] = odds_map[num]

    snapshot = {
        "date": dt.date.today().isoformat(),
        "source": "geny",
        "id_course": id_course,
        "r_label": r_label,
        "runners": runners,
        "partants": len(runners),
    }
    return snapshot


def write_snapshot_from_geny(id_course: str, phase: str, out_dir: Path) -> Path:
    """Fetch a Geny snapshot for ``id_course`` and write it to ``out_dir``.

    The output filename embeds a timestamp, the race label and the phase tag
    (``"H-30"`` or ``"H-5"``).
    """

    snap = fetch_from_geny_idcourse(id_course)

    phase_tag = "H-30" if phase.upper().replace("-", "") == "H30" else "H-5"
    timestamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    r_label = snap.get("r_label") or "R?"
    filename = f"{timestamp}_{r_label}C?_{phase_tag}.json"

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / filename
    dest.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


def _compute_implied_probabilities(runners: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    """Return implied win probabilities for ``runners`` based on their odds."""

    implied: Dict[str, float] = {}
    total = 0.0
    for runner in runners:
        cid = runner.get("id")
        if cid is None:
            continue
        cid_str = str(cid)
        odds_val = runner.get("odds", 0.0)
        try:
            odds = float(odds_val)
        except (TypeError, ValueError):
            odds = 0.0
        if odds > 0:
            inv = 1.0 / odds
        else:
            inv = 0.0
        implied[cid_str] = inv
        total += inv

    if total <= 0:
        return {cid: 0.0 for cid in implied}

    return {cid: value / total for cid, value in implied.items()}


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
    seen_ids: set[str] = set()
    for r in payload.get("runners", []):
        cid = ""
        for key in ("id", "runner_id", "num", "number"):
            raw_val = r.get(key)
            if raw_val is None:
                continue
            if isinstance(raw_val, str):
                raw_val = raw_val.strip()
            if raw_val == "":
                continue
            cid = str(raw_val)
            if cid:
                break
        if not cid or cid in seen_ids:
            continue
        seen_ids.add(cid)

        name = r.get("name") or cid
        odds_val = r.get("odds", 0.0)
        try:
            odds = float(odds_val)
        except (TypeError, ValueError):
            odds = 0.0
        runners.append({"id": cid, "name": name, "odds": odds})
        id2name.setdefault(cid, name)
    implied = _compute_implied_probabilities(runners)
    for runner in runners:
        runner["p_imp"] = implied.get(runner["id"], 0.0)

    odds_map = {runner["id"]: runner["odds"] for runner in runners}

    meta.update({
        "runners": runners,
        "id2name": id2name,
        "odds": odds_map,
        "p_imp": implied,
    })
    return meta

def compute_diff(
    h30: Dict[str, Any],
    h5: Dict[str, Any],
    top_n: int = 5,
    min_delta: float = 0.8,
) -> Dict[str, List[Dict[str, Any]]]:
    """Compute steams and drifts between two snapshots."""
    odds30 = {str(r["id"]): float(r.get("odds", 0)) for r in h30.get("runners", [])}
    odds05 = {str(r["id"]): float(r.get("odds", 0)) for r in h5.get("runners", [])}
    deltas: Dict[str, float] = {}
    for cid, o30 in odds30.items():
        if cid in odds05:
            deltas[cid] = o30 - odds05[cid]
    steams = [
        {"id": cid, "delta": d}
        for cid, d in sorted(deltas.items(), key=lambda x: x[1], reverse=True)
        if d > min_delta
    ][:top_n]
    drifts = [
        {"id": cid, "delta": d}
        for cid, d in sorted(deltas.items(), key=lambda x: x[1])
        if d < -min_delta
    ][:top_n]
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


__all__ = [
    "fetch_meetings",
    "filter_today",
    "fetch_runners",
    "fetch_from_geny_idcourse",
    "write_snapshot_from_geny",
    "normalize_snapshot",
    "compute_diff",
    "make_diff",
    "resolve_source_url",
    "main",
]


def main() -> None:  # pragma: no cover - minimal CLI wrapper
    parser = argparse.ArgumentParser(description="Fetch data from Zeturf")
    parser.add_argument(
        "--mode", choices=["planning", "h30", "h5", "diff"], required=True
    )
    parser.add_argument("--out", required=True, help="Output JSON file")
    parser.add_argument("--sources", default="config/sources.yml", help="YAML sources")
    args = parser.parse_args()
    
    if args.mode in {"planning", "h30", "h5"}:
        with open(args.sources, "r", encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
        try:
            url = resolve_source_url(config, args.mode)
        except ValueError as exc:  # pragma: no cover - defensive branch
            raise ValueError(str(exc)) from exc
        if args.mode == "planning":
            meetings = fetch_meetings(url)
            data = filter_today(meetings)
        else:
            payload = fetch_runners(url)
            data = normalize_snapshot(payload)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:  # diff mode
        out_path = Path(args.out)
        root = out_path.parent.parent
        snaps = os.getenv("SNAPSHOTS", "H30,H5").split(",")
        h30_name, h5_name = [s.strip().lower() for s in snaps[:2]]
        h30_path = root / h30_name / f"{h30_name}.json"
        h5_path = root / h5_name / f"{h5_name}.json"
        h30 = json.loads(h30_path.read_text(encoding="utf-8"))
        h5 = json.loads(h5_path.read_text(encoding="utf-8"))
        top_n = int(os.getenv("DRIFT_TOP_N", "5"))
        min_delta = float(os.getenv("DRIFT_MIN_DELTA", "0.8"))
        res = compute_diff(h30, h5, top_n=top_n, min_delta=min_delta)
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
