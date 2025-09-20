from __future__ import annotations

from pathlib import Path

import json

from get_arrivee_geny import load_planning, parse_arrival


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
