"""FastAPI service exposing entry points for Hippique Analyse scripts."""
from __future__ import annotations

import sys
import subprocess
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

app = FastAPI(title="Hippique Analyse GPI v5.1")


class AnalyseRequest(BaseModel):
    """Payload used to trigger analysis scripts."""

    script: Literal["runner_chain", "analyse_courses_du_jour_enrichie"] = "runner_chain"
    reunion: Optional[str] = None
    course: Optional[str] = None
    phase: Optional[str] = "H5"
    data_dir: Optional[str] = None
    budget: Optional[float] = None
    kelly: Optional[float] = None
    from_geny_today: bool = False
    reunion_url: Optional[str] = None
    reunions_file: Optional[str] = None
    upload_drive: bool = False
    drive_folder_id: Optional[str] = None
    extra_args: List[str] = Field(default_factory=list)


class PromptRequest(BaseModel):
    """Payload for generating the GPI prompt."""

    reunion: Optional[str] = None
    course: Optional[str] = None
    phase: Optional[str] = None
    extra_args: List[str] = Field(default_factory=list)


class ResultRequest(BaseModel):
    """Payload for updating the Excel tracking workbook with race results."""

    result_file: str
    tickets: str
    mises: float
    gains: float
    excel: str = "modele_suivi_courses_hippiques.xlsx"
    extra_args: List[str] = Field(default_factory=list)


def _run_command(cmd: List[str]) -> dict:
    """Execute ``cmd`` and return standard output, error and status code."""

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - surfaces deployment issues
        raise HTTPException(status_code=500, detail=f"Executable introuvable: {exc}")
    except Exception as exc:  # pragma: no cover - defensive programming
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "cmd": cmd,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "rc": proc.returncode,
    }


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Health probe used by Cloud Run."""

    return {"status": "ok"}


@app.post("/analyse")
def analyse(payload: AnalyseRequest) -> dict:
    """Run either ``runner_chain.py`` or ``analyse_courses_du_jour_enrichie.py``."""

    if payload.script == "runner_chain":
        script_path = BASE_DIR / "runner_chain.py"
        if not payload.reunion or not payload.course:
            raise HTTPException(
                status_code=400,
                detail="Les paramètres 'reunion' et 'course' sont requis pour runner_chain.",
            )
        cmd = [
            "python",
            str(script_path),
            "--reunion",
            payload.reunion,
            "--course",
            payload.course,
        ]
        if payload.phase:
            cmd.extend(["--phase", payload.phase])
    else:
        script_path = BASE_DIR / "analyse_courses_du_jour_enrichie.py"
        cmd = ["python", str(script_path)]
        if payload.data_dir:
            cmd.extend(["--data-dir", payload.data_dir])
        if payload.budget is not None:
            cmd.extend(["--budget", str(payload.budget)])
        if payload.kelly is not None:
            cmd.extend(["--kelly", str(payload.kelly)])
        if payload.from_geny_today:
            cmd.append("--from-geny-today")
        if payload.reunion_url:
            cmd.extend(["--reunion-url", payload.reunion_url])
        if payload.phase:
            cmd.extend(["--phase", payload.phase])
        if payload.reunion:
            cmd.extend(["--reunion", payload.reunion])
        if payload.course:
            cmd.extend(["--course", payload.course])
        if payload.reunions_file:
            cmd.extend(["--reunions-file", payload.reunions_file])
        if payload.upload_drive:
            cmd.append("--upload-drive")
        if payload.drive_folder_id:
            cmd.extend(["--drive-folder-id", payload.drive_folder_id])

    cmd = [*cmd, *payload.extra_args]
    return _run_command(cmd)


@app.get("/analyse/{reunion}/{course}")
def analyse_course(reunion: str, course: str, phase: str = "H5") -> dict:
    """Compatibility route mirroring the legacy CLI example."""

    payload = AnalyseRequest(reunion=reunion, course=course, phase=phase)
    return analyse(payload)


@app.post("/prompt")
def generate_prompt(payload: PromptRequest) -> dict:
    """Generate the GPI prompt by delegating to ``prompt_analyse.py``."""

    script_path = BASE_DIR / "prompt_analyse.py"
    cmd = ["python", str(script_path)]
    if payload.reunion:
        cmd.extend(["--reunion", payload.reunion])
    if payload.course:
        cmd.extend(["--course", payload.course])
    if payload.phase:
        cmd.extend(["--phase", payload.phase])
    cmd = [*cmd, *payload.extra_args]
    return _run_command(cmd)


@app.post("/result")
def update_result(payload: ResultRequest) -> dict:
    """Update the tracking Excel workbook with the latest race results."""

    script_path = BASE_DIR / "update_excel_with_results.py"
    cmd = [
        "python",
        str(script_path),
        "--excel",
        payload.excel,
        "--result",
        payload.result_file,
        "--tickets",
        payload.tickets,
        "--mises",
        str(payload.mises),
        "--gains",
        str(payload.gains),
    ]
    cmd = [*cmd, *payload.extra_args]
    return _run_command(cmd)
