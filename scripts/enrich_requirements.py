#!/usr/bin/env python3
"""Utilities for keeping ``requirements.txt`` enriched with expected packages."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"

# Packages that were previously appended to ``requirements.txt`` via inline shell.
EXTRA_DEPENDENCIES = (
    "fastapi",
    "uvicorn[standard]",
    "python-dotenv",
    "requests",
    "pandas",
    "openpyxl",
    "PyYAML",
    "google-cloud-secret-manager",
    "google-auth",
    "google-cloud-storage",
)


def _normalise_requirement(line: str) -> str | None:
    """Return the canonical package name from a requirement line.

    Comments and empty lines are ignored and return ``None``.
    """

    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    return re.split(r"[<>=!~]", stripped, maxsplit=1)[0].strip()


def _load_existing(path: Path) -> set[str]:
    existing: set[str] = set()
    for raw_line in path.read_text().splitlines():
        name = _normalise_requirement(raw_line)
        if name:
            existing.add(name)
    return existing


def enrich_requirements(
    path: Path, extras: Iterable[str], *, dry_run: bool = False
) -> bool:
    """Ensure ``path`` contains the packages from ``extras``.

    Returns ``True`` when the file would be modified.
    """

    existing_packages = _load_existing(path)
    missing = [pkg for pkg in extras if pkg not in existing_packages]

    if not missing:
        return False

    if dry_run:
        print("Missing packages:")
        for pkg in missing:
            print(f"  - {pkg}")
        return True

    lines = path.read_text().splitlines()
    if lines and lines[-1].strip():
        lines.append("")
    lines.extend(missing)
    path.write_text("\n".join(lines) + "\n")
    print("Added packages:")
    for pkg in missing:
        print(f"  - {pkg}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--requirements",
        type=Path,
        default=DEFAULT_REQUIREMENTS_PATH,
        help="Path to the requirements file to update (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report missing packages without modifying the file.",
    )
    args = parser.parse_args()

    changed = enrich_requirements(
        args.requirements, EXTRA_DEPENDENCIES, dry_run=args.dry_run
    )
    if not changed:
        print("Requirements are already enriched.")


if __name__ == "__main__":
    main()
