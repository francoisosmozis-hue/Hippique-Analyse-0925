import os
import re
import json
import tempfile
import subprocess
from pathlib import Path
from typing import Optional, List, Literal, Tuple

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# =========================
# Config via variables d'env
# =========================
DEFAULT_BUDGET = float(os.getenv("DEFAULT_BUDGET", "5.0"))
MIN_EV_SP = float(os.getenv("MIN_EV_SP", "0.20"))
MIN_EV_COMBO = float(os.getenv("MIN_EV_COMBO", "0.40"))
MAX_VOLAT_PER_HORSE = float(os.getenv("MAX_VOLAT_PER_HORSE", "0.60"))
DATA_MODE = os.getenv("DATA_MODE", "web")  # "web" ou "local"

APP_VERSION = "GPI v5.1"

app = FastAPI(title="Hippique Analyse", version=APP_VERSION)


# =========================
# Schémas d'entrée/sortie
# =========================
class AnalyseParams(BaseModel):
    # Paramètres clefs pour déclencher le pipeline
    meeting: Optional[str] = Field(
        default=None,
        description="Identifiant réunion/courses (si utilisé par tes scripts, ex: 'R1C3')."
    )
    reunion: Optional[str] = Field(
        default=None,
        description="Identifiant de la réunion (ex: 'R1').",
    )
    course: Optional[str] = Field(
        default=None,
        description="Identifiant de la course (ex: 'C3').",
    )
    course_url: Optional[str] = Field(
        default=None,
        description="URL ZEturf/Geny pour scrap (si DATA_MODE='web')."
    )
    phase: Literal["H30", "H5", "RACE"] = Field(
        default="H5",
        description="Phase d’analyse (H30 ou H5 ou RACE/post)."
    )

    # Overrides facultatifs
    default_budget: Optional[float] = Field(default=None, ge=0)
    min_ev_sp: Optional[float] = Field(default=None)
    min_ev_combo: Optional[float] = Field(default=None)
    max_volat_per_horse: Optional[float] = Field(default=None)
    data_mode: Optional[Literal["web", "local"]] = Field(default=None)

    # Avancé : flags pour activer/désactiver certaines étapes
    run_prompt: bool = Field(default=True, description="Générer le prompt final Lyra GPI v5.1")
    run_export: bool = Field(default=True, description="Exporter p_finale et tickets")


class AnalyseResult(BaseModel):
    ok: bool
    app: str
    params: AnalyseParams
    outputs_dir: Optional[str] = None
    p_finale_path: Optional[str] = None
    tickets: Optional[dict] = None
    logs: Optional[List[str]] = None


