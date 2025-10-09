#!/usr/bin/env python3
import os, subprocess
from pathlib import Path
from watchfiles import watch

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [ROOT/'gemini_sessions']
MSG = "chore(gemini): autosave"

def run(cmd): subprocess.run(cmd, check=False)

if __name__ == "__main__":
    os.chdir(ROOT)
    print("[autosave] watching gemini_sessions/ → git add/commit/push")
    for _changes in watch(*TARGETS, debounce=1500, stop_event=None):
        run(["git", "add", "gemini_sessions"])
        # commit seulement s'il y a du staged
        if subprocess.call(["git", "diff", "--cached", "--quiet"]) != 0:
            run(["git", "commit", "-m", MSG])
            run(["git", "push"])
