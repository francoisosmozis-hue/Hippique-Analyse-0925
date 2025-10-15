"""Helpers to materialise jockey/entraineur statistics from a snapshot."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any, Iterable, Mapping, TypeAlias


LOGGER = logging.getLogger(__name__)

ResultDict: TypeAlias = dict[str, str | None]


def enrich_from_snapshot(snapshot_path: str, out_dir: str) -> dict:
    """Build ``je_stats.csv`` and ``chronos.csv`` files from ``snapshot_path``.

    Parameters
    ----------
    snapshot_path:
        Path to the JSON snapshot describing the runners.
    out_dir:
        Directory where the CSV files will be written.

    Returns
    -------
    dict
        Mapping with the keys ``"je_stats"`` and ``"chronos"`` whose values are the
        paths to the generated files (as strings) or ``None`` when the artefact
        could not be produced.
    """

    result: ResultDict = {"je_stats": None, "chronos": None}

    snapshot_file = Path(snapshot_path)
    try:
        raw_payload = json.loads(snapshot_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        LOGGER.warning("Snapshot %s does not exist", snapshot_file)
        return result
    except (OSError, json.JSONDecodeError):
        LOGGER.exception("Unable to load snapshot %s", snapshot_file)
        return result

    if not isinstance(raw_payload, Mapping):
        LOGGER.warning("Snapshot %s is not a JSON object", snapshot_file)
        payload: Mapping[str, Any] = {}
    else:
        payload = raw_payload

    runners_field = payload.get("runners")
    runners: list[Mapping[str, Any]] = []
    if isinstance(runners_field, list):
        for index, runner in enumerate(runners_field):
            if isinstance(runner, Mapping):
                runners.append(runner)
            else:
                LOGGER.warning(
                    "Runner entry %s in %s is not an object and will be ignored",
                    index,
                    snapshot_file,
                )
    else:
        LOGGER.warning("Snapshot %s is missing a 'runners' array", snapshot_file)

    normalised = list(_normalise_runners(runners, snapshot_file))

    output_dir = Path(out_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        LOGGER.exception("Unable to create output directory %s", output_dir)
        return result

    je_path = output_dir / "je_stats.csv"
    chronos_path = output_dir / "chronos.csv"

    try:
        _write_csv(je_path, normalised, ("num", "nom", "j_rate", "e_rate"))
    except OSError:
        LOGGER.exception("Failed to write JE statistics CSV at %s", je_path)
    else:
        result["je_stats"] = str(je_path)
        
    try:
        _write_csv(chronos_path, normalised, ("num", "chrono"))
    except OSError:
        LOGGER.exception("Failed to write chronos CSV at %s", chronos_path)
    else:
        result["chronos"] = str(chronos_path)

    return result


def _normalise_runners(
    runners: Iterable[Mapping[str, Any]], snapshot_file: Path
) -> Iterable[dict[str, str]]:
    for index, runner in enumerate(runners):
        descriptor = _runner_descriptor(runner, index)
        num = _extract_value(
            runner,
            ("num", "number", "id"),
            snapshot_file,
            descriptor,
            "num",
        )
        yield {
            "num": num,
            "nom": _extract_value(
                runner,
                ("nom", "name", "horse", "label"),
                snapshot_file,
                descriptor,
                "nom",
            ),
            "j_rate": _extract_value(
                runner,
                ("j_rate", "j_win", "jockey_rate"),
                snapshot_file,
                descriptor,
                "j_rate",
            ),
            "e_rate": _extract_value(
                runner,
                ("e_rate", "e_win", "trainer_rate"),
                snapshot_file,
                descriptor,
                "e_rate",
            ),
            "chrono": _extract_value(
                runner,
                ("chrono", "time"),
                snapshot_file,
                descriptor,
                "chrono",
            ),
        }

        
def _runner_descriptor(runner: Mapping[str, Any], index: int) -> str:
    for key in ("num", "number", "id"):
        value = runner.get(key)
        if value not in (None, ""):
            return f"{key}={value}"
    return f"index {index}"


def _extract_value(
    runner: Mapping[str, Any],
    keys: Iterable[str],
    snapshot_file: Path,
    descriptor: str,
    label: str,
) -> str:
    for key in keys:
        value = runner.get(key)
        if value not in (None, ""):
            return str(value)

    LOGGER.warning(
        "Runner %s in %s is missing '%s'; using empty string",
        descriptor,
        snapshot_file,
        label,
    )
    return ""


def _write_csv(path: Path, rows: Iterable[dict[str, str]], columns: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = list(columns)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(column, "") for column in header])


def http_get(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    headers: Mapping[str, str] | None = None,
) -> str:
    """Return the body of an HTTP ``GET`` request.

    The helper centralises default headers and converts ``requests`` specific
    exceptions into ``RuntimeError`` instances so that callers do not have to
    depend on the underlying library.
    """

    caller: Callable[..., requests.Response]
    if session is None:
        caller = requests.get
    else:
        caller = session.get

    merged_headers = dict(DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)

    try:
        response = caller(url, headers=merged_headers, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:  # pragma: no cover - network errors
        raise RuntimeError(f"HTTP request failed for {url}") from exc

    return response.text


@lru_cache(maxsize=512)
def _normalise_text(value: str) -> str:
    """Return a case and diacritics insensitive representation of ``value``."""

    decomposed = unicodedata.normalize("NFKD", value)
    cleaned = "".join(char for char in decomposed if char.isalnum())
    return cleaned.lower()


def discover_horse_url_by_name(
    name: str,
    *,
    get: Callable[[str], str] | None = None,
) -> str | None:
    """Return the Geny horse profile URL for ``name`` when available."""

    if not name or not name.strip():
        return None

    fetch = get or http_get
    query = quote_plus(name.strip())
    search_url = f"{GENY_BASE_URL}/recherche?query={query}"

    try:
        html = fetch(search_url)
    except RuntimeError:
        LOGGER.warning("Failed to fetch Geny search results for %s", name)
        return None

    soup = BeautifulSoup(html, "html.parser")
    target_norm = _normalise_text(name)

    best_url: str | None = None
    best_score = 0.0

    for link in soup.select("a[href]"):
        href = link.get("href")
        if not href or "/chev" not in href:
            continue

        candidate_text = link.get_text(" ", strip=True)
        if not candidate_text:
            continue

        candidate_norm = _normalise_text(candidate_text)
        if candidate_norm == target_norm:
            return urljoin(GENY_BASE_URL, href)

        score = difflib.SequenceMatcher(None, target_norm, candidate_norm).ratio()
        if score > best_score:
            best_score = score
            best_url = urljoin(GENY_BASE_URL, href)

    return best_url


def extract_links_from_horse_page(html: str) -> dict[str, str]:
    """Return profile links for the jockey and the trainer."""

    soup = BeautifulSoup(html, "html.parser")
    links: dict[str, str] = {}

    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        if not href:
            continue

        absolute = urljoin(GENY_BASE_URL, href)
        text = anchor.get_text(" ", strip=True).lower()
        href_lower = absolute.lower()

        if "jockey" in text or "driver" in text or re.search(r"/jockey|/driver", href_lower):
            links.setdefault("jockey", absolute)
        if (
            "entraine" in text
            or "entraîne" in text
            or "trainer" in text
            or "coach" in text
            or re.search(r"/entraine|/entraineur|/trainer|/coach", href_lower)
        ):
            links.setdefault("trainer", absolute)

    return links


_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_RATIO_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
_VICTORY_RE = re.compile(r"victoires?\s*[:=]\s*(\d+)", re.IGNORECASE)


def _parse_percentage(text: str) -> float | None:
    """Extract a percentage-like value from ``text``."""

    if not text:
        return None

    percent = _PERCENT_RE.search(text)
    if percent:
        return float(percent.group(1).replace(",", "."))

    ratio = _RATIO_RE.search(text)
    if ratio:
        numerator = int(ratio.group(1))
        denominator = int(ratio.group(2))
        if denominator:
            return round(100.0 * numerator / denominator, 2)

    victory = _VICTORY_RE.search(text)
    if victory:
        return float(victory.group(1))

    number = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not number:
        return None

    try:
        value = float(number.group(1).replace(",", "."))
    except ValueError:
        return None

    if 0.0 <= value <= 1.0:
        return round(value * 100, 2)
    if 0.0 <= value <= 100.0:
        return value
    return None


def extract_rate_from_profile(html: str) -> float | None:
    """Return the win percentage contained in a profile page."""

    soup = BeautifulSoup(html, "html.parser")

    for element in soup.find_all(["span", "div", "td", "th", "p", "li", "strong", "b"]):
        text = element.get_text(" ", strip=True)
        rate = _parse_percentage(text)
        if rate is not None:
            return rate

    fallback = soup.get_text(" ", strip=True)
    return _parse_percentage(fallback)


def parse_horse_percentages(
    horse_name: str,
    *,
    get: Callable[[str], str] | None = None,
) -> tuple[float | None, float | None]:
    """Return the jockey and trainer win percentages for ``horse_name``."""

    fetch = get or http_get
    horse_url = discover_horse_url_by_name(horse_name, get=fetch)
    if not horse_url:
        return None, None

    try:
        horse_html = fetch(horse_url)
    except RuntimeError:
        LOGGER.warning("Failed to fetch horse page %s", horse_url)
        return None, None

    links = extract_links_from_horse_page(horse_html)
    jockey_rate = trainer_rate = None

    jockey_link = links.get("jockey")
    if jockey_link:
        try:
            jockey_rate = extract_rate_from_profile(fetch(jockey_link))
        except RuntimeError:
            LOGGER.warning("Failed to fetch jockey profile %s", jockey_link)

    trainer_link = links.get("trainer")
    if trainer_link:
        try:
            trainer_rate = extract_rate_from_profile(fetch(trainer_link))
        except RuntimeError:
            LOGGER.warning("Failed to fetch trainer profile %s", trainer_link)

    return jockey_rate, trainer_rate


__all__ = [
    "enrich_from_snapshot",
    "discover_horse_url_by_name",
    "http_get",
    "extract_links_from_horse_page",
    "extract_rate_from_profile",
    "parse_horse_percentages",
]
