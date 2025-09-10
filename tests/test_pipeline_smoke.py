# tests/test_pipeline_smoke.py
import json, tempfile, os, subprocess, sys, pathlib

GPI_YML = """\
BUDGET_TOTAL: 5
SP_RATIO: 0.6
COMBO_RATIO: 0.4
EV_MIN_SP: 0.20
EV_MIN_GLOBAL: 0.40
MAX_VOL_PAR_CHEVAL: 0.60
ALLOW_JE_NA: true
PAUSE_EXOTIQUES: false
OUTDIR_DEFAULT: "runs/test"
EXCEL_PATH: "modele_suivi_courses_hippiques.xlsx"
CALIB_PATH: "payout_calibration.yaml"
MODEL: "GPI v5.1"
"""

def sample(h, rc="R1C1"):
    return {
        "rc": rc, "hippodrome":"Test","date":"2025-09-10","discipline":"trot",
        "runners":[
            {"id":"1","name":"A","odds":3.2,"je_stats":{"j_win":12,"e_win":15}},
            {"id":"2","name":"B","odds":4.8,"je_stats":{"j_win":10,"e_win":9}},
            {"id":"3","name":"C","odds":9.5,"je_stats":{"j_win":8,"e_win":7}},
            {"id":"4","name":"D","odds":15.0,"je_stats":{"j_win":5,"e_win":6}},
        ],
        "id2name":{"1":"A","2":"B","3":"C","4":"D"}
    }

def test_smoke_run(tmp_path):
    h30 = sample("H30"); h5 = sample("H05")   # mêmes partants, cotes plausibles
    h05_path = tmp_path/"h5.json"; h30_path = tmp_path/"h30.json"
    gpi_path = tmp_path/"gpi.yml"; outdir = tmp_path/"out"
    h30_path.write_text(json.dumps(h30), encoding="utf-8")
    h05_path.write_text(json.dumps(h5), encoding="utf-8")
    gpi_path.write_text(GPI_YML, encoding="utf-8")

    cmd = [sys.executable, "pipeline_run.py",
           "--h30", str(h30_path),
           "--h5",  str(h05_path),
           "--gpi", str(gpi_path),
           "--outdir", str(outdir)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr

    # artefacts
    assert (outdir/"tickets.json").exists()
    assert (outdir/"ligne.csv").exists()
    assert (outdir/"arrivee_placeholder.json").exists()
    assert (outdir/"cmd_update_excel.txt").exists()

    # vérifs tickets
    data=json.loads((outdir/"tickets.json").read_text(encoding="utf-8"))
    tickets=data["tickets"]
    stake_total=sum(t.get("stake",0) for t in tickets)
    assert stake_total <= 5.00 + 1e-6
    sp_cnt = sum(1 for t in tickets if t["type"]=="SP")
    combo_cnt = sum(1 for t in tickets if t["type"]!="SP")
    assert sp_cnt >= 1
    assert combo_cnt <= 1
