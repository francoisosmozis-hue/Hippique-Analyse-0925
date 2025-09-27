"""Tools for fetching meetings from Zeturf and computing odds drifts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Sequence, TypeVar

try:
    import requests
except ModuleNotFoundError as exc:  # pragma: no cover - exercised via dedicated test
    raise RuntimeError(
        "The 'requests' package is required to fetch data from Zeturf. "
        "Install it with 'pip install requests' or switch to the urllib-based fallback implementation."
    ) from exc
import yaml
from bs4 import BeautifulSoup
import re

try:  # pragma: no cover - Python < 3.9 fallbacks are extremely rare
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - very defensive
    ZoneInfo = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


class EmptyDomError(RuntimeError):
    """Raised when an HTML payload lacks meaningful DOM nodes."""


T = TypeVar("T")


def _retry_with_backoff(
    operation: Callable[[], T],
    *,
    retries: int = 3,
    initial_delay: float = 0.5,
    backoff: float = 1.5,
    retry_exceptions: Iterable[type[BaseException]] = (Exception,),
) -> T:
    """Execute ``operation`` retrying failures with exponential backoff."""

    attempts = max(1, int(retries))
    delay = max(0.0, float(initial_delay))
    factor = backoff if backoff > 0 else 1.0
    retry_types = tuple(retry_exceptions)

    last_exc: BaseException | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except retry_types as exc:  # type: ignore[misc]
            last_exc = exc
            if attempt == attempts - 1:
                break
            if delay:
                time.sleep(delay)
                delay *= factor

    if last_exc is not None:
        raise last_exc

    raise RuntimeError("Operation failed without raising an exception")


def _http_get_with_backoff(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: int = 10,
    retries: int = 3,
    initial_delay: float = 0.5,
    backoff: float = 1.5,
    require_text: bool = False,
):
    """Return an HTTP response, retrying on throttling or empty payloads."""

    def _request() -> requests.Response:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        if require_text and not (resp.text and resp.text.strip()):
            raise EmptyDomError(f"Empty DOM response received from {url}")
        return resp

    return _retry_with_backoff(
        _request,
        retries=retries,
        initial_delay=initial_delay,
        backoff=backoff,
        retry_exceptions=(requests.RequestException, EmptyDomError),
    )


GENY_BASE = "https://www.geny.com"
HDRS = {"User-Agent": "Mozilla/5.0 (+EV; GPI v5.1)"}
GENY_FALLBACK_URL = f"{GENY_BASE}/reunions-courses-pmu"
COURSE_PAGE_TEMPLATES: Sequence[str] = (
    "https://www.zeturf.fr/fr/course/{course_id}",
    "https://www.zeturf.fr/course/{course_id}",
    "https://m.zeeturf.fr/fr/course/{course_id}",
)

_SCRAPED_START_TIMES: Dict[str, str] = {}

_COURSE_PLACEHOLDER = re.compile(r"{\s*course[_-]?id\s*}", re.IGNORECASE)
_COURSE_ID_PATTERN = re.compile(r"\d{5,}")
_RC_PATTERN = re.compile(r"^R\d+C\d+$", re.IGNORECASE)
_COURSE_JSON_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r'courseId["\']?\s*[:=]\s*"?(\d{5,})'),
    re.compile(r'course_id["\']?\s*[:=]\s*"?(\d{5,})'),
    re.compile(r'idCourse["\']?\s*[:=]\s*"?(\d{5,})'),
    re.compile(r'id_course["\']?\s*[:=]\s*"?(\d{5,})'),
    re.compile(r"course/(\d{5,})"),
    re.compile(r"race/(\d{5,})"),
)
_COURSE_LINK_PATTERNS: Sequence[re.Pattern[str]] = (
    re.compile(r"/course/(\d{5,})"),
    re.compile(r"/race/(\d{5,})"),
)
_COURSE_ATTR_HINTS: Sequence[str] = (
    "data-course-id",
    "data-courseid",
    "data-course",
    "data-idcourse",
    "data-courseId",
    "data-id-course",
    "data-race-id",
    "data-raceid",
    "data-event-id",
    "data-eventid",
)

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


_TEXTUAL_TIME_PATTERN = re.compile(
    r"(\d{1,2})\s*(?:heures?|heure|hours?|hrs?|hres?|[hH:.\u202f])\s*(\d{1,2})?\s*(?:mn|minutes?)?",
    re.IGNORECASE,
)
_HOUR_ONLY_PATTERN = re.compile(
    r"(\d{1,2})\s*(?:heures?|heure|hours?|hrs?|hres?|[hH])",
    re.IGNORECASE,
)

@lru_cache(maxsize=1)
def _env_timezone() -> dt.tzinfo | None:
    """Return the timezone configured via ``$TZ`` when available."""

    if ZoneInfo is None:
        return None

    tz_name = os.environ.get("TZ")
    if not tz_name:
        return None

    try:
        return ZoneInfo(tz_name)
    except Exception:  # pragma: no cover - invalid/unknown TZ identifiers
        return None


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
    
    resp = _http_get_with_backoff(GENY_FALLBACK_URL, timeout=10, require_text=True)
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
    payload = resp.json()

    if isinstance(payload, Mapping) and course_id:
        start_time = _detect_start_time(payload)
        if not start_time:
            scraped = _scrape_start_time_from_course_page(course_id)
            if scraped:
                meta = payload.get("meta") if isinstance(payload.get("meta"), Mapping) else {}
                updated_meta = dict(meta) if meta else {}
                updated_meta.setdefault("start_time", scraped)
                payload["meta"] = updated_meta
                payload.setdefault("start_time", scraped)

        payload.setdefault("course_id", course_id)

    return payload


def _normalise_rc(value: Any) -> str | None:
    """Return the canonical ``R<d>C<d>`` representation for ``value``."""

    if value is None:
        return None
    text = str(value).strip().upper().replace(" ", "")
    if not text:
        return None
    if _RC_PATTERN.match(text):
        return text
    return None


def _resolve_rc_entry(rc: str, obj: Any, *, visited: set[int] | None = None) -> Any:
    """Return the configuration entry associated with ``rc`` in ``obj``.

    The search inspects nested mappings/lists, recognising either explicit ``rc``
    keys or combinations of ``reunion``/``course`` values.
    """

    if visited is None:
        visited = set()

    if isinstance(obj, Mapping):
        obj_id = id(obj)
        if obj_id in visited:
            return None
        visited.add(obj_id)

        for key, value in obj.items():
            key_rc = _normalise_rc(key)
            if key_rc == rc:
                return value

        rc_candidates = [
            obj.get("rc"),
            obj.get("race_id"),
            obj.get("race"),
            obj.get("course_label"),
        ]
        for candidate in rc_candidates:
            if _normalise_rc(candidate) == rc:
                return obj

        reunion = obj.get("reunion") or obj.get("meeting") or obj.get("r")
        course = obj.get("course") or obj.get("race") or obj.get("c")
        if reunion and course:
            combined = _normalise_rc(f"{reunion}{course}")
            if combined == rc:
                return obj

        for value in obj.values():
            if isinstance(value, (Mapping, list, tuple, set)):
                found = _resolve_rc_entry(rc, value, visited=visited)
                if found is not None:
                    return found
        return None

    if isinstance(obj, (list, tuple, set)):
        for item in obj:
            found = _resolve_rc_entry(rc, item, visited=visited)
            if found is not None:
                return found
    return None


def _extract_course_id_from_entry(entry: Any, *, visited: set[int] | None = None) -> str | None:
    """Extract ``course_id`` from ``entry`` when present."""

    if entry is None:
        return None

    if isinstance(entry, str):
        text = entry.strip()
        if text.isdigit():
            return text
        match = _COURSE_ID_PATTERN.search(text)
        if match:
            return match.group(0)
        return None

    if not isinstance(entry, Mapping):
        if isinstance(entry, (list, tuple, set)):
            for item in entry:
                course_id = _extract_course_id_from_entry(item, visited=visited)
                if course_id:
                    return course_id
        return None

    if visited is None:
        visited = set()
    obj_id = id(entry)
    if obj_id in visited:
        return None
    visited.add(obj_id)

    for key in ("course_id", "id_course", "courseId", "idCourse", "id", "numero", "number"):
        if key in entry:
            value = entry[key]
            if isinstance(value, (int, str)):
                text = str(value).strip()
                if text.isdigit():
                    return text
                match = _COURSE_ID_PATTERN.search(text)
                if match:
                    return match.group(0)

    for value in entry.values():
        if isinstance(value, (Mapping, list, tuple, set)):
            course_id = _extract_course_id_from_entry(value, visited=visited)
            if course_id:
                return course_id

    return None


def _extract_url_from_entry(entry: Any) -> str | None:
    """Return a URL embedded in ``entry`` when available."""

    if entry is None:
        return None

    if isinstance(entry, str):
        text = entry.strip()
        if text.startswith("http://") or text.startswith("https://"):
            return text
        return None

    if isinstance(entry, Mapping):
        for key in _URL_FIELDS:
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in entry.values():
            if isinstance(value, (Mapping, list, tuple, set, str)):
                url = _extract_url_from_entry(value)
                if url:
                    return url
    elif isinstance(entry, (list, tuple, set)):
        for item in entry:
            url = _extract_url_from_entry(item)
            if url:
                return url

    return None


def fetch_race_snapshot(
    rc: str,
    *,
    phase: str,
    sources: Mapping[str, Any],
    url: str | None = None,
    retries: int = 3,
    backoff: float = 1.5,
    initial_delay: float = 0.5,
) -> Dict[str, Any]:
    """Return a normalized snapshot for ``rc`` using ``sources`` configuration."""

    rc_norm = _normalise_rc(rc)
    if not rc_norm:
        raise ValueError("rc must follow pattern R<C> with digits, e.g. R1C3")

    if not isinstance(sources, Mapping):
        raise ValueError("sources must be a mapping configuration")

    phase_tag, mode_key, _ = _normalise_snapshot_phase(phase)
    retries = max(1, int(retries))
    backoff = float(backoff) if backoff > 0 else 1.0
    delay = max(0.0, float(initial_delay))

    config: MutableMapping[str, Any]
    if isinstance(sources, MutableMapping):
        config = sources
    else:
        config = dict(sources)

    entry = _resolve_rc_entry(rc_norm, config)
    course_id = _extract_course_id_from_entry(entry)
    entry_url = _extract_url_from_entry(entry)

    if url:
        entry_url = url.strip()
        if not course_id:
            match = _COURSE_ID_PATTERN.search(entry_url)
            if match:
                course_id = match.group(0)

    template = resolve_source_url(config, mode_key)

    if entry_url:
        if _COURSE_PLACEHOLDER.search(entry_url) or "{course_id}" in entry_url:
            if not course_id:
                raise ValueError(f"No course_id configured for {rc_norm}")
            fetch_url = _inject_course_id(entry_url, course_id)
        else:
            fetch_url = entry_url
    else:
        if not course_id:
            raise ValueError(f"Unable to resolve course_id for {rc_norm}")
        fetch_url = _inject_course_id(template, course_id)

   def _do_fetch() -> Dict[str, Any]:
        return fetch_runners(fetch_url)

    try:
        payload = _retry_with_backoff(
            _do_fetch,
            retries=retries,
            initial_delay=delay,
            backoff=backoff,
            retry_exceptions=(requests.RequestException,),
        )
    except requests.RequestException:
        raise

    if isinstance(payload, MutableMapping):
        payload.setdefault("rc", rc_norm)
        if course_id:
            payload.setdefault("course_id", course_id)
        match = re.match(r"R(\d+)C(\d+)", rc_norm)
        if match:
            payload.setdefault("reunion", f"R{int(match.group(1))}")
            payload.setdefault("course", f"C{int(match.group(2))}")
        payload.setdefault("phase", phase_tag)
    return normalize_snapshot(payload)


def _rows_to_runners(rows: Iterable[Any]) -> List[Dict[str, Any]]:
    """Return runners extracted from table rows."""

    runners: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for tr in rows:
        if not hasattr(tr, "find_all"):
            continue
        cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(cols) < 2:
            continue
        num = cols[0].strip()
        if not num.isdigit() or num in seen:
            continue
        seen.add(num)
        runner: Dict[str, Any] = {"num": num, "name": cols[1] or num}
        if len(cols) > 2 and cols[2]:
            runner["jockey"] = cols[2]
        if len(cols) > 3 and cols[3]:
            runner["entraineur"] = cols[3]
        runners.append(runner)
    return runners

    
def _parse_geny_runners(soup: BeautifulSoup, html: str) -> List[Dict[str, Any]]:
    """Parse runner information from Geny partants HTML."""

    runners = _rows_to_runners(soup.select("tr"))
    if runners:
        return runners

    runners = _rows_to_runners(soup.find_all("tr"))
    if runners:
        return runners

    attr_based: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for tag in soup.find_all(attrs={"data-num": True}):
        num = str(tag.get("data-num", "")).strip()
        if not num.isdigit() or num in seen:
            continue
        name = (
            tag.get("data-name")
            or tag.get("data-cheval")
            or tag.get("data-horse")
            or tag.get("data-runner")
        )
        if not name:
            name = tag.get_text(" ", strip=True)
            if name.startswith(num):
                name = name[len(num) :].strip()
        runner: Dict[str, Any] = {"num": num, "name": (name or "").strip() or num}
        jockey = tag.get("data-jockey") or tag.get("data-driver")
        trainer = tag.get("data-entraineur") or tag.get("data-trainer")
        if jockey:
            runner["jockey"] = str(jockey).strip()
        if trainer:
            runner["entraineur"] = str(trainer).strip()
        attr_based.append(runner)
        seen.add(num)
    if attr_based:
        return attr_based

    rows_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
    cell_pattern = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
    parsed: List[Dict[str, Any]] = []
    seen.clear()
    for row_html in rows_pattern.findall(html):
        cells = [
            BeautifulSoup(cell, "html.parser").get_text(strip=True)
            for cell in cell_pattern.findall(row_html)
        ]
        if len(cells) < 2:
            continue
        num = cells[0].strip()
        if not num.isdigit() or num in seen:
            continue
        runner: Dict[str, Any] = {"num": num, "name": cells[1] or num}
        if len(cells) > 2 and cells[2]:
            runner["jockey"] = cells[2]
        if len(cells) > 3 and cells[3]:
            runner["entraineur"] = cells[3]
        parsed.append(runner)
        seen.add(num)
    if parsed:
        return parsed

    attr_block_pattern = re.compile(
        r'data-num=["\'](?P<num>\d+)["\'](?P<body>.*?)(?=data-num=["\']\d+["\']|$)',
        re.IGNORECASE | re.DOTALL,
    )
    parsed = []
    seen.clear()
    for match in attr_block_pattern.finditer(html):
        num = match.group("num")
        if num in seen:
            continue
        body = match.group("body")
        name_match = re.search(
            r"data-(?:name|cheval|horse|runner)=[\"']([^\"']+)[\"']",
            body,
            re.IGNORECASE,
        )
        name = name_match.group(1).strip() if name_match else num
        runner: Dict[str, Any] = {"num": num, "name": name or num}
        jockey_match = re.search(
            r"data-(?:jockey|driver)=[\"']([^\"']+)[\"']",
            body,
            re.IGNORECASE,
        )
        trainer_match = re.search(
            r"data-(?:entraineur|trainer)=[\"']([^\"']+)[\"']",
            body,
            re.IGNORECASE,
        )
        if jockey_match:
            runner["jockey"] = jockey_match.group(1).strip()
        if trainer_match:
            runner["entraineur"] = trainer_match.group(1).strip()
        parsed.append(runner)
        seen.add(num)
    if parsed:
        return parsed

    text = soup.get_text("\n", strip=True)
    text_pattern = re.compile(r"^(?P<num>\d{1,3})\s+(?P<name>.+)$", re.MULTILINE)
    parsed = []
    seen.clear()
    for match in text_pattern.finditer(text):
        num = match.group("num")
        if num in seen:
            continue
        name = match.group("name").strip()
        if not name:
            continue
        parsed.append({"num": num, "name": name})
        seen.add(num)
    return parsed


def fetch_from_geny_idcourse(id_course: str) -> Dict[str, Any]:
    """Return a snapshot for ``id_course`` scraped from geny.com.

    Parameters
    ----------
    id_course:
        Identifier of the course on geny.com.
    """

    partants_url = f"{GENY_BASE}/partants-pmu/_c{id_course}"
    cotes_url = f"{GENY_BASE}/cotes?id_course={id_course}"

    resp_partants = _http_get_with_backoff(
        partants_url,
        headers=HDRS,
        timeout=10,
        require_text=True,
    )
    html = resp_partants.text
    soup = BeautifulSoup(html, "html.parser")

    text = soup.get_text(" ", strip=True)
    match = re.search(r"R\d+", text)
    r_label = match.group(0) if match else None
    start_time = _extract_start_time(html)

    runners = _parse_geny_runners(soup, html)
    if not runners:
        logger.warning("No runners parsed from Geny partants page for %s", id_course)

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
    if start_time:
        snapshot["start_time"] = start_time
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


def _normalise_start_time(value: Any) -> str | None:
    """Return a ``HH:MM`` representation for ``value`` when possible."""

    if value in (None, ""):
        return None

    if isinstance(value, (int, float)):
        text = f"{int(value):04d}"
    else:
        text = str(value).strip()
    if not text:
        return None

    text = text.replace("\u202f", " ")

    # Direct digit-based formats such as 1305 or 13:05
    if len(text) == 4 and text.isdigit():
        return f"{text[:2]}:{text[2:]}"
    if len(text) >= 5 and text[2] == ":" and text[:2].isdigit():
        try:
            hour = int(text[:2]) % 24
            minute = int(text[3:5])
        except ValueError:
            pass
        else:
            return f"{hour:02d}:{minute:02d}"

    cleaned = text.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(cleaned)
    except ValueError:
        match = _TEXTUAL_TIME_PATTERN.search(text)
        if match:
            hour = int(match.group(1)) % 24
            minute_str = match.group(2)
            minute = int(minute_str) if minute_str is not None else 0
            return f"{hour:02d}:{minute:02d}"

        # Handle explicit hour-only strings such as "13h" or "13 heures"
        hour_only = _HOUR_ONLY_PATTERN.search(text)
        if hour_only:
            hour = int(hour_only.group(1)) % 24
            return f"{hour:02d}:00"

        return text if text else None
    else:
        if parsed.tzinfo is not None:
            tz = _env_timezone()
            if tz is not None:
                parsed = parsed.astimezone(tz)
        return parsed.strftime("%H:%M")


def _detect_start_time(payload: Mapping[str, Any]) -> str | None:
    """Return an already-present start time in ``payload`` if available."""

    meta = payload.get("meta")
    if isinstance(meta, Mapping):
        for key in ("start_time", "start", "heure", "time", "hour"):
            formatted = _normalise_start_time(meta.get(key))
            if formatted:
                return formatted

    for key in ("start_time", "start", "heure", "time", "hour"):
        formatted = _normalise_start_time(payload.get(key))
        if formatted:
            return formatted

    return None


def _scrape_start_time_from_course_page(course_id: str) -> str | None:
    """Fetch the public course page and extract its start time."""

    cache_key = str(course_id)
    cached = _SCRAPED_START_TIMES.get(cache_key)
    if cached:
        return cached

    for template in COURSE_PAGE_TEMPLATES:
        url = template.format(course_id=course_id)
        try:
            resp = _http_get_with_backoff(
                url,
                headers=HDRS,
                timeout=10,
                require_text=True,
            )
        except (requests.RequestException, EmptyDomError):
            continue
        start_time = _extract_start_time(resp.text)
        if start_time:
            _SCRAPED_START_TIMES[cache_key] = start_time
            return start_time

    return None


def _extract_start_time(html: str) -> str | None:
    """Extract a start time from a Geny/Zeturf HTML fragment."""

    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    def _format_match(hour_text: str, minute_text: str | None) -> str:
        hour = int(hour_text) % 24
        minute = int(minute_text) if minute_text is not None else 0
        return f"{hour:02d}:{minute:02d}"

    def _from_text(text: str) -> str | None:
        cleaned = text.replace("\u202f", " ")
        cleaned = re.sub(r"\([^()]*\)", " ", cleaned)
        cleaned = re.sub(r"(?i)\b(?:mn|minutes?)\b", "", cleaned)
        cleaned = re.sub(r"\s*[hH]\s*", ":", cleaned)
        cleaned = cleaned.replace(".", ":")
        formatted = _normalise_start_time(cleaned)
        if formatted and re.fullmatch(r"\d{2}:\d{2}", formatted):
            return formatted
        match_local = _TEXTUAL_TIME_PATTERN.search(text)
        if match_local:
            return _format_match(match_local.group(1), match_local.group(2))
        return formatted if formatted and ":" in formatted else None

    def _from_attributes(tag: Any, *attrs: str) -> str | None:
        for attr in attrs:
            value = tag.get(attr)
            if not value:
                continue
            normalised = _normalise_start_time(value)
            if normalised and re.fullmatch(r"\d{2}:\d{2}", normalised):
                return normalised
            formatted = _from_text(str(value))
            if formatted:
                return formatted
            if normalised and ":" in normalised and re.search(r"\d", normalised):
                candidate = _from_text(normalised)
                if candidate:
                    return candidate
        return None

    for time_tag in soup.find_all("time"):
        formatted = _from_attributes(time_tag, "datetime", "content")
        if formatted:
            return formatted
        candidate_text = time_tag.get_text(" ", strip=True)
        formatted = _from_text(candidate_text)
        if formatted:
            return formatted

    def _from_json_ld(value: Any) -> str | None:
        if isinstance(value, Mapping):
            for key in ("startDate", "startTime", "start_time", "start"):
                formatted = _normalise_start_time(value.get(key))
                if formatted and re.fullmatch(r"\d{2}:\d{2}", formatted):
                    return formatted
                formatted = _from_text(str(value.get(key))) if value.get(key) else None
                if formatted:
                    return formatted
            for nested in value.values():
                formatted = _from_json_ld(nested)
                if formatted:
                    return formatted
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                formatted = _from_json_ld(item)
                if formatted:
                    return formatted
        elif isinstance(value, str):
            formatted = _from_text(value)
            if formatted:
                return formatted
        return None

    for script_tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text_content = script_tag.string or script_tag.get_text()
        if not text_content:
            continue
        try:
            data = json.loads(text_content)
        except (TypeError, ValueError):
            formatted = _from_text(text_content)
            if formatted:
                return formatted
            continue
        formatted = _from_json_ld(data)
        if formatted:
            return formatted

    attr_candidates = (
        "data-time",
        "data-start-time",
        "data-start-time-utc",
        "data-starttime",
        "data-starttime-utc",
        "data-starts",
        "data-starts-at",
        "data-event-time",
        "data-start-at",
        "data-start-date",
        "data-start-datetime",
        "data-startdatetime",
        "data-start-date-time",
        "data-scheduled-time",
        "data-scheduled-start",
        "data-scheduled-start-time",
        "data-time-start",
        "data-event-hour",
        "data-event-start",
        "data-heure",
        "data-heure-depart",
        "data-heure-depart-programme",
        "data-depart",
        "data-departure",
        "data-race-time",
        "data-race-hour",
        "data-race-start",
        "data-official-time",
    )
    for attr in attr_candidates:
        for tag in soup.find_all(attrs={attr: True}):
            formatted = _from_attributes(tag, attr)
            if formatted:
                return formatted

    keyword = re.compile(r"(heure|départ|depart|start|off)", re.IGNORECASE)
    for meta_tag in soup.find_all("meta"):
        meta_keys = [meta_tag.get(key) for key in ("property", "name", "itemprop")]
        if any(key and keyword.search(key) for key in meta_keys):
            formatted = _from_attributes(meta_tag, "content", "value")
            if formatted:
                return formatted
    attr_hint_names = ("aria-label", "title", "data-label", "data-tooltip")
    
    for tag in soup.find_all(True):
        descriptor = " ".join(
            [
                tag.name or "",
                " ".join(tag.get("class", [])),
                tag.get("id") or "",
            ]
        )
        attr_values = [tag.get(name) for name in attr_hint_names]
        if any(value and keyword.search(str(value)) for value in attr_values):
            formatted = _from_attributes(tag, *attr_hint_names)
            if formatted:
                return formatted
        if keyword.search(descriptor):
            formatted = _from_attributes(tag, *attr_hint_names)
            if formatted:
                return formatted
            text = tag.get_text(" ", strip=True)
            formatted = _from_text(text)
            if formatted and re.search(r"\d", text):
                return formatted

    match = _TEXTUAL_TIME_PATTERN.search(html)
    if match:
        return _format_match(match.group(1), match.group(2))

    return None


def _inject_course_id(url_template: str, course_id: str) -> str:
    """Return ``url_template`` with ``course_id`` injected."""

    if _COURSE_PLACEHOLDER.search(url_template):
        return _COURSE_PLACEHOLDER.sub(course_id, url_template)

    if "{course_id}" in url_template:
        return url_template.replace("{course_id}", course_id)

    if course_id in url_template:
        return url_template

    if "?" in url_template:
        separator = "&" if url_template.endswith(("&", "?")) else "&"
        return f"{url_template}{separator}course_id={course_id}"

    return f"{url_template.rstrip('/')}/{course_id}"


def _extract_course_ids_from_meeting(html: str) -> List[str]:
    """Return ordered course identifiers discovered in ``html``."""

    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    ordered: List[str] = []
    seen: set[str] = set()

    def _push(candidate: str | None) -> None:
        if not candidate:
            return
        match = _COURSE_ID_PATTERN.search(str(candidate))
        if not match:
            return
        value = match.group(0)
        if value in seen:
            return
        seen.add(value)
        ordered.append(value)

    for tag in soup.find_all(True):
        for attr in _COURSE_ATTR_HINTS:
            attr_value = tag.get(attr)
            if attr_value:
                _push(attr_value)
        if tag.name == "a" and tag.get("href"):
            href = tag.get("href")
            for pattern in _COURSE_LINK_PATTERNS:
                match = pattern.search(href)
                if match:
                    _push(match.group(1))
        if tag.name == "script":
            text = tag.string or tag.get_text()
            if not text:
                continue
            for pattern in _COURSE_JSON_PATTERNS:
                for match in pattern.findall(text):
                    _push(match)

    if not ordered:
        for pattern in _COURSE_JSON_PATTERNS:
            for match in pattern.findall(html):
                _push(match)

    return ordered


def _normalise_snapshot_phase(value: str) -> tuple[str, str, str]:
    """Return (phase_tag, mode, file_label) for ``value`` (H-30/H-5)."""

    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned == "H30":
        return "H30", "h30", "H-30"
    if cleaned == "H5":
        return "H5", "h5", "H-5"
    raise ValueError("snapshot must be H-30 ou H-5")


def normalize_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a normalized snapshot of runners with metadata."""
    rc = payload.get("rc", "")
    meta = {
        "rc": rc,
        "hippodrome": payload.get("hippodrome", ""),
        "date": payload.get("date", dt.date.today().isoformat()),
        "discipline": payload.get("discipline", ""),
    }
    course_id = payload.get("course_id") or payload.get("id_course") or payload.get("idCourse")
    if course_id:
        meta["course_id"] = str(course_id)

    rc_text = str(rc).strip().upper()
    if rc_text:
        match = re.search(r"R(\d+)C(\d+)", rc_text)
        if match:
            meta.setdefault("reunion", f"R{int(match.group(1))}")
            meta.setdefault("course", f"C{int(match.group(2))}")
    start_time = _detect_start_time(payload)
    if not start_time and course_id:
        start_time = _scrape_start_time_from_course_page(str(course_id))
    if not start_time:
        raw_meta = payload.get("meta") if isinstance(payload.get("meta"), Mapping) else None
        if isinstance(raw_meta, Mapping):
            start_time = _normalise_start_time(raw_meta.get("start_time"))
    if not start_time:
        start_time = _normalise_start_time(payload.get("start_time"))
    if start_time:
        meta["start_time"] = start_time
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

    meta.setdefault("partants", len(runners))

    meta.update({
        "runners": runners,
        "id2name": id2name,
        "odds": odds_map,
        "p_imp": implied,
    })
    _warn_missing_metadata(meta)
    return meta


