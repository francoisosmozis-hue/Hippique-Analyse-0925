"""Daily plan builder from ZEturf and Geny sources."""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .logging_utils import get_logger

LOGGER = get_logger(__name__)

ZETURF_BASE_URL = "https://www.zeturf.fr"
GENY_BASE_URL = "https://www.geny.com"
USER_AGENT = "Hippique-Analyse/1.0 (contact: ops@hippique.local)"
_REQUEST_INTERVAL_SECONDS = 1.1  # throttle 1 req/s per host
_LAST_REQUEST_BY_HOST: Dict[str, float] = {}

COURSE_RE = re.compile(
    r"/fr/course/(?P<date>\d{4}-\d{2}-\d{2})/R(?P<r>\d+)C(?P<c>\d+)-",
    re.IGNORECASE,
)
COURSE_ID_RE = re.compile(r"R(?P<r>\d+)C(?P<c>\d+)", re.IGNORECASE)


@dataclass(order=True)
class CoursePlan:
    """Representation of a course entry in the plan."""

    sort_index: tuple = field(init=False, repr=False)
    date: str
    r_label: str
    c_label: str
    meeting: str
    time_local: Optional[str]
    course_url: str
    reunion_url: Optional[str] = None

    def __post_init__(self) -> None:
        self.sort_index = self._compute_sort_index()

    def _compute_sort_index(self) -> tuple:
        if self.time_local:
            hour, minute = [int(part) for part in self.time_local.split(":", 1)]
        else:
            hour, minute = 99, 99
        reunion_num = int(re.sub(r"[^0-9]", "", self.r_label) or 0)
        course_num = int(re.sub(r"[^0-9]", "", self.c_label) or 0)
        return (hour, minute, reunion_num, course_num)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.date, self.r_label, self.c_label)

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "date": self.date,
            "r_label": self.r_label,
            "c_label": self.c_label,
            "meeting": self.meeting,
            "time_local": self.time_local,
            "course_url": self.course_url,
            "reunion_url": self.reunion_url,
        }


def _throttled_get(url: str, *, timeout: int = 15, attempts: int = 3) -> str:
    """HTTP GET with throttle, retries and jitter backoff."""
    
    parsed = urlparse(url)
    host = parsed.netloc
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(1, attempts + 1):
        while True:
            last_call = _LAST_REQUEST_BY_HOST.get(host)
            now = time.monotonic()
            if not last_call or now - last_call >= _REQUEST_INTERVAL_SECONDS:
                break
            time.sleep(_REQUEST_INTERVAL_SECONDS - (now - last_call))
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            _LAST_REQUEST_BY_HOST[host] = time.monotonic()
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            LOGGER.warning(
                "http_retry",
                extra={
                    "url": url,
                    "attempt": attempt,
                    "error": str(exc),
                },
            )
            if attempt >= attempts:
                raise
            sleep_time = _REQUEST_INTERVAL_SECONDS * attempt + random.uniform(0.2, 0.8)
            time.sleep(sleep_time)
    raise RuntimeError("Unreachable")


def build_plan(date: str) -> List[Dict[str, Optional[str]]]:
    """Build the plan for the provided date."""

    LOGGER.info("building_plan", extra={"date": date})
    entries = zeturf_parse_program(date)
    if not entries:
        LOGGER.warning("no_entries_from_zeturf", extra={"date": date})
    filled = geny_fill_times(date, entries)
    deduped: Dict[tuple[str, str, str], CoursePlan] = {}
    for entry in filled:
        if entry.key in deduped:
            LOGGER.debug("duplicate_entry", extra={"key": entry.key})
            continue
        deduped[entry.key] = entry
    plan = sorted(deduped.values())
    LOGGER.info("plan_built", extra={"date": date, "courses": len(plan)})
    return [item.to_dict() for item in plan]


