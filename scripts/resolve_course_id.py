"""Utilities to determine which course to analyse for scheduled runs."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python <3.9 fallback
    from backports.zoneinfo import ZoneInfo  # type: ignore

PARIS = ZoneInfo("Europe/Paris")


@dataclass(frozen=True)
class CourseContext:
    """Resolved course information."""

    course_id: str
    meeting: str | None = None
    race: str | None = None
    when: dt.datetime | None = None


class CourseContextError(RuntimeError):
    """Raised when the course context cannot be determined."""


def _parse_iso_datetime(value: str) -> dt.datetime | None:
    """Parse ``value`` into an aware ``datetime`` in Europe/Paris."""

    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        dtobj = dt.datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None
    if dtobj.tzinfo is None:
        dtobj = dtobj.replace(tzinfo=PARIS)
    else:
        dtobj = dtobj.astimezone(PARIS)
    return dtobj


def _extract_course_id(url: str | None) -> str | None:
    """Return the numeric course identifier embedded in ``url``."""

    if not url:
        return None
    match = re.search(r"/race/(\d+)", url)
    if match:
        return match.group(1)
    return None


def _iter_schedule_entries(path: Path) -> Iterator[CourseContext]:
    """Yield :class:`CourseContext` rows from ``path``."""

    with path.open("r", encoding="utf-8") as fh:
        reader = csv.reader(fh, delimiter=";")
        for row in reader:
            if not row:
                continue
            url = row[0].strip()
            course_id = _extract_course_id(url)
            if not course_id:
                continue
            when = _parse_iso_datetime(row[1]) if len(row) > 1 else None
            meeting = row[2].strip() if len(row) > 2 and row[2].strip() else None
            race = row[3].strip() if len(row) > 3 and row[3].strip() else None
            yield CourseContext(
                course_id=course_id, meeting=meeting, race=race, when=when
            )


def _iter_planning_entries(path: Path) -> Iterator[CourseContext]:
    """Yield :class:`CourseContext` entries from a planning JSON file."""

    if not path.exists():
        return iter(())

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        meetings = (
            data.get("meetings") or data.get("reunions") or data.get("data") or []
        )
    else:
        meetings = data

    contexts: list[CourseContext] = []
    for meeting in meetings:
        meeting_label = (
            meeting.get("label")
            or meeting.get("r")
            or meeting.get("id")
            or meeting.get("meeting")
            or None
        )
        courses = meeting.get("courses") or meeting.get("races") or []
        for course in courses:
            course_id = (
                course.get("course_id")
                or course.get("id_course")
                or course.get("id")
                or course.get("number")
                or course.get("num")
            )
            if course_id is None:
                continue
            course_id = str(course_id)
            if not course_id.isdigit():
                continue
            race_label = (
                course.get("course")
                or course.get("race")
                or course.get("label")
                or course.get("num")
                or None
            )
            when = _parse_iso_datetime(
                course.get("start") or course.get("time") or course.get("hour")
            )
            contexts.append(
                CourseContext(
                    course_id=course_id,
                    meeting=str(meeting_label) if meeting_label is not None else None,
                    race=str(race_label) if race_label is not None else None,
                    when=when,
                )
            )
    return iter(contexts)


def _select_best(
    now: dt.datetime, candidates: Iterable[CourseContext]
) -> CourseContext | None:
    """Return the most relevant course from ``candidates`` for ``now``."""

    def sort_key(ctx: CourseContext) -> tuple[int, dt.timedelta]:
        if ctx.when is None:
            return (2, dt.timedelta.max)
        delta = ctx.when - now
        if delta.total_seconds() >= 0:
            return (0, delta)
        return (1, -delta)

    ordered = sorted(candidates, key=sort_key)
    return ordered[0] if ordered else None


def resolve_course_context(
    *,
    fallback: str | None = None,
    schedule_file: str | Path | None = None,
    planning_dir: str | Path | None = None,
    now: dt.datetime | None = None,
) -> CourseContext:
    """Determine the course to analyse for the current execution."""

    if fallback:
        return CourseContext(course_id=str(fallback))

    now = (now or dt.datetime.now(tz=PARIS)).astimezone(PARIS)

    candidates: list[CourseContext] = []

    if schedule_file:
        schedule_path = Path(schedule_file)
        if schedule_path.exists():
            candidates.extend(_iter_schedule_entries(schedule_path))

    if planning_dir:
        planning_path = Path(planning_dir)
        if planning_path.is_dir():
            planning_file = planning_path / f"{now.date().isoformat()}.json"
            candidates.extend(_iter_planning_entries(planning_file))

    selected = _select_best(now, candidates)
    if not selected:
        raise CourseContextError(
            "Unable to resolve course_id automatically. Set vars.GPI_COURSE_ID or update the planning."
        )
    return selected


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry-point used by automation scripts."""

    parser = argparse.ArgumentParser(
        description="Resolve the course identifier to fetch"
    )
    parser.add_argument("--schedule-file", default="schedules.csv")
    parser.add_argument("--planning-dir", default="data/planning")
    parser.add_argument("--fallback")
    parser.add_argument(
        "--target",
        help="ISO timestamp to use instead of now (defaults to current time)",
    )
    args = parser.parse_args(argv)

    now = _parse_iso_datetime(args.target) if args.target else None

    try:
        ctx = resolve_course_context(
            fallback=args.fallback,
            schedule_file=args.schedule_file,
            planning_dir=args.planning_dir,
            now=now,
        )
    except CourseContextError as exc:  # pragma: no cover - CLI propagation
        print(str(exc))
        return 1

    payload = {
        "course_id": ctx.course_id,
        "meeting": ctx.meeting,
        "race": ctx.race,
        "when": ctx.when.isoformat() if ctx.when else None,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


__all__ = [
    "CourseContext",
    "CourseContextError",
    "resolve_course_context",
]


if __name__ == "__main__":  # pragma: no cover - CLI helper
    raise SystemExit(main())
