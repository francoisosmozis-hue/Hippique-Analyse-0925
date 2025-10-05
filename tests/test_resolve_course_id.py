"""Tests for :mod:`scripts.resolve_course_id`."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from scripts.resolve_course_id import (
    CourseContextError,
    resolve_course_context,
)

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python <3.9 fallback
    from backports.zoneinfo import ZoneInfo  # type: ignore


def write_schedule(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "schedules.csv"
    path.write_text("\n".join(rows), encoding="utf-8")
    return path


def test_resolve_course_context_with_fallback() -> None:
    """A fallback course id should be returned directly."""

    ctx = resolve_course_context(fallback="999999")
    assert ctx.course_id == "999999"
    assert ctx.meeting is None
    assert ctx.race is None


def test_resolve_course_context_picks_closest_future_entry(tmp_path: Path) -> None:
    """The resolver should select the closest future race from the schedule."""

    schedule = write_schedule(
        tmp_path,
        [
            "https://m.zeeturf.fr/rest/api/2/race/1000;2025-09-10 13:00;R1;C1",
            "https://m.zeeturf.fr/rest/api/2/race/2000;2025-09-10 13:30;R2;C2",
        ],
    )
    now = dt.datetime(2025, 9, 10, 12, 50, tzinfo=ZoneInfo("Europe/Paris"))

    ctx = resolve_course_context(schedule_file=schedule, planning_dir=None, now=now)

    assert ctx.course_id == "1000"
    assert ctx.meeting == "R1"
    assert ctx.race == "C1"


def test_resolve_course_context_errors_when_empty(tmp_path: Path) -> None:
    """Missing schedule information should raise a clear error."""

    schedule = write_schedule(
        tmp_path, ["https://m.zeeturf.fr/rest/api/2/race/{course_id};;"]
    )

    with pytest.raises(CourseContextError):
        resolve_course_context(schedule_file=schedule, planning_dir=None)
