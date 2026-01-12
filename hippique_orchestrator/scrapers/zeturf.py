from __future__ import annotations

import asyncio
import re
from typing import Any

from hippique_orchestrator.scripts.online_fetch_zeturf import fetch_race_snapshot_full

# Match "R1C1" in either "/R1C1-..." or "-R1C1-..." or "/r1c1/"
_RC_RE = re.compile(r"(?i)(?:^|[\/-])(r\d+c\d+)(?:[\/-]|$)")


def _phase_norm(phase: str) -> str:
    p = (phase or "").upper().replace("-", "").replace("_", "")
    return "H5" if p in ("H5", "H05") else "H30"


async def fetch_zeturf_race_details(
    course_url: str,
    *,
    phase: str = "H30",
    date: str | None = None,
) -> dict[str, Any]:
    m = _RC_RE.search(course_url)
    if not m:
        raise ValueError(f"ZEturf: impossible d'extraire R?C? depuis l'URL: {course_url}")

    rc = m.group(1).upper()
    ph = _phase_norm(phase)

    # fetch_race_snapshot_full est sync (requests) -> thread pour ne pas bloquer l'event loop
    snap = await asyncio.to_thread(
        fetch_race_snapshot_full,
        rc,
        None,
        ph,
        course_url=course_url,
        date=date,
    )

    if not isinstance(snap, dict):
        snap = {}

    runners = snap.get("runners") or []
    snap["runners"] = runners
    snap.setdefault("source", "zeturf")
    snap.setdefault("source_url", course_url)
    snap.setdefault("phase", ph)
    if date:
        snap.setdefault("date", date)
    return snap
