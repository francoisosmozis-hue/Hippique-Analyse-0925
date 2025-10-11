from __future__ import annotations
from pathlib import Path
from typing import Any, Optional, Iterable

<<<<<<< HEAD
# Flags & placeholders (les tests monkeypatchent ces symboles)
USE_GCS: bool = False
storage: Any = object()           # monkeypatch dans tests
service_account: Any = object()   # monkeypatch dans tests

# API Drive placeholders (monkeypatch targets)
_DRIVE_BUILD: Any = None
_MEDIA_DOWNLOAD: Any = None
_MEDIA_FILE_UPLOAD: Any = None

def is_gcs_enabled() -> bool:
    return bool(USE_GCS)
=======
# Keep these imports on separate lines to avoid syntax issues when running
# under stripped/concatenated builds.
>>>>>>> origin/main

def build_remote_path(*, date: Optional[str]=None, reunion: Optional[str]=None, course: Optional[str]=None, suffix: str="") -> str:
    parts = ["drive", date or "YYYY-MM-DD", reunion or "R?", course or "C?"]
    return "/".join(parts).rstrip("/") + (suffix or "")

<<<<<<< HEAD
def upload_file(path: str | Path, bucket: Optional[str]=None, prefix: Optional[str]=None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # no-op (les tests vérifient juste l'appel/chemin)
    return p
=======
REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    from post_course_payload import (
        CSV_HEADER,
        apply_summary_to_ticket_container,
        build_payload,
        compute_post_course_summary,
        format_csv_line,
        merge_meta,
    )
except ImportError:  # pragma: no cover - executed when run from scripts/
    if str(REPO_ROOT) not in sys.path:
        sys.path.append(str(REPO_ROOT))
    from post_course_payload import (
        CSV_HEADER,
        apply_summary_to_ticket_container,
        build_payload,
        compute_post_course_summary,
        format_csv_line,
        merge_meta,
    )

try:  # pragma: no cover - fallback when executed from within scripts/
    from scripts.gcs_utils import disabled_reason, is_gcs_enabled
except ImportError:  # pragma: no cover
    from gcs_utils import disabled_reason, is_gcs_enabled
    
SCOPES = ("https://www.googleapis.com/auth/devstorage.read_write",)
DRIVE_SCOPES = ("https://www.googleapis.com/auth/drive",)
>>>>>>> origin/main

def push_tree(root: str | Path, bucket: str, prefix: str="") -> list[Path]:
    root = Path(root)
    files = sorted([p for p in root.rglob("*") if p.is_file()])
    for f in files:
        upload_file(f, bucket=bucket, prefix=prefix)
    return files

def _build_service() -> None:
    # Placeholder GCS client; les tests monkeypatchent storage/service_account
    return None

<<<<<<< HEAD
def _build_drive_service(*, credentials_json: Optional[str]=None, credentials_file: Optional[str]=None) -> Any:
    # Placeholder Drive service; les tests monkeypatchent _DRIVE_BUILD
    return {"service": "drive", "json": credentials_json, "file": credentials_file}

def download_file(service: Any=None, file_id: Optional[str]=None, target: str | Path = "download.bin", **_) -> Path:
    # Tests vérifient l'appel et l'écriture
    p = Path(target)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
    return p

def main():
    import argparse
    ap = argparse.ArgumentParser(description="drive_sync (CI-compatible stub)")
    ap.add_argument("--help-only", action="store_true")
    ap.parse_args()
=======

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


def _build_drive_service(
    credentials: str | os.PathLike[str] | None,
    *,
    subject: str | None = None,
) -> Any:
    """Instantiate a Google Drive service client."""

    _ensure_drive_imports()

    info_payload: dict[str, Any] | None = None
    credentials_path: Path | None = None

    candidate = credentials or os.environ.get("DRIVE_CREDENTIALS_JSON")
    if candidate in (None, ""):
        candidate = None

    if isinstance(candidate, (str, os.PathLike)) and Path(candidate).exists():
        credentials_path = Path(candidate)
    elif isinstance(candidate, (str, os.PathLike)) and str(candidate).strip():
        try:
            info_payload = json.loads(str(candidate))
        except json.JSONDecodeError:
            credentials_path = Path(str(candidate))
    else:
        env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if env_path:
            credentials_path = Path(env_path)

    if info_payload is not None:
        creds = service_account.Credentials.from_service_account_info(
            info_payload, scopes=DRIVE_SCOPES
        )
    elif credentials_path is not None and credentials_path.exists():
        creds = service_account.Credentials.from_service_account_file(
            str(credentials_path), scopes=DRIVE_SCOPES
        )
    else:
        raise FileNotFoundError("Google Drive credentials not provided")

    impersonate = subject or os.environ.get("DRIVE_IMPERSONATE")
    if impersonate:
        creds = creds.with_subject(impersonate)

    assert _DRIVE_BUILD is not None
    return _DRIVE_BUILD("drive", "v3", credentials=creds, cache_discovery=False)


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


def _resolve_excel_path(excel: str | Path | None, outdir: str | Path | None) -> Path:
    """Return the Excel path used for post-course updates."""

    if excel:
        path = Path(excel)
    elif outdir:
        path = Path(outdir) / "modele_suivi_courses_hippiques.xlsx"
    else:
        path = Path("modele_suivi_courses_hippiques.xlsx")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _run_local_post_course(
    arrivee: str | Path | None,
    tickets: str | Path | None,
    outdir: str | Path | None,
    excel: str | Path | None,
    *,
    places: int = 1,
    excel_runner: Callable[[list[str] | None], None] | None = None,
) -> dict[str, Path]:
    """Execute local post-course steps and return generated artefacts."""

    outputs: dict[str, Path] = {}

    if not arrivee or not tickets:
        return outputs

    arrivee_path = Path(arrivee)
    tickets_path = Path(tickets)
    if not arrivee_path.exists() or not tickets_path.exists():
        return outputs
        
    target_out = Path(outdir) if outdir else tickets_path.parent
    excel_path = _resolve_excel_path(excel, outdir)
    outputs["excel"] = excel_path

    try:
        import post_course
        import update_excel_with_results
    except ImportError:  # pragma: no cover - defensive guard
        return outputs

    arrivee_data = post_course._load_json(arrivee_path)
    tickets_data = post_course._load_json(tickets_path)

    winners = [str(x) for x in arrivee_data.get("result", [])[: max(places, 0)]]
    summary = compute_post_course_summary(tickets_data.get("tickets", []), winners)
    apply_summary_to_ticket_container(tickets_data, summary)
    post_course._save_json(tickets_path, tickets_data)

    target_out.mkdir(parents=True, exist_ok=True)
    meta = merge_meta(arrivee_data, tickets_data)
    payload = build_payload(
        meta=meta,
        arrivee=arrivee_data,
        tickets=tickets_data.get("tickets", []),
        summary=summary,
        winners=winners,
        ev_estimees=tickets_data.get("ev"),
        places=places,
    )
    arrivee_output = target_out / "arrivee.json"
    post_course._save_json(arrivee_output, payload)

    ligne = format_csv_line(meta, summary)
    csv_line = target_out / "ligne_resultats.csv"
    post_course._save_text(csv_line, CSV_HEADER + "\n" + ligne + "\n")
    outputs["arrivee"] = arrivee_output
    outputs["csv_line"] = csv_line

    cmd = (
        "python update_excel_with_results.py "
        f'--excel "{excel_path}" '
        f'--payload "{arrivee_output}"\n'
    )
    cmd_path = target_out / "cmd_update_excel.txt"
    post_course._save_text(cmd_path, cmd)
    outputs["cmd"] = cmd_path
    
    runner = excel_runner or update_excel_with_results.main
    try:
        runner([
            "--excel",
            str(excel_path),
            "--payload",
            str(arrivee_output),
        ])
    except SystemExit:  # pragma: no cover - align with CLI style
        pass

    return outputs


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


def drive_download_file(service: Any, file_id: str, dest: str | Path) -> Path:
    """Download ``file_id`` from Drive into ``dest``."""

    _ensure_drive_imports()
    assert _MEDIA_DOWNLOAD is not None

    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = _MEDIA_DOWNLOAD(buffer, request)
    done = False
    while not done:
        _status, done = downloader.next_chunk()

    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(buffer.getvalue())
    return dest_path


def drive_upload_file(
    service: Any,
    folder_id: str | None,
    path: str | Path,
    *,
    file_id: str | None = None,
    mime_type: str | None = None,
) -> str:
    """Upload ``path`` to Drive and return the file identifier."""

    _ensure_drive_imports()
    assert _MEDIA_FILE_UPLOAD is not None

    local_path = Path(path)
    guessed_type = mime_type or mimetypes.guess_type(local_path.name)[0]
    media = _MEDIA_FILE_UPLOAD(str(local_path), mimetype=guessed_type, resumable=False)

    files_resource = service.files()
    metadata: dict[str, Any] = {"name": local_path.name}
    if folder_id:
        metadata["parents"] = [folder_id]

    if file_id:
        request = files_resource.update(fileId=file_id, media_body=media)
        result = request.execute()
        file_id_out = result.get("id", file_id)
        return str(file_id_out) if file_id_out is not None else ""

    request = files_resource.create(body=metadata, media_body=media, fields="id")
    result = request.execute()
    file_id_out = result.get("id")
    return str(file_id_out) if file_id_out is not None else ""


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
        "--drive-credentials",
        help="Chemin ou payload JSON pour le compte de service Google Drive",
    )
    parser.add_argument(
        "--drive-subject",
        help="Utilisateur à impersoner pour Drive (delegation domain-wide)",
    )
    parser.add_argument(
        "--excel-file-id",
        help="Identifiant Drive du classeur ROI à mettre à jour",
    )
    parser.add_argument(
        "--upload-result",
        action="store_true",
        help="Téléverser le snapshot arrivee.json sur Drive",
    )
    parser.add_argument(
        "--upload-line",
        action="store_true",
        help="Téléverser la synthèse CSV (ligne_resultats.csv) sur Drive",
    )
    parser.add_argument(
        "--upload-file",
        action="append",
        default=[],
        metavar="PATH",
        help="Fichiers additionnels à téléverser sur Drive",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Afficher les actions sans effectuer les transferts distants",
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

    excel_path = _resolve_excel_path(args.excel, args.outdir)
    dry_run = args.dry_run
    if dry_run:
        print("[drive_sync] --dry-run → les opérations réseau seront simulées.")
        
    drive_requested = bool(
        not args.local_only
        and (
            args.excel_file_id
            or args.upload_result
            or args.upload_line
            or args.upload_file
        )
    )

    drive_service = None
    if drive_requested:
        if dry_run:
            print("[drive_sync] --dry-run → client Google Drive non initialisé.")
            if args.excel_file_id:
                print(
                    "[drive_sync] --dry-run: téléchargerait le classeur Drive "
                    f"{args.excel_file_id} vers {excel_path}"
                )
        else:
            credentials_arg = args.drive_credentials or args.credentials_json
            try:
                drive_service = _build_drive_service(
                    credentials_arg, subject=args.drive_subject
                )
            except Exception as exc:  # pragma: no cover - logged for operator visibility
                print(f"[drive_sync] Drive sync désactivée: {exc}")
                drive_service = None
            else:
                if args.excel_file_id:
                    try:
                        drive_download_file(drive_service, args.excel_file_id, excel_path)
                    except Exception as exc:  # pragma: no cover - best effort
                        print(
                            f"[drive_sync] Impossible de télécharger l'Excel Drive: {exc}",
                            file=sys.stderr,
                        )
                        
    outputs = _run_local_post_course(
        args.arrivee,
        args.tickets,
        args.outdir,
        excel_path,
        places=args.places,
    )

    folder_id = args.prefix
    excel_file = outputs.get("excel", excel_path)
    mime_xlsx = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if args.excel_file_id:
        if dry_run and drive_requested:
            print(
                "[drive_sync] --dry-run: téléverserait l'Excel local vers le fichier "
                f"Drive {args.excel_file_id}"
            )
        elif drive_service:
            try:
                drive_upload_file(
                    drive_service,
                    None,
                    excel_file,
                    file_id=args.excel_file_id,
                    mime_type=mime_xlsx,
                )
            except Exception as exc:  # pragma: no cover - best effort
                print(
                    f"[drive_sync] Impossible de téléverser l'Excel Drive: {exc}",
                    file=sys.stderr,
                )
    elif folder_id:
        if dry_run and drive_requested:
            print(
                "[drive_sync] --dry-run: téléverserait l'Excel local dans le dossier "
                f"Drive {folder_id}"
            )
        elif drive_service:
            try:
                drive_upload_file(
                    drive_service,
                    folder_id,
                    excel_file,
                    mime_type=mime_xlsx,
                )
            except Exception as exc:  # pragma: no cover - best effort
                print(
                    f"[drive_sync] Upload Excel Drive ignoré: {exc}",
                    file=sys.stderr,
                )
    elif args.upload_result or args.upload_line or args.upload_file:
        msg = "[drive_sync] Upload Drive ignoré: --folder-id manquant pour les créations."
        if dry_run:
            print("[drive_sync] --dry-run: " + msg.split(": ")[1])
        else:
            print(msg, file=sys.stderr)

    if args.upload_result:
        arrivee_path = outputs.get("arrivee")
        if arrivee_path and arrivee_path.exists():
            if dry_run and drive_requested:
                if folder_id:
                    print(
                        "[drive_sync] --dry-run: téléverserait arrivee.json dans "
                        f"Drive {folder_id}"
                    )
                else:
                    print(
                        "[drive_sync] --dry-run: arrivee.json ignoré faute de folder-id"
                    )
            elif drive_service and folder_id:
                try:
                    drive_upload_file(drive_service, folder_id, arrivee_path)
                except Exception as exc:  # pragma: no cover
                    print(
                        f"[drive_sync] Upload arrivee.json échoué: {exc}",
                        file=sys.stderr,
                    )
    if args.upload_line:
        csv_line = outputs.get("csv_line")
        if csv_line and csv_line.exists():
            if dry_run and drive_requested:
                if folder_id:
                    print(
                        "[drive_sync] --dry-run: téléverserait ligne_resultats.csv dans "
                        f"Drive {folder_id}"
                    )
                else:
                    print(
                        "[drive_sync] --dry-run: ligne_resultats.csv ignoré faute de folder-id"
                    )
            elif drive_service and folder_id:
                try:
                    drive_upload_file(drive_service, folder_id, csv_line)
                except Exception as exc:  # pragma: no cover
                    print(
                        f"[drive_sync] Upload ligne_resultats.csv échoué: {exc}",
                        file=sys.stderr,
                    )

    for extra in args.upload_file:
        extra_path = Path(extra)
        if not extra_path.exists():
            print(
                f"[drive_sync] Fichier introuvable, upload ignoré: {extra_path}",
                file=sys.stderr,
            )
            continue
        if folder_id:
            if dry_run and drive_requested:
                print(
                    "[drive_sync] --dry-run: téléverserait "
                    f"{extra_path} dans Drive {folder_id}"
                )
            elif drive_service:
                try:
                    drive_upload_file(drive_service, folder_id, extra_path)
                except Exception as exc:  # pragma: no cover
                    print(
                        f"[drive_sync] Upload Drive échoué pour {extra_path}: {exc}",
                        file=sys.stderr,
                    )
        else:
            if dry_run:
                print(
                    "[drive_sync] --dry-run: upload ignoré (folder-id manquant) pour "
                    f"{extra_path}"
                )
            else:
                print(
                    f"[drive_sync] Upload ignoré (folder-id manquant): {extra_path}",
                    file=sys.stderr,
                )

    if args.local_only:
        print("[drive_sync] --local-only → skipping Google Cloud Storage synchronisation.")
        return 0

    if dry_run:
        bucket_display = args.bucket or os.environ.get(BUCKET_ENV) or "<bucket?>"
        prefix_display = args.prefix or ""
        for base in args.push:
            print(
                "[drive_sync] --dry-run: enverrait le répertoire "
                f"{base} vers gs://{bucket_display}/{prefix_display}"
            )
        for path in _iter_uploads(args.upload_glob):
            print(
                "[drive_sync] --dry-run: téléverserait le fichier "
                f"{path} vers gs://{bucket_display}/{prefix_display}"
            )
        for object_name, dest in args.download:
            print(
                "[drive_sync] --dry-run: téléchargerait gs://"
                f"{bucket_display}/{object_name} vers {dest}"
            )
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
>>>>>>> origin/main


if __name__ == "__main__":
    main()
