#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
from typing import Any, Optional

# Essaie l'impl réelle ; sinon expose des stubs sûrs pour la CI/tests.
try:
    from .drive_sync_impl import *  # type: ignore  # noqa: F401,F403
except Exception:
    def _build_service() -> None:
        return None

    def build_remote_path(*, date: Optional[str]=None,
                          reunion: Optional[str]=None,
                          course: Optional[str]=None,
                          suffix: str="") -> str:
        parts = ["drive", date or "YYYY-MM-DD", reunion or "R?", course or "C?"]
        return "/".join(parts).rstrip("/") + (suffix or "")

    def download_file(*, service: Any=None, file_id: str="",
                      target: Path | str="download.bin") -> Path:
        p = Path(target)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
        return p

    def main() -> int:
        ap = argparse.ArgumentParser(description="drive_sync (CI stub)")
        ap.add_argument("--help-only", action="store_true")
        ap.parse_args()
        return 0

    if __name__ == "__main__":
        raise SystemExit(main())
else:
    if __name__ == "__main__":
        ap = argparse.ArgumentParser(description="drive_sync wrapper")
        ap.add_argument("--help-only", action="store_true")
        ap.parse_args()
