#!/usr/bin/env python3
import py_compile
import sys
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
    "Hippique-Analyse-0925",
}


def should_skip(p: Path) -> bool:
    if any(part in SKIP_DIRS for part in p.parts):
        return True
    name = p.name
    # ignorer impls instables et fichiers quarantainés
    if name.endswith("_impl.py") or name.endswith(".disabled"):
        return True
    return False


errs = []
for p in Path(".").rglob("*.py"):
    if should_skip(p):
        continue
    try:
        py_compile.compile(str(p), doraise=True)
    except Exception as e:
        errs.append((str(p), e))

if errs:
    print("== Syntax errors ==")
    for f, e in errs:
        print(" -", f, "->", e)
    sys.exit(1)
print("Syntax OK")
