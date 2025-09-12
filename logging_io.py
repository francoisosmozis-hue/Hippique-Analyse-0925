import json
from pathlib import Path
from typing import Iterable, Mapping

# CSV header for the tracking file.
CSV_HEADER = [
    "reunion",
    "course",
    "hippodrome",
    "date",
    "discipline",
    "partants",
    "nb_tickets",
    "total_stake",
    "ev_sp",
    "ev_global",
    "roi_sp",
    "roi_global",
    "risk_of_ruin",
    "clv_moyen",
    "model",
]


def append_csv_line(path: str, data: Mapping[str, object], header: Iterable[str] = CSV_HEADER) -> None:
    """Append a line to a CSV file ensuring the header exists.

    Parameters
    ----------
    path: str
        Target CSV file.
    data: Mapping[str, object]
        Mapping of column names to values.
    header: Iterable[str]
        Sequence of column names used as CSV header.
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not file_path.exists()
    with file_path.open("a", encoding="utf-8") as fh:
        if is_new:
            fh.write(";".join(header) + "\n")
        line = ";".join(str(data.get(col, "")) for col in header)
        fh.write(line + "\n")


def append_json(path: str, data: object) -> None:
    """Write JSON data to *path* creating parent directories."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
