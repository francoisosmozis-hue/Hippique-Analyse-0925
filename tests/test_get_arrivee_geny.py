from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

if "bs4" not in sys.modules:
    # Provide a lightweight BeautifulSoup shim for environments where bs4 is unavailable.
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

        def find_all(self, name: str | None = None):
            matches = []
            for elem in self._element.iter():
                if name and elem.tag != name:
                    continue
                matches.append(_SoupNode(elem))
            return matches

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

        def get_text(self, separator: str = "", strip: bool = False) -> str:
            pieces = list(self._element.itertext())
            text = "".join(pieces)
            if strip:
                text = text.strip()
            if separator:
                text = separator.join(part for part in text.split())
            return text

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

    def BeautifulSoup(markup: str, parser: str | None = None):  # type: ignore[misc]
        return _SoupNode(_build_root(markup))

    sys.modules["bs4"] = SimpleNamespace(BeautifulSoup=BeautifulSoup)

from get_arrivee_geny import (  # noqa: E402
    PlanningEntry,
    fetch_arrival,
    load_planning,
    parse_arrival,
)


def test_load_planning_supports_multiple_layouts(tmp_path: Path) -> None:
    planning = {
        "date": "2024-09-10",
        "meetings": [
            {
                "label": "R1",
                "hippodrome": "Vincennes",
                "url_geny": "https://offline",
                "races": [
                    {"course": 3, "idcourse": "123", "time": "13:45", "result_path": "R1C3.html"},
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


def test_parse_arrival_supports_multiple_formats() -> None:
    html = """
    <html><head><script>var DATA = {"arrivee": [5, "2", 9]};</script></head>
    <body>
    <div>Arrivée officielle : 5 - 2 - 9</div>
    </body></html>
    """
    numbers = parse_arrival(html)
    assert numbers == ["5", "2", "9"]

    text = "Arrivee definitive 4-7-11"
    assert parse_arrival(text) == ["4", "7", "11"]

    # TODO: La logique de parsing CSV a été retirée de parse_arrival.
    # Cette partie du test doit être réévaluée.
    # csv_text = "place;numero\n1;3\n2;8\n3;5"
    # assert parse_arrival(csv_text) == ["1", "3", "2", "8", "3", "5"]


@pytest.mark.skip(reason="La fonctionnalité local_sources a été supprimée de PlanningEntry.")
def test_fetch_arrival_prefers_local_sources(tmp_path: Path) -> None:
    offline = tmp_path / "R1C2.html"
    offline.write_text("<div>Arrivée officielle : 8 - 4 - 5</div>", encoding="utf-8")

    entry = PlanningEntry(rc="R1C2", local_sources=[offline.name])
    entry.base_dir = tmp_path

    result = fetch_arrival(entry, search_roots=[])
    assert result["status"] == "ok"
    assert result["result"] == ["8", "4", "5"]
    assert Path(result["source_path"]).resolve() == offline.resolve()

    result = fetch_arrival(entry, search_roots=[])
    assert result["status"] == "ok"
    assert result["result"] == ["8", "4", "5"]
    assert Path(result["source_path"]).resolve() == offline.resolve()
