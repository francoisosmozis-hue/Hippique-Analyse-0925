import os
import subprocess
import sys

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# ➜ Make the package "src" importable (src/...): add /app (parent of src) to sys.path
ROOT_DIR = "/app"
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

app = FastAPI()

def _find_script():
    # use your real orchestrator in /app/src/
    candidates = [
        "/app/src/runner.py",
        "/app/src/service.py",
        "/app/src/plan.py"
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("Aucun orchestrateur trouvé (runner.py, service.py, plan.py).")

def _exec(cmd, timeout=280):
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, timeout=timeout)
        return out
    except subprocess.CalledProcessError as e:
        raise HTTPException(500, detail={"cmd": cmd, "stdout": e.output[-4000:]})
    except subprocess.TimeoutExpired:
        raise HTTPException(504, detail=f"Timeout {timeout}s")

class RunBody(BaseModel):
    phase: str = "H5"
    budget: float = 5.0
    extra_args: list[str] | None = None

@app.get("/healthz")
def healthz():
    return {"ok": True, "version": "gpi-v5.1", "tz": os.getenv("TZ","Europe/Paris")}

@app.get("/debug/ls")
def debug_ls():
    def ls(p):
        try: return sorted(os.listdir(p))
        except Exception as e: return str(e)
    import sys as _sys
    return {
        "python_version": _sys.version,
        "sys_path": _sys.path,
        "/app": ls("/app"),
        "/app/src": ls("/app/src"),
    }

@app.post("/run")
def run_job(body: RunBody):
    script = _find_script()
    cmd = [sys.executable, script]
    # start simple: pass only extra args until we confirm runner.py CLI
    if body.extra_args:
        cmd += list(body.extra_args)
    out = _exec(cmd)
    return {"ok": True, "cmd": cmd, "stdout_tail": out[-4000:]}

@app.get("/debug/cat")
def debug_cat(path: str):
    """Retourne les 40 premières lignes d'un fichier pour inspection."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()[:40]
        return {"path": path, "content": "".join(lines)}
    except Exception as e:
        return {"error": str(e)}
