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
from typing import Callable, Iterable, Optional

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


def _run_local_post_course(
    arrivee: str | Path | None,
    tickets: str | Path | None,
    outdir: str | Path | None,
    excel: str | Path | None,
    *,
    places: int = 1,
    excel_runner: Callable[[list[str] | None], None] | None = None,
) -> None:
    """Execute local post-course steps when arrival/tickets payloads exist."""

    if not arrivee or not tickets:
        return

    arrivee_path = Path(arrivee)
    tickets_path = Path(tickets)
    if not arrivee_path.exists() or not tickets_path.exists():
        return

    target_out = Path(outdir) if outdir else tickets_path.parent
    excel_path = Path(excel) if excel else Path("modele_suivi_courses_hippiques.xlsx")

    try:
        import post_course
        import update_excel_with_results
    except ImportError:  # pragma: no cover - defensive guard
        return

    arrivee_data = post_course._load_json(arrivee_path)
    tickets_data = post_course._load_json(tickets_path)

    winners = [str(x) for x in arrivee_data.get("result", [])[: max(places, 0)]]
    (
        total_gain,
        total_stake,
        roi,
        ev_total,
        diff_ev_total,
        result_moyen,
        roi_reel_moyen,
        brier_total,
        brier_moyen,
    ) = post_course._compute_gains(tickets_data.get("tickets", []), winners)

    tickets_data["roi_reel"] = roi
    tickets_data["result_moyen"] = result_moyen
    tickets_data["roi_reel_moyen"] = roi_reel_moyen
    tickets_data["brier_total"] = brier_total
    tickets_data["brier_moyen"] = brier_moyen
    post_course._save_json(tickets_path, tickets_data)

    target_out.mkdir(parents=True, exist_ok=True)
    meta = tickets_data.get("meta", {}) if isinstance(tickets_data, dict) else {}
    arrivee_out = {
        "rc": arrivee_data.get("rc") or meta.get("rc"),
        "date": arrivee_data.get("date") or meta.get("date"),
        "result": winners,
        "gains": total_gain,
        "roi_reel": roi,
        "result_moyen": result_moyen,
        "roi_reel_moyen": roi_reel_moyen,
        "brier_total": brier_total,
        "brier_moyen": brier_moyen,
        "ev_total": ev_total,
        "ev_ecart_total": diff_ev_total,
    }
    arrivee_output = target_out / "arrivee.json"
    post_course._save_json(arrivee_output, arrivee_out)

    ligne = (
        f'{meta.get("rc", "")};{meta.get("hippodrome", "")};{meta.get("date", "")};'
        f'{meta.get("discipline", "")};{total_stake:.2f};{roi:.4f};'
        f'{result_moyen:.4f};{roi_reel_moyen:.4f};'
        f'{brier_total:.4f};{brier_moyen:.4f};'
        f'{ev_total:.2f};{diff_ev_total:.2f};'
        f'{meta.get("model", meta.get("MODEL", ""))}'
    )
    header = (
        "R/C;hippodrome;date;discipline;mises;ROI_reel;result_moyen;"
        "ROI_reel_moyen;Brier_total;Brier_moyen;EV_total;EV_ecart;model\n"
    )
    post_course._save_text(target_out / "ligne_resultats.csv", header + ligne + "\n")

    cmd = (
        "python update_excel_with_results.py "
        f'--excel "{excel_path}" '
        f'--arrivee "{arrivee_output}" '
        f'--tickets "{tickets_path}"\n'
    )
    post_course._save_text(target_out / "cmd_update_excel.txt", cmd)

    runner = excel_runner or update_excel_with_results.main
    try:
        runner(
            [
                "--excel",
                str(excel_path),
                "--arrivee",
                str(arrivee_output),
                "--tickets",
                str(tickets_path),
            ]
        )
    except SystemExit:  # pragma: no cover - align with CLI style
        pass


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
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="N'exécuter que les actions locales (aucun appel GCS)",
    )
    parser.add_argument("--arrivee", help="Arrivée officielle pour la mise à jour post-course")
    parser.add_argument(
        "--tickets",
        help="Tickets JSON à enrichir avec le ROI observé",
    )
    parser.add_argument(
        "--outdir",
        help="Répertoire pour stocker les artefacts post-course",
    )
    parser.add_argument(
        "--excel",
        help="Classeur Excel à mettre à jour avec les résultats",
    )
    parser.add_argument(
        "--places",
        type=int,
        default=1,
        help="Nombre de positions rémunérées à considérer pour le ROI",
    )
    args = parser.parse_args()

    _run_local_post_course(
        args.arrivee,
        args.tickets,
        args.outdir,
        args.excel,
        places=args.places,
    )

    if args.local_only:
        print("[drive_sync] --local-only → skipping Google Cloud Storage synchronisation.")
        return 0

    if not is_gcs_enabled():
        reason = disabled_reason() or "USE_GCS"
        print(
            f"[drive_sync] {reason}=false → skipping Google Cloud Storage synchronisation."
        )
        return 0

    try:
        bucket_name = _require_bucket(args.bucket)
    except EnvironmentError as exc:
        print(f"[drive_sync] ROI non historisé (Drive off): {exc}")
        return 0
        
    try:
        client = _build_service(args.credentials_json, project=args.project)
    except google_auth_exceptions.DefaultCredentialsError:
        print("[drive_sync] ROI non historisé (Drive off)")
        return 0

    for base in args.push:
        push_tree(base, folder_id=args.prefix, bucket=bucket_name, service=client)

    for path in _iter_uploads(args.upload_glob):
        upload_file(path, folder_id=args.prefix, bucket=bucket_name, service=client)

    for object_name, dest in args.download:
        download_file(object_name, dest, bucket=bucket_name, service=client)

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
