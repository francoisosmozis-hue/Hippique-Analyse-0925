"""Restore archived snapshots and analyses from Google Drive."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterable

from scripts.drive_sync import _build_service, download_file


def _list_files(service, folder_id: str, date: str, prefix: str) -> Iterable[dict]:
    """Yield Drive files in ``folder_id`` matching ``prefix`` and ``date``."""

    page_token = None
    query = (
        f"name contains '{prefix}' and name contains '{date}' "
        f"and '{folder_id}' in parents and mimeType='application/json'"
    )
    while True:
        resp = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name)",
            pageToken=page_token,
        ).execute()
        for item in resp.get("files", []):
            yield item
        page_token = resp.get("nextPageToken")
        if not page_token:
            break


def download_day(date: str, dest: Path, *, service=None) -> None:
    """Download snapshot and analysis JSON files for ``date`` into ``dest``."""

    srv = service or _build_service()
    folder_id = os.environ.get("DRIVE_FOLDER_ID")
    if not folder_id:
        raise EnvironmentError("DRIVE_FOLDER_ID is not set")
    dest.mkdir(parents=True, exist_ok=True)
    for prefix in ("snapshot_", "analysis"):
        for item in _list_files(srv, folder_id, date, prefix):
            download_file(item["id"], dest / item["name"], service=srv)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore snapshot and analysis files from Drive"
    )
    parser.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    parser.add_argument("--dest", required=True, help="Destination folder")
    args = parser.parse_args()
    download_day(args.date, Path(args.dest))


if __name__ == "__main__":
    main()
