"""Convenience wrapper delegating to :mod:`scripts.drive_sync`.

This module allows running ``python drive_sync.py`` from the repository root
while keeping the fully-featured implementation under ``scripts/``.
"""

from __future__ import annotations

import sys

from scripts.drive_sync import main as _scripts_drive_sync_main


def main() -> int:
    """Entry point delegating to :func:`scripts.drive_sync.main`."""

    result = _scripts_drive_sync_main()
    if result is None:
        return 0
    return int(result)


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
