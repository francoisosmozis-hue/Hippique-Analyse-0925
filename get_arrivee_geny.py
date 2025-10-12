#!/usr/bin/env python3
"""Fetch official race arrivals from geny.com based on planning data.

The daily ``post_results`` workflow downloads a planning JSON file that
lists the races analysed during the day.  This helper script loads that
planning information, derives race identifiers (``R#C#``) and the
associated ``course_id``/Geny URL when available, then scrapes the
official arrival from geny.com.  A consolidated JSON payload is written
to ``data/results/<DATE>_arrivees.json`` so that the post-processing
steps (``p_finale_export.py`` and ``update_excel_with_results.py``) can
update tickets and Excel workbooks without manual intervention.

Network requests are intentionally resilient: several URL patterns are
attempted for a given ``course_id`` and the HTML is parsed with multiple
strategies (structured JSON, dedicated arrival lists, generic tables or
fallback text such as "Arrivée officielle : 5 - 7 - 1").  When an
arrival cannot be resolved yet—e.g. the race has not started—the script
records a ``pending`` status but still emits a valid JSON structure so
that downstream tooling can continue operating.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, List, MutableMapping, Sequence
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

GENY_BASE = "https://www.geny.com"
HDRS = {"User-Agent": "Mozilla/5.0 (compatible; get_arrivee_geny/1.0)"}

ARRIVE_TEXT_RE = re.compile(
    r"arriv[ée]e\s*(?:officielle|d[eé]finitive)?\s*:?\s*([0-9\s\-–>]+)",
    re.IGNORECASE,
)


def _norm_str(value: Any) -> str | None:
    """Return ``value`` stripped and converted to ``str`` if possible."""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _compose_rc(reunion: str | None, course: str | None) -> str | None:
    """Return an ``R#C#`` identifier built from ``reunion`` and ``course``."""

    reunion_val = _norm_str(reunion)
    course_val = _norm_str(course)
    if reunion_val and not reunion_val.upper().startswith("R"):
        reunion_val = f"R{reunion_val}"
    if course_val and not course_val.upper().startswith("C"):
        course_val = f"C{course_val}"
    if reunion_val and course_val:
        return f"{reunion_val}{course_val}"
    return reunion_val or course_val


def _first(obj: MutableMapping[str, Any] | None, *keys: str) -> Any:
    """Return the first value from ``obj`` found in ``keys``."""

    if not isinstance(obj, MutableMapping):
        return None
    for key in keys:
        if key in obj:
            return obj[key]
    return None


def _get_course_id(data: MutableMapping[str, Any]) -> str | None:
    """Extract a course identifier from ``data`` using known aliases."""

    for container in (
        data,
        _first(data, "meta"),
        _first(data, "course"),
        _first(data, "race"),
    ):
        if isinstance(container, MutableMapping):
            for key in (
                "course_id",
                "courseId",
                "idcourse",
                "id_course",
                "idCourse",
                "idCoursePMU",
                "id_pmu",
                "idPmu",
            ):
                value = container.get(key)
                if value:
                    return str(value)
    return None


def _get_course_url(data: MutableMapping[str, Any]) -> str | None:
    """Extract a Geny course URL if present in ``data``."""

    value = _first(
        data,
        "url_course",
        "course_url",
        "urlCourse",
        "urlGenyCourse",
        "result_url",
        "url_result",
        "url",
    )
    if value:
        return str(value)
    meta = _first(data, "meta")
    if isinstance(meta, MutableMapping):
        value = _first(meta, "url_course", "course_url", "url_geny")
        if value:
            return str(value)
    return None


def _extract_start(data: MutableMapping[str, Any]) -> str | None:
    """Extract an ISO-ish start time from ``data``."""

    for key in ("start", "time", "heure", "start_time", "post_time"):
        value = data.get(key)
        if value:
            value = str(value)
            if value.isdigit() and len(value) == 4:
                value = f"{value[:2]}:{value[2:]}"
            return value
    return None


@dataclass
class PlanningEntry:
    """Normalized planning information for a single race."""

    rc: str
    reunion: str | None = None
    course: str | None = None
    course_id: str | None = None
    url_geny: str | None = None
    date: str | None = None
    start: str | None = None
    hippodrome: str | None = None
    discipline: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_meta(self) -> dict[str, Any]:
        """Return metadata suitable for JSON serialization."""

        meta = dict(self.meta)
        meta.update(
            {
                "rc": self.rc,
                "reunion": self.reunion,
                "course": self.course,
                "course_id": self.course_id,
                "date": self.date,
                "start": self.start,
                "hippodrome": self.hippodrome,
                "discipline": self.discipline,
                "url_geny": self.url_geny,
            }
        )
        return {k: v for k, v in meta.items() if v not in (None, "")}


