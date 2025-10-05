#!/usr/bin/env python3
import argparse
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="Lint runner (safe)")
    ap.add_argument(
        "--fix", action="store_true", help="apply autofixes (ruff/isort/black)"
    )
    args = ap.parse_args()

    steps = []
    if args.fix:
        steps += [
            ["ruff", "check", "--select", "I", "--fix", "."],
            ["isort", "."],
            ["black", "."],
        ]
    steps += [["ruff", "check", "."]]

    for cmd in steps:
        print("$", " ".join(cmd), flush=True)
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            return proc.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