def _warn_missing_metadata(meta: Mapping[str, Any]) -> None:
    """Emit warnings when critical metadata is missing."""

    missing: List[str] = []
    if not str(meta.get("hippodrome") or "").strip():
        missing.append("meeting")
    if not str(meta.get("discipline") or "").strip():
        missing.append("discipline")
    partants = meta.get("partants")
    try:
        partants_count = int(partants) if partants is not None else 0
    except (TypeError, ValueError):
        partants_count = 0
    if partants_count <= 0:
        missing.append("partants")

    if not missing:
        return

    rc = (
        meta.get("rc")
        or meta.get("course_id")
        or meta.get("reunion")
        or meta.get("id_course")
        or "unknown"
    )
    logger.warning("Missing snapshot metadata for %s: %s", rc, ", ".join(sorted(set(missing))))
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
    "fetch_race_snapshot",
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
    parser.add_argument("--mode", choices=["planning", "h30", "h5", "diff"], help="Mode classique (planning/h30/h5/diff)")
    parser.add_argument("--out", required=True, help="Fichier ou dossier de sortie")
    parser.add_argument("--sources", default="config/sources.yml", help="Fichier YAML des endpoints")
    parser.add_argument("--reunion-url", help="URL publique de la réunion ZEturf à parcourir")
    parser.add_argument("--snapshot", help="Phase pour --reunion-url (H-30 ou H-5)")
    args = parser.parse_args()

    if args.reunion_url:
        if args.mode:
            parser.error("--mode et --reunion-url sont mutuellement exclusifs")
        if not args.snapshot:
            parser.error("--snapshot est requis avec --reunion-url")

        phase_tag, mode_key, file_label = _normalise_snapshot_phase(args.snapshot)
        with open(args.sources, "r", encoding="utf-8") as fh:
            config = yaml.safe_load(fh) or {}
        url_template = resolve_source_url(config, mode_key)

        resp = requests.get(args.reunion_url, headers=HDRS, timeout=10)
        resp.raise_for_status()
        html = resp.text
        course_ids = _extract_course_ids_from_meeting(html)
        if not course_ids:
            raise ValueError("Aucun identifiant de course trouvé dans la page réunion")

        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        for course_id in course_ids:
            api_url = _inject_course_id(url_template, course_id)
            payload = fetch_runners(api_url)
            data = normalize_snapshot(payload)
            data.setdefault("course_id", str(course_id))

            reunion = data.get("reunion")
            course_label = data.get("course")
            rc = data.get("rc") or ""
            if reunion and course_label:
                folder_name = f"{reunion}{course_label}"
            elif rc:
                folder_name = re.sub(r"[^0-9A-Za-z]+", "", str(rc)) or str(course_id)
            else:
                folder_name = str(course_id)

            dest_dir = out_dir / folder_name
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"snapshot_{file_label}.json"
            dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            written += 1

        print(f"{written} snapshot(s) {phase_tag} enregistrés dans {out_dir}")
        return

    if not args.mode:
        parser.error("--mode est requis lorsque --reunion-url n'est pas utilisé")

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
