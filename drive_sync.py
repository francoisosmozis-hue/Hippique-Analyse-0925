
from pathlib import Path
import io
import json
import argparse
import subprocess
from typing import Optional, List

# Lazy imports for Google libs to allow the file to be imported without them
def _lazy_google_imports():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
    return Credentials, build, MediaIoBaseDownload, MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]


def build_drive_service(credentials_path: Path):
    Credentials, build, _, _ = _lazy_google_imports()
    creds = Credentials.from_service_account_file(str(credentials_path), scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def get_file_by_name_in_folder(drive, folder_id: str, name: str) -> Optional[dict]:
    # Avoid backslashes in f-strings by formatting separately
    safe_name = name.replace("'", "\\'")
    q = " and ".join([
        f"'{folder_id}' in parents",
        "trashed = false",
        f"name = '{safe_name}'",
    ])
    res = drive.files().list(q=q, spaces="drive",
                             fields="files(id, name, mimeType, modifiedTime, size)").execute()
    files = res.get("files", [])
    return files[0] if files else None


def list_files_in_folder(drive, folder_id: str) -> List[dict]:
    q = f"'{folder_id}' in parents and trashed = false"
    files = []
    page_token = None
    while True:
        res = drive.files().list(q=q, spaces="drive",
                                 fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
                                 pageToken=page_token).execute()
        files.extend(res.get("files", []))
        page_token = res.get("nextPageToken")
        if not page_token:
            break
    return files


def download_file(drive, file_id: str, out_path: Path):
    from googleapiclient.http import MediaIoBaseDownload
    request = drive.files().get_media(fileId=file_id)
    fh = io.FileIO(out_path, "wb")
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.close()


def upload_new_version_or_create(drive, folder_id: str, local_path: Path, mime_type: str) -> str:
    from googleapiclient.http import MediaFileUpload
    existing = get_file_by_name_in_folder(drive, folder_id, local_path.name)
    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)

    if existing:
        file_id = existing["id"]
        drive.files().update(fileId=file_id, media_body=media).execute()
        return file_id
    else:
        file_metadata = {"name": local_path.name, "parents": [folder_id]}
        new_file = drive.files().create(body=file_metadata, media_body=media, fields="id").execute()
        return new_file["id"]


def guess_mime(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in [".xlsx", ".xlsm", ".xls"]:
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if ext == ".csv":
        return "text/csv"
    if ext == ".json":
        return "application/json"
    if ext == ".txt":
        return "text/plain"
    return "application/octet-stream"


def run_update_excel(excel_path: Path, result_json: Path,
                     tickets: str, mises: float, gains: float,
                     roi_estime: Optional[float], verdict: str, notes: str) -> None:
    cmd = [
        "python", "update_excel_with_results.py",
        "--excel", str(excel_path),
        "--result", str(result_json),
        "--tickets", tickets,
        "--mises", str(mises),
        "--gains", str(gains),
        "--verdict", verdict,
        "--notes", notes,
    ]
    if roi_estime is not None:
        cmd.extend(["--roi_estime", str(roi_estime)])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"update_excel_with_results.py failed:\\n{proc.stderr}\\n{proc.stdout}")
    print(proc.stdout)


def main():
    ap = argparse.ArgumentParser(description="Drive sync helper (download Excel, update, upload new version).")
    ap.add_argument("--folder-id", required=True, help="Google Drive folder ID (target 'analyse hippique').")
    ap.add_argument("--credentials", default="credentials.json", help="Path to service account credentials.json")
    ap.add_argument("--excel", default="modele_suivi_courses_hippiques.xlsx",
                    help="Excel filename to download/update/upload.")
    ap.add_argument("--result", required=True, help="Arrival JSON produced by get_arrivee_geny.py")
    ap.add_argument("--tickets", required=True, help="Tickets text (e.g. 'SP 3€ ; CP 2€')")
    ap.add_argument("--mises", type=float, required=True, help="Total stakes in €")
    ap.add_argument("--gains", type=float, required=True, help="Total gains in €")
    ap.add_argument("--roi-estime", type=float, default=None, help="Estimated ROI (e.g. 0.5 for +50%)")
    ap.add_argument("--verdict", default="", help="Verdict (e.g. 'Valide jeu réel' / 'Abstention')")
    ap.add_argument("--notes", default="", help="Free notes")
    ap.add_argument("--upload-result", action="store_true", help="Also upload the JSON result file to Drive")
    ap.add_argument("--csv-line", default=None, help="Optional single CSV line to write & upload as 'arrivee_line.csv'")
    args = ap.parse_args()

    workdir = Path(".")
    credentials_path = workdir / args.credentials
    result_json = workdir / args.result
    excel_path = workdir / args.excel

    # Build Drive client
    drive = build_drive_service(credentials_path)

    # 1) Try to download latest Excel if it exists
    existing = get_file_by_name_in_folder(drive, args.folder_id, excel_path.name)
    if existing:
        print(f"Downloading existing Excel from Drive: {existing['name']} ({existing['id']})")
        download_file(drive, existing["id"], excel_path)
    else:
        print("No existing Excel found on Drive; a new file will be created locally.")

    # 2) Update Excel using the local result JSON
    run_update_excel(excel_path, result_json, args.tickets, args.mises, args.gains, args.roi_estime, args.verdict, args.notes)

    # 3) Upload updated Excel as new version (or create)
    excel_mime = guess_mime(excel_path)
    excel_id = upload_new_version_or_create(drive, args.folder_id, excel_path, excel_mime)
    print(f"Uploaded Excel → fileId={excel_id}")

    # 4) Optionally upload the result JSON
    if args.upload_result:
        json_mime = guess_mime(result_json)
        json_id = upload_new_version_or_create(drive, args.folder_id, result_json, json_mime)
        print(f"Uploaded JSON result → fileId={json_id}")

    # 5) Optionally write & upload a one-line CSV snapshot
    if args.csv_line:
        csv_path = workdir / "arrivee_line.csv"
        if not args.csv_line.endswith("\\n"):
            args.csv_line += "\\n"
        csv_path.write_text(args.csv_line, encoding="utf-8")
        csv_mime = guess_mime(csv_path)
        csv_id = upload_new_version_or_create(drive, args.folder_id, csv_path, csv_mime)
        print(f"Uploaded CSV snapshot → fileId={csv_id}")


if __name__ == "__main__":
    main()
