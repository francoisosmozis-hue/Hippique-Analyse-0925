"""Synchronise local files with Google Cloud Storage.

This module exposes :func:`upload_file`, :func:`download_file` and
:func:`push_tree` helpers built on top of ``google-cloud-storage``.  The
previous Google Drive implementation has been replaced by a simpler Google
Cloud Storage client that relies on the following environment variables:

``GCS_BUCKET``
    Name of the destination bucket.
``GCS_PREFIX`` (optional)
    Common prefix applied to every uploaded object.
``GOOGLE_CLOUD_PROJECT`` (optional)
    Project used to instantiate the storage client.
``GCS_SERVICE_KEY_B64`` / ``GCS_SERVICE_KEY_JSON`` (optional)
    Service account credentials, either as base64 or raw JSON string.  When
    omitted, the default credentials chain is used.
``USE_GCS`` (optional)
    Controls whether uploads are enabled.  Defaults to ``true``.  For
    backwards compatibility ``USE_DRIVE=false`` still disables the sync.

Example usage from the command line::

    export GCS_BUCKET="<bucket-name>"
    export GCS_SERVICE_KEY_B64="$(base64 -w0 credentials.json)"
    python scripts/drive_sync.py --upload-glob "data/results/*.json"

The CLI accepts multiple ``--upload-glob`` patterns.  Files matching each
pattern are uploaded to the configured bucket under the configured prefix.
``--download OBJECT DEST`` pairs may be provided to retrieve specific objects,
while ``--push DIR`` recursively uploads an entire directory tree.
"""

from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Optional

# Keep these imports on separate lines to avoid syntax issues when running
# under stripped/concatenated builds.

import google.auth.exceptions as google_auth_exceptions
from google.cloud import storage
from google.oauth2 import service_account

try:  # pragma: no cover - fallback when executed from within scripts/
    from scripts.gcs_utils import disabled_reason, is_gcs_enabled
except ImportError:  # pragma: no cover
    from gcs_utils import disabled_reason, is_gcs_enabled
    
SCOPES = ("https://www.googleapis.com/auth/devstorage.read_write",)
BUCKET_ENV = "GCS_BUCKET"
PREFIX_ENV = "GCS_PREFIX"
PROJECT_ENV = "GOOGLE_CLOUD_PROJECT"
SERVICE_KEY_JSON_ENV = "GCS_SERVICE_KEY_JSON"
SERVICE_KEY_B64_ENV = "GCS_SERVICE_KEY_B64"


def _load_credentials(credentials_json: Optional[str] = None):
    """Return service account credentials when available.

    ``credentials_json`` may contain the raw JSON payload.  When omitted, the
    helper falls back to ``GCS_SERVICE_KEY_JSON`` then
    ``GCS_SERVICE_KEY_B64`` (base64-encoded JSON).  As a last resort the
    ``GOOGLE_APPLICATION_CREDENTIALS`` file is considered.  ``None`` is
    returned if no credentials are provided so the default client logic can
    apply (ADC, workload identity, …).
    """

    info = credentials_json or os.environ.get(SERVICE_KEY_JSON_ENV)
    if not info:
        encoded = os.environ.get(SERVICE_KEY_B64_ENV)
        if encoded:
            info = base64.b64decode(encoded).decode()
    if info:
        data = json.loads(info)
        return service_account.Credentials.from_service_account_info(
            data, scopes=SCOPES
        )
    key_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if key_path:
        return service_account.Credentials.from_service_account_file(
            key_path, scopes=SCOPES
        )
    return None


def _build_service(
    credentials_json: Optional[str] = None, *, project: Optional[str] = None
) -> storage.Client:
    """Instantiate and return a ``storage.Client``."""

    creds = _load_credentials(credentials_json)
    project_id = project if project not in (None, "") else os.environ.get(PROJECT_ENV)
    if project_id == "":
        project_id = None
    if creds is None:
        return storage.Client(project=project_id)
    return storage.Client(project=project_id, credentials=creds)


def _remote_path(*parts: str | os.PathLike[str] | None) -> str:
    """Join ``parts`` using ``/`` while stripping empty segments."""

    cleaned: list[str] = []
    for part in parts:
        if part is None:
            continue
        text = str(part).strip("/")
        if text:
            cleaned.append(text.replace("\\", "/"))
    return "/".join(cleaned)