# =========================
# Endpoints basiques
# =========================
@app.get("/")
def root():
    return {
        "ok": True,
        "app": f"Hippique Analyse {APP_VERSION}",
        "defaults": {
            "DEFAULT_BUDGET": DEFAULT_BUDGET,
            "MIN_EV_SP": MIN_EV_SP,
            "MIN_EV_COMBO": MIN_EV_COMBO,
            "MAX_VOLAT_PER_HORSE": MAX_VOLAT_PER_HORSE,
            "DATA_MODE": DATA_MODE,
        },
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok", "app": APP_VERSION}


# =========================
# Endpoint /analyse
# =========================
def _read_json_if_exists(p: Path) -> Optional[dict]:
    try:
        if p.exists() and p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def _format_subprocess_failure(label: str, proc: subprocess.CompletedProcess) -> str:
    """Format stdout/stderr from a subprocess failure for easier debugging."""
    parts: List[str] = [f"{label} (code {proc.returncode})."]
    if proc.stdout:
        parts.append("STDOUT:")
        parts.append(proc.stdout.strip())
    if proc.stderr:
        parts.append("STDERR:")
        parts.append(proc.stderr.strip())

    detail = "\n".join(parts)
    max_len = 12_000
    if len(detail) > max_len:
        detail = detail[:max_len] + "\n… (truncated)"
    return detail


def _normalise_rc_component(value: str, prefix: str) -> str:
    text = str(value).strip().upper().replace(" ", "")
    if not text:
        raise ValueError(f"Identifiant {prefix} vide")
    if text.startswith(prefix):
        text = text[len(prefix) :]
    if not text.isdigit():
        raise ValueError(f"Identifiant {prefix} invalide: {value!r}")
    number = int(text)
    if number <= 0:
        raise ValueError(f"Identifiant {prefix} invalide: {value!r}")
    return f"{prefix}{number}"


def _split_meeting_label(value: str) -> Tuple[str, str]:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    match = re.fullmatch(r"R(?P<reunion>\d+)C(?P<course>\d+)", cleaned)
    if not match:
        raise ValueError("Paramètre meeting doit suivre le format 'R<num>C<num>' (ex: 'R1C3').")
    reunion = _normalise_rc_component(match.group("reunion"), "R")
    course = _normalise_rc_component(match.group("course"), "C")
    return reunion, course


def _resolve_reunion_course(params: AnalyseParams) -> Tuple[Optional[str], Optional[str]]:
    meeting_reunion: Optional[str] = None
    meeting_course: Optional[str] = None
    if params.meeting:
        meeting_reunion, meeting_course = _split_meeting_label(params.meeting)

    reunion = _normalise_rc_component(params.reunion, "R") if params.reunion else None
    course = _normalise_rc_component(params.course, "C") if params.course else None

    if meeting_reunion:
        if reunion and reunion != meeting_reunion:
            raise ValueError("Le champ meeting ne correspond pas à la réunion fournie.")
        if course and course != meeting_course:
            raise ValueError("Le champ meeting ne correspond pas à la course fournie.")
        reunion = meeting_reunion
        course = meeting_course

    if (reunion is None) != (course is None):
        raise ValueError("Fournir reunion et course ensemble (ou utiliser meeting).")

    return reunion, course


@app.post("/analyse", response_model=AnalyseResult)
def analyse(body: AnalyseParams):
    """
    Pilote ton pipeline:
      - analyse_courses_du_jour_enrichie.py (référence GPI v5.1)
      - p_finale_export.py (tickets / ROI)
    Hypothèse: les scripts sont à la racine du conteneur.
    """

    # Résolution des paramètres effectifs (env -> overrides -> body)
    eff_default_budget = body.default_budget if body.default_budget is not None else DEFAULT_BUDGET
    eff_min_ev_sp = body.min_ev_sp if body.min_ev_sp is not None else MIN_EV_SP
    eff_min_ev_combo = body.min_ev_combo if body.min_ev_combo is not None else MIN_EV_COMBO
    eff_max_volat = body.max_volat_per_horse if body.max_volat_per_horse is not None else MAX_VOLAT_PER_HORSE
    eff_data_mode = body.data_mode if body.data_mode is not None else DATA_MODE

    # Dossier de sortie dédié à l’appel
    outputs_dir = Path(tempfile.mkdtemp(prefix="hippique_"))
    logs: List[str] = []

    # Prépare l’environnement pour les scripts Python appelés
    env = os.environ.copy()
    env["DEFAULT_BUDGET"] = str(eff_default_budget)
    env["MIN_EV_SP"] = str(eff_min_ev_sp)
    env["MIN_EV_COMBO"] = str(eff_min_ev_combo)
    env["MAX_VOLAT_PER_HORSE"] = str(eff_max_volat)
    env["DATA_MODE"] = eff_data_mode
    env["OUTPUTS_DIR"] = str(outputs_dir)

    # Construis la commande du script principal
    # NOTE: adapte les flags si ton script en attend d’autres (meeting, URL, phase, etc.)
    cmd = [
        "python", "-u", "analyse_courses_du_jour_enrichie.py",
        "--phase", body.phase,
    ]
    try:
        reunion_label, course_label = _resolve_reunion_course(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if reunion_label and course_label:
        cmd += ["--reunion", reunion_label, "--course", course_label]
    if body.course_url:
        cmd += ["--reunion-url", body.course_url]

    # Exécution du pipeline principal
    try:
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent),
            timeout=60 * 12,  # 12 min max pour être large
            check=False,
        )
        if proc.stdout:
            logs += [l for l in proc.stdout.splitlines() if l.strip()]
        if proc.stderr:
            logs += [f"[stderr] {l}" for l in proc.stderr.splitlines() if l.strip()]

        if proc.returncode != 0:
            detail = _format_subprocess_failure(
                "analyse_courses_du_jour_enrichie.py a échoué", proc
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timeout pipeline analyse (12 min).")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lancement pipeline: {e}")

    # Optionnel: exporter p_finale / tickets via p_finale_export.py
    tickets = None
    p_finale_path = None

    if body.run_export:
        try:
            export_cmd = [
                "python", "-u", "p_finale_export.py",
                "--outputs-dir", str(outputs_dir)
            ]
            proc2 = subprocess.run(
                export_cmd,
                env=env,
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).parent),
                timeout=60 * 5,
                check=False,
            )
            if proc2.stdout:
                logs += [l for l in proc2.stdout.splitlines() if l.strip()]
            if proc2.stderr:
                logs += [f"[stderr] {l}" for l in proc2.stderr.splitlines() if l.strip()]

            if proc2.returncode != 0:
                detail = _format_subprocess_failure(
                    "p_finale_export.py a échoué", proc2
                )
                raise HTTPException(status_code=500, detail=detail)


            # Convention: le script export crée p_finale.json et tickets.json dans outputs_dir
            p_finale = _read_json_if_exists(outputs_dir / "p_finale.json")
            tjson = _read_json_if_exists(outputs_dir / "tickets.json")
            tickets = tjson if tjson else None
            p_finale_path = str(outputs_dir / "p_finale.json") if p_finale else None

        except subprocess.TimeoutExpired:
            logs.append("[export] Timeout export (5 min).")
        except Exception as e:
            logs.append(f"[export] Erreur: {e}")

    # Optionnel: génération du prompt GPI v5.1 (si ton script principal ne l’a pas déjà fait)
    if body.run_prompt:
        # Convention: le script principal ou l’export aura créé un prompt dans outputs_dir/prompts/
        pass

    return AnalyseResult(
        ok=True,
        app=f"Hippique Analyse {APP_VERSION}",
        params=body,
        outputs_dir=str(outputs_dir),
        p_finale_path=p_finale_path,
        tickets=tickets,
        logs=logs[-200:],  # on renvoie la fin des logs (utile en debug)
    )


if __name__ == "__main__":
    # Cloud Run fournit PORT, mais on supporte un run local python main.py
    port = int(os.getenv("PORT", "8080"))
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=port)