def _iter_planning_entries(
    data: Any, context: dict[str, Any] | None = None
) -> Iterable[PlanningEntry]:
    """Yield :class:`PlanningEntry` objects extracted from ``data``."""

    ctx = dict(context or {})
    if isinstance(data, MutableMapping):
        date_val = data.get("date")
        if date_val and "date" not in ctx:
            ctx["date"] = str(date_val)
        for key in ("meetings", "planning", "reunions"):
            nested = data.get(key)
            if isinstance(nested, list):
                for item in nested:
                    yield from _iter_planning_entries(item, ctx)
                return

    if isinstance(data, list):
        for item in data:
            yield from _iter_planning_entries(item, ctx)
        return

    if not isinstance(data, MutableMapping):
        return

    # Update context with meeting-level metadata.
    meeting = _first(data, "reunion", "meeting", "label", "r", "id")
    if meeting:
        ctx["reunion"] = str(meeting)
    hippo = _first(data, "hippodrome", "hippo", "track")
    if hippo:
        ctx["hippodrome"] = str(hippo)
    date = data.get("date") or ctx.get("date")
    if date:
        ctx["date"] = str(date)
    discipline = data.get("discipline") or ctx.get("discipline")
    if discipline:
        ctx["discipline"] = str(discipline)
    geny_url = _first(data, "url_geny", "geny_url", "urlGeny") or ctx.get("url_geny")
    if geny_url:
        ctx["url_geny"] = str(geny_url)

    for key in ("races", "courses", "items", "entries", "programme"):
        nested = data.get(key)
        if isinstance(nested, list):
            for item in nested:
                yield from _iter_planning_entries(item, ctx)
            return

    # Flatten race entry.
    course_val = _first(data, "course", "race", "c", "number", "num")
    if course_val is None:
        course_val = ctx.get("course")
    course = _norm_str(course_val)
    rc = _norm_str(data.get("rc")) or _norm_str(data.get("id"))
    if not rc:
        rc = _compose_rc(ctx.get("reunion"), course)
    if not rc:
        return

    entry = PlanningEntry(rc=rc)
    entry.reunion = _norm_str(ctx.get("reunion"))
    entry.course = course
    entry.date = _norm_str(ctx.get("date") or data.get("date"))
    entry.start = _norm_str(_extract_start(data) or ctx.get("start"))
    entry.hippodrome = _norm_str(ctx.get("hippodrome") or data.get("hippodrome"))
    entry.discipline = _norm_str(ctx.get("discipline") or data.get("discipline"))
    entry.course_id = _get_course_id(data)
    entry.url_geny = _norm_str(_get_course_url(data) or ctx.get("url_geny"))
    entry.meta = {}
    for key in ("meeting", "reunion", "course", "race", "start", "time", "heure"):
        value = data.get(key)
        if value is not None:
            entry.meta[key] = value
    for key in ("meta", "extra", "details"):
        value = data.get(key)
        if isinstance(value, MutableMapping):
            entry.meta.update(value)

    yield entry


def load_planning(path: Path) -> List[PlanningEntry]:
    """Return normalized planning entries from ``path``."""

    data = json.loads(path.read_text(encoding="utf-8"))
    entries = list(_iter_planning_entries(data))
    deduped: dict[str, PlanningEntry] = {}
    for entry in entries:
        if entry.rc in deduped:
            existing = deduped[entry.rc]
            # Merge missing metadata from the new entry.
            for field_name in (
                "reunion",
                "course",
                "course_id",
                "url_geny",
                "date",
                "start",
                "hippodrome",
                "discipline",
            ):
                if not getattr(existing, field_name) and getattr(entry, field_name):
                    setattr(existing, field_name, getattr(entry, field_name))
            existing.meta.update(
                {k: v for k, v in entry.meta.items() if k not in existing.meta}
            )
        else:
            deduped[entry.rc] = entry
    return list(deduped.values())


def _request(url: str) -> requests.Response:
    """Return an HTTP response for ``url`` with optional cookie support."""

    headers = dict(HDRS)
    cookie = os.getenv("GENY_COOKIE")
    if cookie:
        headers["Cookie"] = cookie
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp


