#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import json
from pathlib import Path

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recalibrate payouts and set PAUSE_EXOTIQUES flag"
    )
    parser.add_argument(
        "--history", nargs="+", required=True, help="Fichiers JSON de rapports"
    )
    parser.add_argument("--out", default="payout_calibration.yaml")
    args = parser.parse_args()

    results = {"EMA_ABS_ERROR_PCT": {}}
    for p in args.history:
        path = Path(p)
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ema = results.setdefault("EMA_ABS_ERROR_PCT", {})
            if isinstance(data, dict):
                typ = data.get("type")
                err = data.get("abs_error_pct")
                if typ and err is not None:
                    ema[typ] = float(err)
        except Exception:
            pass

    ema = results.get("EMA_ABS_ERROR_PCT", {"CP": 20.0, "TRIO": 20.0, "ZE4": 20.0})
    pause = any(ema.get(k, 100.0) > 15.0 for k in ("CP", "TRIO", "ZE4"))
    
    # Écris le drapeau consensuel dans payout_calibration.yaml
    block = {"PAUSE_EXOTIQUES": bool(pause), "EMA_ABS_ERROR_PCT": ema}
    with open(args.out, "a", encoding="utf-8") as f:
        f.write("\n# auto-flag J+1\n")
        for key, value in block.items():
            f.write(f"{key}: {value}\n")
    print(f"[Calibration] PAUSE_EXOTIQUES={pause} (seuil 15%)")

if __name__ == "__main__":
    main()