def zeturf_parse_program(date: str) -> List[CoursePlan]:
    """Parse the ZEturf program for the given date."""

    url = f"{ZETURF_BASE_URL}/fr/programmes-et-pronostics?date={date}"
    html = _throttled_get(url)
    soup = BeautifulSoup(html, "lxml")
    entries: List[CoursePlan] = []
    for link in soup.select('a[href*="/fr/course/"]'):
        href = link.get("href")
        if not href:
            continue
        match = COURSE_RE.search(href)
        if not match:
            continue
        r_label = f"R{int(match.group('r'))}"
        c_label = f"C{int(match.group('c'))}"
        meeting = _extract_meeting_name(link)
        time_local = _extract_time_from_link(link)
        reunion_url = _extract_reunion_url(link)
        absolute_url = urljoin(ZETURF_BASE_URL, href)
        entries.append(
            CoursePlan(
                date=match.group("date"),
                r_label=r_label,
                c_label=c_label,
                meeting=meeting,
                time_local=time_local,
                course_url=absolute_url,
                reunion_url=reunion_url,
            )
        )
    return entries


def _extract_meeting_name(link) -> str:
    candidates = [
        link.get("data-meeting"),
        getattr(link, "text", "").strip(),
    ]
    for candidate in candidates:
        if candidate:
            return re.sub(r"\s+", " ", candidate)
    parent = link.find_parent(["article", "div", "li"])
    if parent:
        heading = parent.find(["h2", "h3", "h4", "strong"])
        if heading and heading.get_text(strip=True):
            return heading.get_text(strip=True)
    return ""


def _extract_time_from_link(link) -> Optional[str]:
    for attr in ("data-time", "data-course-time", "data-time-local"):
        value = link.get(attr)
        if value:
            return value.strip()[:5]
    time_container = link.find(class_=re.compile("heure|time", re.IGNORECASE))
    if time_container and time_container.get_text(strip=True):
        text = time_container.get_text(strip=True)
        match = re.search(r"(\d{1,2}:\d{2})", text)
        if match:
            return _normalise_time(match.group(1))
    return None


def _extract_reunion_url(link) -> Optional[str]:
    parent_link = link.find_parent("a")
    if parent_link and parent_link.get("href"):
        return urljoin(ZETURF_BASE_URL, parent_link["href"])
    parent = link.find_parent(["article", "div", "li"])
    if parent:
        reunion_anchor = parent.find("a", href=re.compile(r"/fr/reunion/"))
        if reunion_anchor and reunion_anchor.get("href"):
            return urljoin(ZETURF_BASE_URL, reunion_anchor["href"])
    return None


def _normalise_time(value: str) -> str:
    hour, minute = value.split(":", 1)
    return f"{int(hour):02d}:{int(minute):02d}"


def geny_fill_times(date: str, plan: Iterable[CoursePlan]) -> List[CoursePlan]:
    """Complete missing times using Geny as fallback."""

    entries = list(plan)
    missing = [entry for entry in entries if not entry.time_local]
    if not missing:
        return entries
    url = f"{GENY_BASE_URL}/programme-courses/{date}"
    try:
        html = _throttled_get(url)
    except requests.RequestException as exc:
        LOGGER.warning("geny_fetch_failed", extra={"url": url, "error": str(exc)})
        return entries
    soup = BeautifulSoup(html, "lxml")
    times_map: Dict[tuple[str, str], str] = {}
    for element in soup.select("[data-race], a[href*='R'][href*='C']"):
        race_id = element.get("data-race") or element.get("data-race-id")
        if not race_id and element.has_attr("href"):
            race_id = _extract_race_from_href(element["href"])
        if not race_id:
            continue
        match = COURSE_ID_RE.search(race_id)
        if not match:
            continue
        time_text = _extract_time_from_element(element)
        if not time_text:
            continue
        key = (f"R{int(match.group('r'))}", f"C{int(match.group('c'))}")
        times_map[key] = time_text
    for entry in entries:
        if entry.time_local:
            continue
        entry.time_local = times_map.get((entry.r_label, entry.c_label))
        entry.sort_index = entry._compute_sort_index()
    return entries


def _extract_race_from_href(href: str) -> Optional[str]:
    match = COURSE_ID_RE.search(href)
    if match:
        return match.group(0)
    return None


def _extract_time_from_element(element) -> Optional[str]:
    for attr in ("data-time", "data-course-time", "data-time-local"):
        value = element.get(attr)
        if value:
            return _normalise_time(value)
    text = element.get_text(" ", strip=True)
    match = re.search(r"(\d{1,2}:\d{2})", text)
    if match:
        return _normalise_time(match.group(1))
    return None


__all__ = [
    "build_plan",
    "geny_fill_times",
    "zeturf_parse_program",
    "CoursePlan",
]
