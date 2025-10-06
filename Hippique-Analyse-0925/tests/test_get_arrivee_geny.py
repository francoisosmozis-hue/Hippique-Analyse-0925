from __future__ import annotations

import json
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from pathlib import Path

import pytest

if "requests" not in sys.modules:

    class _DummyRequestException(Exception):
        pass

    def _dummy_get(*args: object, **kwargs: object) -> None:
        raise NotImplementedError("requests.get should be patched in tests")

    sys.modules["requests"] = SimpleNamespace(RequestException=_DummyRequestException, get=_dummy_get)


if "bs4" not in sys.modules:

    class _SoupNode:
        def __init__(self, element: ET.Element) -> None:
            self._element = element

        def get(self, key: str, default: object | None = None) -> object | None:
            if key == "class":
                value = self._element.attrib.get(key)
                if value is None:
                    return default
                return value.split()
            return self._element.attrib.get(key, default)

        def find_all(self, name: str | None = None, href: bool = False, attrs: dict[str, object] | None = None):
            matches = []
            for elem in self._element.iter():
                if name and elem.tag != name:
                    continue
                if href and "href" not in elem.attrib:
                    continue
                if attrs and not _match_attrs(elem, attrs):
                    continue
                matches.append(_SoupNode(elem))
            return matches

        def find(self, name: str | None = None, href: bool = False, attrs: dict[str, object] | None = None):
            results = self.find_all(name=name, href=href, attrs=attrs)
            return results[0] if results else None

        def select(self, selector: str):
            parts = [part for part in selector.split() if part]
            nodes = [self]
            for part in parts:
                tag, classes = _parse_selector(part)
                next_nodes = []
                for node in nodes:
                    for elem in node._element.iter():
                        if tag and elem.tag != tag:
                            continue
                        if classes and not _has_classes(elem, classes):
                            continue
                        next_nodes.append(_SoupNode(elem))
                nodes = next_nodes
            return nodes

        def select_one(self, selector: str):
            results = self.select(selector)
            return results[0] if results else None

        def get_text(self, separator: str = "", strip: bool = False) -> str:
            pieces = list(self._element.itertext())
            text = "".join(pieces)
            if strip:
                text = text.strip()
            if separator:
                text = separator.join(part for part in text.split())
            return text


    def _match_attrs(element: ET.Element, attrs: dict[str, object]) -> bool:
        for key, value in attrs.items():
            attr_val = element.attrib.get(key)
            if value is True:
                if attr_val is None:
                    return False
            elif key == "class":
                classes = attr_val.split() if attr_val else []
                expected = value if isinstance(value, (list, tuple)) else [value]
                if not all(cls in classes for cls in expected):
                    return False
            else:
                if attr_val != value:
                    return False
        return True


    def _parse_selector(selector: str) -> tuple[str | None, list[str]]:
        selector = selector.strip()
        if not selector:
            return None, []
        if "." in selector:
            parts = selector.split(".")
            tag = parts[0] or None
            classes = [part for part in parts[1:] if part]
        else:
            tag = selector or None
            classes = []
        return tag, classes


    def _has_classes(element: ET.Element, classes: list[str]) -> bool:
        attr_val = element.attrib.get("class", "")
        current = attr_val.split() if attr_val else []
        return all(cls in current for cls in classes)


    def _build_root(markup: str) -> ET.Element:
        try:
            return ET.fromstring(markup)
        except ET.ParseError:
            wrapper = f"<root>{markup}</root>"
            return ET.fromstring(wrapper)


    def BeautifulSoup(markup: str, parser: str | None = None) -> _SoupNode:  # type: ignore[misc]
        return _SoupNode(_build_root(markup))


    sys.modules["bs4"] = SimpleNamespace(BeautifulSoup=BeautifulSoup)

from get_arrivee_geny import (
    PlanningEntry,
    _resolve_course_url_from_meeting,
    load_planning,
    main,
    parse_arrival,
)


def test_load_planning_supports_multiple_layouts(tmp_path: Path) -> None:
    planning = {
        "date": "2024-09-10",
        "meetings": [
            {
                "label": "R1",
                "hippodrome": "Vincennes",
                "url_geny": "https://www.geny.com/r1",
                "races": [
                    {"course": 3, "idcourse": "123", "time": "13:45"},
                ],
            }
        ],
    }
    path = tmp_path / "planning.json"
    path.write_text(json.dumps(planning), encoding="utf-8")

    entries = load_planning(path)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.rc == "R1C3"
    assert entry.course_id == "123"
    assert entry.date == "2024-09-10"
    assert entry.hippodrome == "Vincennes"
    assert entry.url_geny == "https://www.geny.com/r1"


def test_parse_arrival_supports_multiple_patterns() -> None:
    html = """
    <html><head><script>var DATA = {"arrivee": [5, "2", 9]};</script></head>
    <body>
    <div>Arrivée officielle : 5 - 2 - 9</div>
    </body></html>
    """
    numbers = parse_arrival(html)
    assert numbers == ["5", "2", "9"]

    table_html = """
    <table>
      <thead><tr><th>Place</th><th>N°</th></tr></thead>
      <tbody>
        <tr><td>2</td><td>7</td></tr>
        <tr><td>1</td><td>4</td></tr>
      </tbody>
    </table>
    """
    numbers = parse_arrival(table_html)
    assert numbers == ["4", "7"]


def test_resolve_course_url_checks_all_data_course_nodes(monkeypatch) -> None:
    html = """
    <html><body>
        <a data-course="111" href="/course-111">R1 C2</a>
        <a data-course="222" href="/course-222">R1 C2</a>
    </body></html>
    """

    class DummyResponse:
        def __init__(self, text: str) -> None:
            self.text = text

    def fake_request(target_url: str) -> DummyResponse:
        assert target_url == "https://www.geny.com/reunion"
        return DummyResponse(html)

    monkeypatch.setattr("get_arrivee_geny._request", fake_request)

    entry = PlanningEntry(rc="R1C2", reunion="R1", course="C2", course_id="222")
    resolved = _resolve_course_url_from_meeting("https://www.geny.com/reunion", entry)
    assert resolved == "https://www.geny.com/course-222"


def test_main_errors_when_planning_file_missing(tmp_path: Path) -> None:
    missing_planning = tmp_path / "missing.json"
    out_path = tmp_path / "arrivals.json"

    with pytest.raises(SystemExit) as excinfo:
        main(["--planning", str(missing_planning), "--out", str(out_path)])

    message = str(excinfo.value)
    assert "Planning file" in message
    assert "online_fetch_zeturf.py --mode planning" in message