def _extract_arrival_from_json(text: str) -> list[str]:
    """Extract arrival numbers from JSON-like payload contained in ``text``."""

    for pattern in (
        r'"arriv[ée]e"\s*:\s*(\[[^\]]+\])',
        r'"arrival"\s*:\s*(\[[^\]]+\])',
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        raw = match.group(1)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            numbers = re.findall(r"\d+", raw)
        else:
            numbers = [str(item) for item in data if str(item).strip()]
        if numbers:
            return numbers
    return []


def _extract_arrival_from_list(soup: BeautifulSoup) -> list[str]:
    """Extract arrival numbers from ordered/unstyled lists."""

    for selector in ("ol", "ul"):
        for node in soup.select(selector):
            classes = " ".join(node.get("class", [])).lower()
            if not any(token in classes for token in ("arriv", "result", "arrival")):
                continue
            numbers: list[str] = []
            for li in node.find_all("li"):
                num = li.get("data-num") or li.get("data-number")
                if not num:
                    digits = re.findall(r"\d+", li.get_text(" ", strip=True))
                    num = digits[0] if digits else None
                if num:
                    numbers.append(str(num))
            if numbers:
                return numbers
    return []


def _extract_arrival_from_tables(soup: BeautifulSoup) -> list[str]:
    """Extract arrival numbers from tabular data."""

    for table in soup.find_all("table"):
        headers = [th.get_text(" ", strip=True).lower() for th in table.find_all("th")]
        if not headers:
            continue
        rank_idx = next(
            (i for i, h in enumerate(headers) if "arriv" in h or "place" in h), None
        )
        if rank_idx is None:
            continue
        num_idx = next(
            (
                i
                for i, h in enumerate(headers)
                if h in {"n", "n°", "num", "numero", "nº", "n° cheval"} or "num" in h
            ),
            None,
        )
        ranked: list[tuple[int, str]] = []
        for row in table.find_all("tr"):
            cols = [td.get_text(" ", strip=True) for td in row.find_all("td")]
            if not cols:
                continue
            try:
                place_text = cols[rank_idx]
            except IndexError:
                continue
            digits = re.findall(r"\d+", place_text)
            if not digits:
                continue
            place = int(digits[0])
            num: str | None = None
            if num_idx is not None and num_idx < len(cols):
                digits = re.findall(r"\d+", cols[num_idx])
                if digits:
                    num = digits[0]
            if not num:
                digits = re.findall(r"\d+", cols[0])
                if digits:
                    num = digits[0]
            if num:
                ranked.append((place, str(num)))
        if ranked:
            ranked.sort(key=lambda item: item[0])
            return [num for _, num in ranked]
    return []


def _extract_arrival_from_text(text: str) -> list[str]:
    """Extract arrival numbers from free text snippets."""

    match = ARRIVE_TEXT_RE.search(text)
    if not match:
        return []
    return re.findall(r"\d+", match.group(1))


def parse_arrival(html: str) -> list[str]:
    """Return arrival numbers extracted from ``html``."""

    numbers = _extract_arrival_from_json(html)
    if numbers:
        return numbers

    soup = BeautifulSoup(html, "html.parser")
    numbers = _extract_arrival_from_list(soup)
    if numbers:
        return numbers

    numbers = _extract_arrival_from_tables(soup)
    if numbers:
        return numbers

    numbers = _extract_arrival_from_text(soup.get_text(" ", strip=True))
    return numbers


def _course_candidate_urls(course_id: str) -> Sequence[str]:
    return (
        f"{GENY_BASE}/resultats-pmu/course/_c{course_id}",
        f"{GENY_BASE}/resultats-pmu/_c{course_id}",
        f"{GENY_BASE}/course-pmu/_c{course_id}",
        f"{GENY_BASE}/partants-pmu/_c{course_id}",
    )


def fetch_arrival_for_course(
    entry: PlanningEntry,
) -> tuple[list[str], str | None, str | None]:
    """Return arrival numbers, resolved URL and optional error message."""

    if not entry.course_id:
        return [], None, "missing-course-id"

    for url in _course_candidate_urls(entry.course_id):
        try:
            resp = _request(url)
        except requests.RequestException as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"
            continue
        numbers = parse_arrival(resp.text)
        if numbers:
            return numbers, url, None
        last_error = "no-arrival-data"
    return [], None, last_error


def _resolve_course_url_from_meeting(url: str, entry: PlanningEntry) -> str | None:
    """Try to resolve a course specific URL from a meeting page."""

    try:
        resp = _request(url)
    except requests.RequestException:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    course_key = (entry.course or "").replace(" ", "").upper()

    if entry.course_id:
        for attr in (
            "data-course",
            "data-course-id",
            "data-idcourse",
            "data-id-course",
        ):
            for node in soup.find_all(attrs={attr: True}):
                value = node.get(attr)
                if not value or str(value) != entry.course_id:
                    continue
                href = node.get("href")
                if not href and hasattr(node, "find"):
                    link = node.find("a", href=True)
                    if link:
                        href = link.get("href")
                if href:
                    return urljoin(url, href)

    fallback_urls: list[str] = []
    seen_urls: set[str] = set()
    for link in soup.find_all("a", href=True):
        data_course = (
            link.get("data-course")
            or link.get("data-course-id")
            or link.get("data-idcourse")
            or link.get("data-id-course")
        )
        if entry.course_id and data_course and str(data_course) == entry.course_id:
            return urljoin(url, link["href"])
        if course_key:
            text = link.get_text(" ", strip=True).replace(" ", "").upper()
            if course_key in text:
                candidate = urljoin(url, link["href"])
                if candidate not in seen_urls:
                    fallback_urls.append(candidate)
                    seen_urls.add(candidate)

    for candidate in fallback_urls:
        return candidate

    return None


def fetch_arrival(entry: PlanningEntry) -> dict[str, Any]:
    """Fetch arrival information for ``entry`` and return a JSON-serialisable dict."""

    result: dict[str, Any] = {
        "rc": entry.rc,
        "course_id": entry.course_id,
        "result": [],
        "status": "pending",
        "meta": entry.to_meta(),
        "url": None,
        "error": None,
    }

    numbers, url, error = fetch_arrival_for_course(entry)
    if numbers:
        result.update(
            {
                "result": numbers,
                "status": "ok",
                "url": url,
                "retrieved_at": datetime.utcnow().isoformat(),
            }
        )
        return result

    if error and error != "missing-course-id":
        result["error"] = error

    geny_url = entry.url_geny
    if geny_url:
        resolved = _resolve_course_url_from_meeting(geny_url, entry)
        if resolved:
            try:
                resp = _request(resolved)
            except (
                requests.RequestException
            ) as exc:  # pragma: no cover - network failure
                result["error"] = f"{exc.__class__.__name__}: {exc}"
            else:
                numbers = parse_arrival(resp.text)
                if numbers:
                    result.update(
                        {
                            "result": numbers,
                            "status": "ok",
                            "url": resolved,
                            "retrieved_at": datetime.utcnow().isoformat(),
                        }
                    )
                    return result
                result["error"] = "no-arrival-data"

    if not result.get("error"):
        if entry.course_id:
            result["error"] = error
        else:
            result["error"] = "missing-identifiers"
    return result


def write_arrivals(entries: Sequence[PlanningEntry], dest: Path) -> None:
    """Fetch arrivals for ``entries`` and write them to ``dest``."""

    payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "source": "geny",
        "arrivees": [],
    }

    for entry in sorted(entries, key=lambda e: e.rc):
        race = fetch_arrival(entry)
        payload["arrivees"].append(race)
        status = race["status"]
        rc = race["rc"]
        if status == "ok":
            print(f"[OK] {rc}: {' - '.join(race['result'])}")
        else:
            print(f"[WARN] {rc}: {status} ({race.get('error')})")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Fetch arrivals from geny.com based on planning JSON"
    )
    parser.add_argument("--planning", required=True, help="Path to planning JSON file")
    parser.add_argument(
        "--out", required=True, help="Destination JSON file for arrivals"
    )
    args = parser.parse_args(argv)

    planning_path = Path(args.planning)
    if not planning_path.exists():
        message = (
            "Planning file "
            f"{planning_path} not found. "
            "Generate it with: python scripts/online_fetch_zeturf.py --mode planning --out "
            "data/planning/<date>.json"
        )
        raise SystemExit(message)

    entries = load_planning(planning_path)
    if not entries:
        raise SystemExit(f"No valid races found in planning {planning_path}")

    out_path = Path(args.out)
    write_arrivals(entries, out_path)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()


__all__ = [
    "load_planning",
    "parse_arrival",
    "fetch_arrival",
    "write_arrivals",
    "PlanningEntry",
]