def build_remote_path(*parts: str | os.PathLike[str] | None) -> str:
    """Public helper exposing :func:`_remote_path` for reuse in other modules."""

    return _remote_path(*parts)


def _iter_uploads(patterns: Iterable[str]) -> Iterable[Path]:
    for pat in patterns:
        for match in glob.glob(pat, recursive=True):
            p = Path(match)
            if p.is_file():
                yield p


def _require_bucket(bucket: Optional[str] = None) -> str:
    name = bucket or os.environ.get(BUCKET_ENV)
    if not name:
        raise EnvironmentError(f"{BUCKET_ENV} is not set")
    return name
    

def upload_file(
    path: str | Path,
    *,
    folder_id: Optional[str] = None,
    bucket: Optional[str] = None,
    service: storage.Client | None = None,
) -> str:
    """Upload ``path`` to the configured bucket and return the object name."""

    client = service or _build_service()
    bucket_name = _require_bucket(bucket)
    prefix = folder_id or os.environ.get(PREFIX_ENV)
    blob_name = _remote_path(prefix, Path(path).name)
    if not blob_name:
        blob_name = Path(path).name
    blob = client.bucket(bucket_name).blob(blob_name)
    blob.upload_from_filename(str(path))
    return blob.name


def download_file(
    object_name: str,
    dest: str | Path,
    *,
    bucket: Optional[str] = None,
    service: storage.Client | None = None,
) -> Path:
    """Download ``object_name`` from the bucket into ``dest`` and return the path."""

    client = service or _build_service()
    bucket_name = _require_bucket(bucket)
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    blob = client.bucket(bucket_name).blob(object_name)
    blob.download_to_filename(str(dest_path))
    return dest_path


def push_tree(
    base: str | Path,
    *,
    folder_id: Optional[str] = None,
    bucket: Optional[str] = None,
    service: storage.Client | None = None,
) -> None:
    """Recursively upload ``base`` into ``folder_id`` (treated as prefix)."""

    client = service or _build_service()
    bucket_name = _require_bucket(bucket)
    prefix = folder_id or os.environ.get(PREFIX_ENV)
    root = Path(base)
    bucket_obj = client.bucket(bucket_name)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        blob_name = _remote_path(prefix, rel)
        blob = bucket_obj.blob(blob_name)
        blob.upload_from_filename(str(path))


def main() -> int | None:
    if not is_gcs_enabled():
        reason = disabled_reason() or "USE_GCS"
        print(
            f"[drive_sync] {reason}=false → skipping Google Cloud Storage synchronisation."
        )
        return 0

    parser = argparse.ArgumentParser(
        description="Upload/download files to Google Cloud Storage"
    )
    parser.add_argument("--bucket", default=os.environ.get(BUCKET_ENV))
    parser.add_argument("--project", default=os.environ.get(PROJECT_ENV))
    parser.add_argument("--prefix")
    parser.add_argument(
        "--folder-id",
        dest="prefix",
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    parser.set_defaults(prefix=os.environ.get(PREFIX_ENV))
    parser.add_argument(
        "--credentials-json",
        help="Service account credentials JSON string (defaults to GCS_SERVICE_KEY_* env vars)",
    )
    parser.add_argument(
        "--upload-glob",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Glob pattern of files to upload (may be repeated)",
    )
    parser.add_argument(
        "--download",
        nargs=2,
        metavar=("OBJECT", "DEST"),
        action="append",
        default=[],
        help="Download OBJECT into DEST",
    )
    parser.add_argument(
        "--push",
        action="append",
        default=[],
        help="Répertoire à envoyer sur GCS",
    )
    args = parser.parse_args()

    try:
        client = _build_service(args.credentials_json, project=args.project)
    except google_auth_exceptions.DefaultCredentialsError:
        print(
            "[drive_sync] no Google Cloud credentials detected → skipping Google Cloud Storage synchronisation."
        )
        return 0

    for base in args.push:
        push_tree(base, folder_id=args.prefix, bucket=args.bucket, service=client)

    for path in _iter_uploads(args.upload_glob):
        upload_file(path, folder_id=args.prefix, bucket=args.bucket, service=client)

    for object_name, dest in args.download:
        download_file(object_name, dest, bucket=args.bucket, service=client)

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
