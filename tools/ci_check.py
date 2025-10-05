#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SKIP_DIRS = {
    ".venv",
    ".git",
    ".github",
    "data",
    "dist",
    "build",
    "excel",
    "out",
    "cache",
    "__pycache__",
    "Hippique-Analyse-0925","tests","scripts/tests",
}
DEFAULT_TIMEOUT = 5


def iter_py_files(root: Path):
    for p in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        name = p.name
        if name.endswith("_impl.py") or name.endswith(".disabled"):
            continue
        yield p


def has_argparse(p: Path) -> bool:
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    return ("argparse.ArgumentParser(" in txt) or (
        "from argparse import ArgumentParser" in txt
    )


def run_help(p: Path, timeout: int) -> tuple[int, str, str]:
    env = os.environ.copy()
    env.update({"CI": "1", "DRY_RUN": "1", "OFFLINE": "1", "NO_NET": "1"})
    cmd = [sys.executable, str(p), "--help"]
    try:
        proc = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=timeout
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"Timeout ({timeout}s)"
    except Exception as e:
        return 1, "", f"Exception: {e}"


def try_import(p: Path, timeout: int) -> tuple[int, str]:
    env = os.environ.copy()
    env.update({"CI": "1", "DRY_RUN": "1", "OFFLINE": "1", "NO_NET": "1"})
    code = f"""
import importlib.util, sys
spec=importlib.util.spec_from_file_location("ci_module","{p.as_posix()}")
m=importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
    sys.exit(0)
except SystemExit as e:
    sys.exit(int(getattr(e,'code',0) or 0))
except Exception as e:
    print("IMPORT_ERROR:",repr(e))
    sys.exit(1)
"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout + proc.stderr)
    except subprocess.TimeoutExpired:
        return 124, f"Timeout ({timeout}s)"


def main():
    ap = argparse.ArgumentParser(
        description="CI checks without running business logic."
    )
    ap.add_argument("--mode", choices=["helpcheck", "importcheck"], required=True)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = ap.parse_args()

    root = Path(".").resolve()
    failures = []
    total = 0

    for p in iter_py_files(root):
        total += 1
        if args.mode == "helpcheck":
            if not has_argparse(p):
                continue
            rc, out, err = run_help(p, args.timeout)
            if rc != 0:
                failures.append((str(p), f"help rc={rc}", err or out))
        else:
            rc, out = try_import(p, args.timeout)
            if rc != 0:
                failures.append((str(p), f"import rc={rc}", out))

    if failures:
        print(f"== {args.mode} FAIL ({len(failures)}) / scanned={total}")
        for path, why, msg in failures:
            print("\n---", path, ":", why)
            print(
                textwrap.shorten(
                    msg.replace("\n", " | "), width=1000, placeholder="..."
                )
            )
        sys.exit(1)
    else:
        print(f"{args.mode} OK — scanned={total}")


if __name__ == "__main__":
    main()
