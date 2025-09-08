import argparse
import hashlib
import logging
import time
from pathlib import Path
from typing import Iterable

import requests


def md5sum(path: Path) -> str:
    """Compute MD5 checksum of a file."""
    h = hashlib.md5()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_file(url: str, path: Path, retries: int = 5, backoff: float = 1.0) -> bool:
    """Upload a file to ``url`` using exponential backoff on network errors."""
    for attempt in range(retries):
        try:
            with path.open('rb') as fh:
                response = requests.post(url, files={"file": fh})
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            logging.warning("Upload failed for %s (attempt %s/%s): %s", path, attempt + 1, retries, exc)
            if attempt + 1 == retries:
                return False
            time.sleep(backoff)
            backoff *= 2
    return False


def sync(url: str, files: Iterable[Path]) -> None:
    """Upload multiple files and log checksum and total count."""
    files = list(files)
    uploaded = 0
    for file_path in files:
        if upload_file(url, file_path):
            uploaded += 1
            logging.info("Uploaded %s checksum=%s", file_path, md5sum(file_path))
        else:
            logging.error("Failed to upload %s", file_path)
    logging.info("%s/%s files uploaded", uploaded, len(files))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync files to remote drive")
    parser.add_argument("--url", required=True, help="Upload endpoint")
    parser.add_argument("files", nargs="+", help="Files to upload")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")

    file_paths = [Path(f) for f in args.files]
    sync(args.url, file_paths)


if __name__ == "__main__":
    main()
