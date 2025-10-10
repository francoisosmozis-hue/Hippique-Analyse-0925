#!/usr/bin/env python3
"""Offline parser to normalise race arrivals into a JSON payload.

This module supersedes the historical online scraper by operating entirely on
local artefacts (text, CSV, HTML) exported from trusted providers.  It accepts a
planning JSON produced during the analysis stage and associates each race with
one or more offline files.  The parser tolerates heterogeneous layouts and
produces a stable JSON schema that downstream scripts can consume without
network access.

Usage example
-------------

    python get_arrivee_geny.py \
        --planning data/planning/2025-09-06.json \
        --out data/results/2025-09-06_arrivees.json \
        --source data/arrivees/offline

The ``--source`` flag can be repeated to provide additional lookup directories
or explicit files.  When the planning payload already contains local file
references (``result_path``, ``arrivee_file`` …) the parser automatically relies
on those hints.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, List, Mapping, MutableMapping, Sequence

from bs4 import BeautifulSoup

ARRIVE_TEXT_RE = re.compile(
    r"arriv[ée]e\s*(?:officielle|définitive)?\s*[:\-–>]*\s*([0-9\s,;:\-–>]+)",
    re.IGNORECASE,
)

_JSON_LIST_RE = re.compile(r"\[(?:[^\]\[]+|\[[^\]]*\])*\]")

_HTML_GUESS_RE = re.compile(r"<\s*(?:html|body|table|div|section|ul|ol)[^>]*>", re.IGNORECASE)

_SUPPORTED_SUFFIX_HINTS = {
    ".html": "html",
    ".htm": "html",
    ".json": "json",
    ".txt": "text",
    ".csv": "csv",
    ".tsv": "csv",
    ".log": "text",
}

_DEFAULT_SOURCES_KEYS = (
    "result_path",
    "result_file",
    "arrivee_path",
    "arrivee_file",
    "arrival_path",
    "arrival_file",
    "offline_file",
    "offline_path",
    "local_file",
    "local_path",
    "fichier",
    "fichier_arrivee",
)


def _norm_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _compose_rc(reunion: str | None, course: str | None) -> str | None:
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
    if not isinstance(obj, MutableMapping):
        return None
    for key in keys:
        if key in obj:
            return obj[key]
    return None


def _get_course_id(data: MutableMapping[str, Any]) -> str | None:
    for container in (data, _first(data, "meta"), _first(data, "course"), _first(data, "race")):
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
    for key in ("start", "time", "heure", "start_time", "post_time"):
        value = data.get(key)
        if value:
            value = str(value)
            if value.isdigit() and len(value) == 4:
                value = f"{value[:2]}:{value[2:]}"
            return value
    return None


def _extract_sources(data: MutableMapping[str, Any] | None) -> list[str]:
    sources: list[str] = []
    if not isinstance(data, MutableMapping):
        return sources
    for key in _DEFAULT_SOURCES_KEYS:
        value = data.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, (list, tuple, set)):
            sources.extend(str(item) for item in value if item not in (None, ""))
        else:
            sources.append(str(value))
    extra = data.get("sources")
    if isinstance(extra, (list, tuple, set)):
        sources.extend(str(item) for item in extra if item not in (None, ""))
    elif isinstance(extra, (str, os.PathLike)):
        sources.append(str(extra))
    return sources


@dataclass
class PlanningEntry:
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
    local_sources: list[str] = field(default_factory=list)
    base_dir: Path | None = None

    def to_meta(self) -> dict[str, Any]:
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
        if self.local_sources:
            meta.setdefault("local_sources", list(dict.fromkeys(self.local_sources)))
        return {k: v for k, v in meta.items() if v not in (None, "")}


def _iter_planning_entries(data: Any, context: dict[str, Any] | None = None) -> Iterable[PlanningEntry]:
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

    scoped_sources = list(ctx.get("local_sources", []))
    scoped_sources.extend(_extract_sources(data))
    if scoped_sources:
        ctx["local_sources"] = scoped_sources
        
    for key in ("races", "courses", "items", "entries", "programme"):
        nested = data.get(key)
        if isinstance(nested, list):
            for item in nested:
                yield from _iter_planning_entries(item, ctx)
            return

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
    entry.local_sources = list(dict.fromkeys(scoped_sources))
    
    yield entry


def load_planning(path: Path) -> List[PlanningEntry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = list(_iter_planning_entries(data))
    deduped: dict[str, PlanningEntry] = {}
    for entry in entries:
        entry.base_dir = path.parent
        if entry.rc in deduped:
            existing = deduped[entry.rc]
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
            existing.meta.update({k: v for k, v in entry.meta.items() if k not in existing.meta})
            existing.local_sources.extend(x for x in entry.local_sources if x not in existing.local_sources)
        else:
            deduped[entry.rc] = entry
    return list(deduped.values())


def _extract_arrival_from_json(text: str) -> list[str]:
     for match in _JSON_LIST_RE.finditer(text): 
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            numbers = re.findall(r"\d+", match.group(0))
        else:
            numbers = [str(item) for item in data if str(item).strip()]
        if numbers:
            return numbers
    return []


def _extract_arrival_from_tables(soup: BeautifulSoup) -> list[str]:
    for table in soup.find_all("table"):
        header_map: dict[str, int] = {}
        body_rows = []
        for thead in table.find_all("thead"):
            header_map = {}
            for row in thead.find_all("tr"):
                for idx, cell in enumerate(row.find_all(("th", "td"))):
                    header = cell.get_text(" ", strip=True).lower()
                    if not header:
                        continue
                    header_map[header] = idx
        if not header_map:
            head_row = table.find("tr")
            if head_row:
                for idx, cell in enumerate(head_row.find_all(("th", "td"))):
                    header = cell.get_text(" ", strip=True).lower()
                    if header:
                        header_map[header] = idx
        for tbody in table.find_all("tbody"):
            for row in tbody.find_all("tr"):
                body_rows.append([cell.get_text(" ", strip=True) for cell in row.find_all(("td", "th"))])
        if not body_rows:
            continue
        num_idx = None
        for key in ("n°", "num", "cheval", "dossard", "n° cheval", "n°ordre"):
            if key in header_map:
                num_idx = header_map[key]
                break
        if num_idx is None and header_map:
            num_idx = min(header_map.values())
        numbers: list[str] = []
        for row in body_rows:
            if num_idx is None or num_idx >= len(row):
                digits = re.findall(r"\d+", " ".join(row))
                if digits:
                    numbers.append(digits[0])
            else:
                value = row[num_idx]
                digits = re.findall(r"\d+", value)
                if digits:
                    numbers.append(digits[0])
        if numbers:
            return numbers
    return []


def _extract_arrival_from_list(soup: BeautifulSoup) -> list[str]:
    for selector in ("ol", "ul"):
        for node in soup.select(selector):
            classes = " ".join(node.get("class", [])).lower()
            if classes and not any(token in classes for token in ("arriv", "result", "arrival")):
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


def _extract_arrival_from_text(text: str) -> list[str]:
    match = ARRIVE_TEXT_RE.search(text)
    candidates: list[str] = []
    if match:
        candidates = re.findall(r"\d+", match.group(1))
    if not candidates:
        candidates = re.findall(r"\d+", text)
    return [str(num) for num in candidates if str(num).strip()]


def parse_arrival(content: str, *, hint: str | None = None) -> list[str]:
    if not content:
        return []
    text = content.strip()
    if not text:
        return []

    hint_lower = hint.lower() if hint else None
    if hint_lower == "json":
        numbers = _extract_arrival_from_json(text)
        if numbers:
            return numbers
        return _extract_arrival_from_text(text)

    if hint_lower == "csv":
        return _extract_arrival_from_text(text)

    if hint_lower == "text":
        numbers = _extract_arrival_from_json(text)
        if numbers:
            return numbers
        return _extract_arrival_from_text(text)

    if hint_lower == "html" or _HTML_GUESS_RE.search(text):
        soup = BeautifulSoup(text, "html.parser")
        numbers = _extract_arrival_from_json(text)
        if numbers:
            return numbers
        numbers = _extract_arrival_from_list(soup)
        if numbers:
            return numbers
        numbers = _extract_arrival_from_tables(soup)
        if numbers:
            return numbers
        return _extract_arrival_from_text(soup.get_text(" ", strip=True))

    numbers = _extract_arrival_from_json(text)
    if numbers:
        return numbers
    return _extract_arrival_from_text(text)


def _read_local_file(path: Path) -> tuple[str, str | None]:
    suffix = path.suffix.lower()
    hint = _SUPPORTED_SUFFIX_HINTS.get(suffix)
    if suffix in {".csv", ".tsv"}:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh, delimiter=";" if suffix == ".csv" else "\t")
            rows = [" ".join(cell for cell in row if cell) for row in reader]
        return "\n".join(rows), "csv"
    text = path.read_text(encoding="utf-8")
    return text, hint

    
    def _resolve_relative(path: str, base_dir: Path | None) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or base_dir is None:
        return candidate
    return (base_dir / candidate).resolve()

    
def _candidate_identifiers(entry: PlanningEntry) -> list[str]:
    identifiers: list[str] = []
    if entry.course_id:
        identifiers.extend({entry.course_id, f"_c{entry.course_id}", f"course_{entry.course_id}"})
    identifiers.append(entry.rc.replace("/", "").replace(" ", ""))
    if entry.date and entry.rc:
        identifiers.append(f"{entry.date}_{entry.rc}")
    if entry.hippodrome and entry.rc:
        hippo = re.sub(r"[^a-z0-9]+", "-", entry.hippodrome.lower())
        identifiers.append(f"{hippo}_{entry.rc.lower()}")
    return list(dict.fromkeys(identifiers))


def _iter_source_paths(entry: PlanningEntry, search_roots: Sequence[Path]) -> Iterator[tuple[Path, str | None]]:
    seen: set[Path] = set()

    for raw in entry.local_sources:
        resolved = _resolve_relative(raw, entry.base_dir)
        if resolved.exists() and resolved.is_file():
            path = resolved.resolve()
            if path not in seen:
                seen.add(path)
                yield path, _SUPPORTED_SUFFIX_HINTS.get(path.suffix.lower())

    for base in search_roots:
        base_path = _resolve_relative(str(base), entry.base_dir) if not isinstance(base, Path) else base
        base_path = base_path.resolve()
        if not base_path.exists():
            continue
        if base_path.is_file():
            if base_path not in seen:
                seen.add(base_path)
                yield base_path, _SUPPORTED_SUFFIX_HINTS.get(base_path.suffix.lower())
            continue
        identifiers = _candidate_identifiers(entry)
        for identifier in identifiers:
            for suffix, hint in _SUPPORTED_SUFFIX_HINTS.items():
                direct = base_path / f"{identifier}{suffix}"
                if direct.exists() and direct.is_file():
                    resolved = direct.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        yield resolved, hint
        for identifier in identifiers:
            pattern = f"**/*{identifier}*"
            matches = list(base_path.glob(pattern))
            for match in matches[:5]:
                if match.is_file():
                    resolved = match.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        yield resolved, _SUPPORTED_SUFFIX_HINTS.get(match.suffix.lower())


def fetch_arrival(entry: PlanningEntry, search_roots: Sequence[Path] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "rc": entry.rc,
        "course_id": entry.course_id,
        "result": [],
        "status": "pending",
        "meta": entry.to_meta(),
        "source_path": None,
        "error": None,
    }

    search_roots = search_roots or []
    errors: list[str] = []
    for path, hint in _iter_source_paths(entry, search_roots):
        try:
            content, inferred_hint = _read_local_file(path)
        except OSError as exc:
            errors.append(f"{path.name}:{exc.__class__.__name__}")
            continue
        numbers = parse_arrival(content, hint=hint or inferred_hint)
        if numbers:
            result.update(
                {
                    "result": numbers,
                    "status": "ok",
                    "source_path": str(path),
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            break
        errors.append(f"{path.name}:no-arrival-data")

    if result["status"] != "ok":
        if errors:
            result["error"] = ",".join(errors)
        elif not entry.local_sources and not search_roots:
            result["error"] = "no-source-provided"
        else:
            result["error"] = "arrival-not-found"
    return result


def write_arrivals(entries: Sequence[PlanningEntry], dest: Path, *, search_roots: Sequence[Path] | None = None) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "offline",
        "arrivees": [],
    }

    for entry in sorted(entries, key=lambda e: e.rc):
        race = fetch_arrival(entry, search_roots=search_roots or [])
        payload["arrivees"].append(race)
        status = race["status"]
        rc = race["rc"]
        if status == "ok":
            print(f"[OK] {rc}: {' - '.join(race['result'])}")
        else:
            print(f"[WARN] {rc}: {status} ({race.get('error')})")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_sources_args(raw_sources: Sequence[str]) -> list[Path]:
    paths: list[Path] = []
    for raw in raw_sources:
        if not raw:
            continue
        for item in str(raw).split(os.pathsep):
            item = item.strip()
            if not item:
                continue
            paths.append(Path(item))
    return paths


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Assembler les arrivées à partir de fichiers locaux")
    parser.add_argument("--planning", required=True, help="Fichier JSON du planning")
    parser.add_argument("--out", required=True, help="Fichier de sortie JSON normalisé")
    parser.add_argument(
        "--source",
        dest="sources",
        action="append",
        default=[],
        help="Chemin supplémentaire (fichier ou dossier) contenant les arrivées",
    )
    args = parser.parse_args(argv)

    planning_path = Path(args.planning)
    if not planning_path.exists():
        raise SystemExit(f"Planning introuvable: {planning_path}")

    entries = load_planning(planning_path)
    if not entries:
        raise SystemExit(f"Aucune course valide détectée dans {planning_path}")

    search_roots = _parse_sources_args(args.sources)
    out_path = Path(args.out)
    write_arrivals(entries, out_path, search_roots=search_roots)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()


__all__ = [
    "PlanningEntry",
    "fetch_arrival",
    "load_planning",
    "main",
    "parse_arrival",
    "write_arrivals",
]
