"""Synchronise local files with Google Drive.

This module provides :func:`upload_file` and :func:`download_file` helpers
relying on ``google-api-python-client``.  Credentials are expected in the
``GOOGLE_CREDENTIALS_JSON`` environment variable (the full service account JSON)
and the target folder is read from ``DRIVE_FOLDER_ID``.

Example usage from the command line::

    export DRIVE_FOLDER_ID="<drive-folder-id>"
    export GOOGLE_CREDENTIALS_JSON="$(cat credentials.json)"
    python scripts/drive_sync.py --upload-glob "data/results/*.json"

The CLI accepts multiple ``--upload-glob`` patterns.  Files matching each
pattern are uploaded to the configured Drive folder.  ``--download FILE_ID
DEST`` pairs may be provided to retrieve files.
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
from pathlib import Path
from typing import Iterable, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _build_service(credentials_json: Optional[str] = None):
    """Return an authenticated Drive service using ``credentials_json``.

    Parameters
    ----------
    credentials_json:
        Service account credentials as a JSON string.  If omitted, the
        ``GOOGLE_CREDENTIALS_JSON`` environment variable is used.
    """

    info = credentials_json or os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not info:
        raise EnvironmentError("GOOGLE_CREDENTIALS_JSON is not set")
    data = json.loads(info)
    creds = service_account.Credentials.from_service_account_info(
        data, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def upload_file(
    path: str | Path,
    *,
    folder_id: Optional[str] = None,
    service=None,
) -> str:
    """Upload ``path`` to Drive and return the file id."""

    srv = service or _build_service()
    dest = folder_id or os.environ.get("DRIVE_FOLDER_ID")
    if not dest:
        raise EnvironmentError("DRIVE_FOLDER_ID is not set")
    file_metadata = {"name": Path(path).name, "parents": [dest]}
    media = MediaFileUpload(str(path), resumable=True)
    created = (
        srv.files().create(body=file_metadata, media_body=media, fields="id").execute()
    )
    return created.get("id")


def download_file(
    file_id: str,
    dest: str | Path,
    *,
    service=None,
) -> Path:
    """Download ``file_id`` from Drive into ``dest`` and return the path."""

    srv = service or _build_service()
    request = srv.files().get_media(fileId=file_id)
    fh = io.FileIO(dest, "wb")
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return Path(dest)


def _iter_uploads(patterns: Iterable[str]) -> Iterable[Path]:
    for pat in patterns:
        for match in glob.glob(pat, recursive=True):
            p = Path(match)
            if p.is_file():
                yield p


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload/download files to Drive")
    parser.add_argument("--folder-id", default=os.environ.get("DRIVE_FOLDER_ID"))
    parser.add_argument(
        "--credentials-json", default=os.environ.get("GOOGLE_CREDENTIALS_JSON")
    )
    parser.add_argument(
        "--upload-glob",
        action="append",
        default=[],
        help="Glob pattern of files to upload",
    )
    parser.add_argument(
        "--download",
        nargs=2,
        metavar=("FILE_ID", "DEST"),
        action="append",
        default=[],
        help="Download FILE_ID into DEST",
    )
    args = parser.parse_args()

    service = _build_service(args.credentials_json)

    for path in _iter_uploads(args.upload_glob):
        upload_file(path, folder_id=args.folder_id, service=service)

    for file_id, dest in args.download:
        download_file(file_id, dest, service=service)


if __name__ == "__main__":
    main()
