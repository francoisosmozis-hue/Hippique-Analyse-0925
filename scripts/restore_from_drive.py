"""Restore archived snapshots and analyses from Google Cloud Storage."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterable

from scripts.drive_sync import _build_service, build_remote_path, download_file

BUCKET_ENV = "GCS_BUCKET"
PREFIX_ENV = "GCS_PREFIX

def _list_blobs(
    service, bucket: str, base_prefix: str, date: str, prefix: str
) -> Iterable[str]:
    """Yield object names under ``bucket`` whose filename matches ``prefix`` and ``date``."""

    search_prefix = build_remote_path(base_prefix, prefix)
    for blob in service.list_blobs(bucket, prefix=search_prefix):
        name = Path(blob.name).name
        if date in name and prefix in name:
            yield blob.name


def download_day(date: str, dest: Path, *, service=None) -> None:
    """Download snapshot and analysis JSON files for ``date`` into ``dest``."""

    srv = service or _build_service()
    bucket = os.environ.get(BUCKET_ENV)
    if not bucket:
        raise EnvironmentError(f"{BUCKET_ENV} is not set")
    base_prefix = os.environ.get(PREFIX_ENV, "")
    dest.mkdir(parents=True, exist_ok=True)
    for prefix in ("snapshot_", "analysis"):
        for object_name in _list_blobs(srv, bucket, base_prefix, date, prefix):
            target = dest / Path(object_name).name
            download_file(object_name, target, bucket=bucket, service=srv)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore snapshot and analysis files from Google Cloud Storage"
    )
    parser.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    parser.add_argument("--dest", required=True, help="Destination folder")
    args = parser.parse_args()
    download_day(args.date, Path(args.dest))


if __name__ == "__main__":
    main()
