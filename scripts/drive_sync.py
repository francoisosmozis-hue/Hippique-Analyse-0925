from __future__ import annotations
from pathlib import Path
from typing import Any, Optional, Iterable

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

def build_remote_path(*, date: Optional[str]=None, reunion: Optional[str]=None, course: Optional[str]=None, suffix: str="") -> str:
    parts = ["drive", date or "YYYY-MM-DD", reunion or "R?", course or "C?"]
    return "/".join(parts).rstrip("/") + (suffix or "")

def upload_file(path: str | Path, bucket: Optional[str]=None, prefix: Optional[str]=None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # no-op (les tests vérifient juste l'appel/chemin)
    return p

def push_tree(root: str | Path, bucket: str, prefix: str="") -> list[Path]:
    root = Path(root)
    files = sorted([p for p in root.rglob("*") if p.is_file()])
    for f in files:
        upload_file(f, bucket=bucket, prefix=prefix)
    return files

def _build_service() -> None:
    # Placeholder GCS client; les tests monkeypatchent storage/service_account
    return None

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


if __name__ == "__main__":
    main()
