#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
runner_chain.py — Orchestrateur GPI v5.1 (EV centralisée + ROI global + contrôles)
Correctifs inclus :
- Suppression d'un bloc mal indenté dans _build_global_reporting (bug syntaxe).
- Chemins par défaut relatifs (compat GitHub Actions) pour Excel & calibration.
- Ajout 'reporting_global' de façon sûre après décision pipeline.
- Logs & sorties stables.
"""
import argparse, json, pathlib, time, sys, shlex, subprocess, os
from typing import Any, Dict, List, Optional

# === Reporting global EV/ROI (sécurisé) =====================================
def _build_global_reporting(pipeline_decision: Dict[str, Any] | None):
    """
    Agrège les métriques EV/ROI à partir du reporting détaillé du pipeline.
    Retourne un dict avec: total_stake_eur, ev_total_eur, roi_estimated,
    expected_gross_return_eur, nb_tickets, by_ticket, notes (si abstention).
    """
    rep = (pipeline_decision or {}).get("reporting", {}) or {}
    out = {
        "total_stake_eur": rep.get("total_stake_eur", 0.0),
        "ev_total_eur": rep.get("ev_total_eur", 0.0),
        "roi_estimated": rep.get("roi_estimated", None),
        "expected_gross_return_eur": rep.get("expected_gross_return_eur", 0.0),
        "nb_tickets": len(rep.get("tickets", [])),
        "by_ticket": rep.get("tickets", []),
    }
    if (pipeline_decision or {}).get("abstention") or (pipeline_decision or {}).get("abstain"):
        out.setdefault("notes", []).append("Abstention (pipeline_decision).")
    return out

# ────────────────────────────── Utils I/O ──────────────────────────────
def load_json(path: str) -> Dict[str, Any] | None:
    p = pathlib.Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))

def save_json(path: str, obj: Dict[str, Any]) -> None:
    pathlib.Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def is_fresh(path: str, ttl_hours: float) -> bool:
    p = pathlib.Path(path)
    if not p.exists():
        return False
    age_h = (time.time() - p.stat().st_mtime) / 3600.0
    return age_h <= ttl_hours

def _safe_import(name: str):
    try:
        return __import__(name)
    except Exception as e:
        print(f"[runner_chain] Avertissement: import '{name}' impossible : {e}", file=sys.stderr)
        return None

simulate_wrapper = _safe_import("simulate_wrapper")
pipeline_run     = _safe_import("pipeline_run")
online_fetch     = _safe_import("online_fetch_zeturf")
get_arrivee_geny = _safe_import("get_arrivee_geny")
fetch_je_stats   = _safe_import("fetch_je_stats")
fetch_je_chrono  = _safe_import("fetch_je_chrono")

# Chemins par défaut RELATIFS (compat GitHub runner)
DEFAULT_EXCEL = str(pathlib.Path("excel") / "modele_suivi_courses_hippiques.xlsx")
DEFAULT_CALIB = str(pathlib.Path("config") / "payout_calibration.yaml")

def ensure_data_dir(tag: str) -> pathlib.Path:
    base = pathlib.Path("data") / tag
    base.mkdir(parents=True, exist_ok=True)
    return base

# ────────────────────────────── Fetch snapshot ──────────────────────────────
def fetch_snapshot(reunion: str, course: str, phase: str) -> Dict[str, Any]:
    if online_fetch and hasattr(online_fetch, "fetch_race_snapshot"):
        return online_fetch.fetch_race_snapshot(reunion, course, phase=phase)
    raise RuntimeError("fetch_race_snapshot indisponible (online_fetch_zeturf.py).")

def validate_snapshot_or_die(snapshot: Dict[str, Any], phase: str) -> None:
    if not isinstance(snapshot, dict):
        print(f"[runner_chain] ERREUR: snapshot {phase} invalide (type).", file=sys.stderr)
        sys.exit(2)
    partants = snapshot.get("partants")
    if not isinstance(partants, list) or len(partants) == 0:
        print(f"[runner_chain] ERREUR: snapshot {phase} vide ou sans 'partants'.", file=sys.stderr)
        sys.exit(2)

# ────────────────────────────── EV exotiques ──────────────────────────────
EXOTIC_TYPES = {
    "TRIO","ZE4","ZE234","COUPLE","COUPLE_PLACE","CP","COUPLE GAGNANT","COUPLE PLACE"
}

def filter_exotics_by_overround(out: Dict[str, Any], overround_max: float = 1.30) -> None:
    """Supprime les combinés si overround trop élevé (marché peu jouable)."""
    market = out.get("market") or {}
    ov = market.get("overround")
    if ov is None:
        return
    try:
        if float(ov) > float(overround_max):
            kept = []
            for t in out.get("tickets", []):
                if (t.get("type","") or "").upper() in EXOTIC_TYPES:
                    continue
                kept.append(t)
            if len(kept) != len(out.get("tickets", [])):
                out["tickets"] = kept
                out.setdefault("notes", []).append(f"exotiques retirés (overround {ov:.3f} > {overround_max:.2f})")
    except Exception:
        pass

def validate_exotics_with_simwrapper(out: Dict[str, Any],
                                     calib_path: Optional[str],
                                     ev_min: float,
                                     payout_min: float,
                                     allow_heuristic: bool) -> Dict[str, Any]:
    """
    Passe tous les combinés via simulate_wrapper.evaluate_combo.
    Retire ceux qui ne passent pas (status != ok, ou ev < seuil, ou payout < payout_min).
    Ajoute un résumé agrégé (stake_total, ev_ratio pondéré).
    """
    if not simulate_wrapper or not hasattr(simulate_wrapper, "evaluate_combo"):
        out.setdefault("notes", []).append("simulate_wrapper indisponible → combinés conservés tels quels (non recommandé)")
        return {"validated": False, "reasons": ["simulate_wrapper_missing"]}

    market = out.get("market") or {}
    horses = market.get("horses") or []
    p_place = {str(h.get("num")): float(h.get("p", 0.0)) for h in horses if h.get("num") is not None}

    new_tickets: List[Dict[str, Any]] = []
    dropped_reasons: List[str] = []
    exo_ok_count = exo_ko_count = 0
    exo_stake_sum = 0.0
    exo_ev_num = 0.0

    for t in out.get("tickets", []):
        typ = (t.get("type") or "").upper()
        if typ in EXOTIC_TYPES:
            legs  = [str(x) for x in t.get("legs", []) if x is not None]
            stake = float(t.get("stake", 0.0) or 0.0)
            nplace = 3 if typ in ("TRIO","ZE4","ZE234") else (3 if len(horses) >= 8 else 2)
            res = simulate_wrapper.evaluate_combo(
                combo_type=typ, legs=legs, stake=stake,
                p_place=p_place, nplace=nplace,
                calib_path=calib_path, allow_heuristic=bool(allow_heuristic)
            )
            ok = (res.get("status") == "ok"
                  and res.get("ev_ratio") is not None
                  and float(res["ev_ratio"]) >= ev_min
                  and res.get("payout_expected") is not None
                  and float(res["payout_expected"]) >= payout_min)
            t["ev_check"] = res
            if ok:
                new_tickets.append(t)
                exo_ok_count += 1
                exo_stake_sum += stake
                exo_ev_num += float(res.get("ev_ratio", 0.0)) * stake
            else:
                exo_ko_count += 1
                reason = (f"{typ} rejeté: legs={legs} stake={stake:.2f} "
                          f"status={res.get('status')} ev={res.get('ev_ratio')} "
                          f"payout={res.get('payout_expected')}")
                if res.get("status") == "insufficient_data":
                    reason += " (calibration/probas insuffisantes)"
                dropped_reasons.append(reason)
        else:
            new_tickets.append(t)
    out["tickets"] = new_tickets
    if dropped_reasons:
        out.setdefault("notes", []).extend(dropped_reasons)

    exo_ev_w = (exo_ev_num / exo_stake_sum) if exo_stake_sum > 0 else None
    summary = {"ok": exo_ok_count, "ko": exo_ko_count,
               "stake_total": round(exo_stake_sum, 2),
               "ev_ratio_weighted": (round(exo_ev_w, 4) if exo_ev_w is not None else None)}
    return {"validated": True, "reasons": dropped_reasons, "summary": summary}

# ────────────────────────────── EV SP (Dutching) ──────────────────────────────
def _extract_sp_ticket(out: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for t in out.get("tickets", []):
        typ = (t.get("type") or "").upper()
        label = (t.get("label") or "").upper()
        if label == "SP_DUTCHING_GPIv51" or typ in ("SP","SIMPLE_PLACE_DUTCHING","DUTCHING_SP","PLACE_DUTCHING"):
            return t
    return None

def _iter_legs_generic(ticket: Dict[str, Any]) -> List[Dict[str, Any]]:
    legs = []
    for key in ("legs","bets"):
        if key in ticket and isinstance(ticket[key], list):
            for leg in ticket[key]:
                if not isinstance(leg, dict): continue
                num = str(leg.get("num") or leg.get("horse") or leg.get("id") or "")
                if not num: continue
                stake = float(leg.get("stake", 0.0) or leg.get("mise", 0.0) or 0.0)
                odds = None
                for ok in ("cote_place","odds","cote","odd"):
                    if ok in leg and leg[ok] is not None:
                        try:
                            odds = float(str(leg[ok]).replace(",", "."))
                            break
                        except Exception:
                            pass
                legs.append({"num": num, "stake": stake, "odds": odds})
            if legs:
                return legs
    alloc = ticket.get("allocation")
    if isinstance(alloc, dict):
        for k, v in alloc.items():
            try:
                num = str(k)
                stake = float(v)
            except Exception:
                continue
            legs.append({"num": num, "stake": stake, "odds": None})
    return legs

def estimate_sp_ev(out: Dict[str, Any],
                   ev_min: float,
                   roi_min: float) -> Dict[str, Any]:
    market = out.get("market") or {}
    horses = market.get("horses") or []
    p_map = {str(h.get("num")): float(h.get("p", 0.0)) for h in horses if h.get("num") is not None}

    t = _extract_sp_ticket(out)
    if not t:
        return {"status": "missing", "ev_ratio": None, "roi_est": None, "notes": ["no_sp_ticket"]}

    legs = _iter_legs_generic(t)
    if not legs:
        return {"status": "insufficient_data", "ev_ratio": None, "roi_est": None, "notes": ["no_legs"]}

    total_stake = 0.0
    ev_euros     = 0.0
    missing_odds = False

    for leg in legs:
        num   = leg.get("num")
        stake = float(leg.get("stake", 0.0) or 0.0)
        odds  = leg.get("odds", None)
        if stake <= 0:
            continue
        total_stake += stake

        p = float(p_map.get(str(num), 0.0))
        if odds is None:
            try:
                mh = next((h for h in horses if str(h.get("num")) == str(num)), None)
                if mh and mh.get("cote") is not None:
                    odds = float(mh["cote"])
            except Exception:
                pass
        if odds is None:
            missing_odds = True
            continue

        ev_leg = p * stake * (float(odds) - 1.0) - (1.0 - p) * stake
        ev_euros += ev_leg

    if total_stake <= 0.0:
        return {"status": "insufficient_data", "ev_ratio": None, "roi_est": None, "notes": ["stake_zero_or_missing"]}

    ev_ratio = ev_euros / total_stake
    roi_est  = ev_ratio
    status = "ok" if (ev_ratio >= ev_min and roi_est >= roi_min) else "ko"
    notes = []
    if missing_odds:
        notes.append("some_odds_missing")

    return {"status": status, "ev_ratio": float(ev_ratio), "roi_est": float(roi_est),
            "stake": float(total_stake), "notes": notes, "legs_count": len(legs)}

def summarize_exotics_ev(out: Dict[str, Any]) -> Dict[str, Any]:
    exo_stake = 0.0
    exo_ev_num = 0.0
    for t in out.get("tickets", []):
        typ = (t.get("type") or "").upper()
        if typ in EXOTIC_TYPES:
            stake = float(t.get("stake", 0.0) or 0.0)
            ev = None
            if isinstance(t.get("ev_check"), dict):
                ev = t["ev_check"].get("ev_ratio")
            if stake > 0 and ev is not None:
                exo_stake += stake
                exo_ev_num += float(ev) * stake
    ev_w = (exo_ev_num / exo_stake) if exo_stake > 0 else None
    return {"stake_total": round(exo_stake, 2),
            "ev_ratio_weighted": (round(ev_w, 4) if ev_w is not None else None)}

# ────────────────────────────── Enrichissement & pré-check H-5 ───────────────
def pre_enrich_H5_if_possible(reunion: str, course: str, snapshot_path: str) -> None:
    """Soft-call des enrichissements J/E & chronos si les modules existent."""
    try:
        if fetch_je_stats and hasattr(fetch_je_stats, "enrich_from_snapshot"):
            fetch_je_stats.enrich_from_snapshot(snapshot_path, reunion=reunion, course=course)
    except Exception as e:
        print(f"[runner_chain] enrich J/E ignoré: {e}", file=sys.stderr)
    try:
        if fetch_je_chrono and hasattr(fetch_je_chrono, "enrich_from_snapshot"):
            fetch_je_chrono.enrich_from_snapshot(snapshot_path, reunion=reunion, course=course)
    except Exception as e:
        print(f"[runner_chain] enrich chronos ignoré: {e}", file=sys.stderr)

def warn_if_stats_chronos_missing(data_dir: pathlib.Path, reunion: str, course: str) -> None:
    """
    Blocage dur : course non jouable si fichiers CSV J/E ou chronos absents.
    """
    patterns = [
        f"{reunion}_{course}_je_stats.csv",
        f"{reunion}_{course}_chronos.csv",
        "je_stats.csv",
        "chronos.csv",
    ]
    found = False
    for pat in patterns:
        if any(p.name == pat for p in data_dir.glob("*.csv")):
            found = True
            break
    if not found:
        print("[runner_chain] ERREUR: données J/E et/ou chronos manquantes → course non jouable.", file=sys.stderr)
        sys.exit(2)

# ────────────────────────────── Tracking CSV ──────────────────────────────
def export_tracking_csv_line(out: Dict[str, Any], budget: float) -> str:
    meta = out.get("meta", {})
    market = out.get("market", {})
    n = market.get("n_partants") or len(market.get("horses", []))
    over = market.get("overround")
    tickets = out.get("tickets", [])
    types = "+".join(sorted(set([t.get("label") or t.get("type","") for t in tickets])))

    spv = (out.get("validation") or {}).get("sp") or {}
    sp_roi = spv.get("roi_est")
    exo_v = (out.get("validation") or {}).get("exotics_summary") or {}
    exo_ev_w = exo_v.get("ev_ratio_weighted")
    roi_global = (out.get("validation") or {}).get("roi_global_est")

    return ",".join([
        str(meta.get("reunion","")), str(meta.get("course","")),
        str(n), f"{over if over is not None else ''}",
        f"{budget:.2f}",
        "OK" if out.get("ev_ok") and not out.get("abstain") else "NO",
        types,
        f"{'' if sp_roi is None else round(float(sp_roi),4)}",
        f"{'' if exo_ev_w is None else round(float(exo_ev_w),4)}",
        f"{'' if roi_global is None else round(float(roi_global),4)}"
    ]) + "\n"

# ────────────────────────────── Main ──────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Runner GPI v5.1 (EV centralisée + ROI global + contrôles)")
    ap.add_argument("--reunion", required=True, help="ex: R1")
    ap.add_argument("--course", required=True, help="ex: C3")
    ap.add_argument("--phase", required=True, choices=["H30", "H5", "RESULT"])
    ap.add_argument("--ttl-hours", type=float, default=6.0)
    ap.add_argument("--budget", type=float, default=5.0)
    ap.add_argument("--kelly-frac", type=float, default=0.4)
    ap.add_argument("--excel", default=DEFAULT_EXCEL)
    ap.add_argument("--calibration", default=DEFAULT_CALIB)
    ap.add_argument("--ev-min-exotic", type=float, default=0.40)
    ap.add_argument("--payout-min-exotic", type=float, default=10.0)
    ap.add_argument("--overround-max", type=float, default=1.30)
    ap.add_argument("--ev-min-sp", type=float, default=0.40)
    ap.add_argument("--roi-min-sp", type=float, default=0.20)
    ap.add_argument("--allow-heuristic", action="store_true", help="Autoriser l'heuristique de simulate_wrapper si calibration absente")
    args = ap.parse_args()

    tag  = f"{args.reunion}{args.course}"
    base = ensure_data_dir(tag)

    if args.phase in ("H30", "H5"):
        snap_path = base / f"snapshot_{args.phase}.json"
        if not is_fresh(str(snap_path), args.ttl_hours):
            try:
                snap = fetch_snapshot(args.reunion, args.course, args.phase)
                validate_snapshot_or_die(snap, args.phase)
                save_json(str(snap_path), snap)
                print(f"[runner_chain] Snapshot {args.phase} enregistré: {snap_path}")
            except Exception as e:
                print(f"[runner_chain] ERREUR snapshot {args.phase}: {e}", file=sys.stderr)
                sys.exit(2)
        else:
            snap = load_json(str(snap_path))
            if snap is None:
                print(f"[runner_chain] ERREUR: snapshot {args.phase} non lisible.", file=sys.stderr)
                sys.exit(2)
            validate_snapshot_or_die(snap, args.phase)
            print(f"[runner_chain] Snapshot {args.phase} frais (≤{args.ttl_hours}h): {snap_path}")

        if args.phase == "H5":
            # (0) Enrichissements optionnels (J/E + chronos) pour booster p_finale en aval
            pre_enrich_H5_if_possible(args.reunion, args.course, str(snap_path))
            # (0b) Blocage dur si CSV J/E/chronos manquants (garantit EV exo)
            warn_if_stats_chronos_missing(base, args.reunion, args.course)

            if not pipeline_run or not hasattr(pipeline_run, "run_pipeline"):
                print("[runner_chain] ERREUR: pipeline_run.run_pipeline introuvable.", file=sys.stderr)
                sys.exit(2)

            out = pipeline_run.run_pipeline(
                reunion=args.reunion,
                course=args.course,
                snapshot_path=str(snap_path),
                budget=args.budget,
                kelly_frac=args.kelly_frac,
                enforce_gpi="v5.1",
            )

            # 0b) Reporting global depuis 'out' si présent (sûr)
            try:
                out["reporting_global"] = _build_global_reporting(out)
            except Exception:
                pass

            # 1) Filtre overround sur exotiques
            filter_exotics_by_overround(out, overround_max=args.overround_max)

            # 2) Validation combinés (simulate_wrapper, EV+payout)
            val_exo = validate_exotics_with_simwrapper(
                out,
                calib_path=args.calibration,
                ev_min=args.ev_min_exotic,
                payout_min=args.payout_min_exotic,
                allow_heuristic=args.allow_heuristic
            )

            # 3) Estimation EV/ROI du panier SP (Dutching) + résumé exotiques + ROI global
            val_sp = estimate_sp_ev(out, ev_min=args.ev_min_sp, roi_min=args.roi_min_sp)
            exo_summary = summarize_exotics_ev(out)

            sp_stake = float(val_sp.get("stake") or 0.0)
            sp_roi   = (float(val_sp.get("roi_est")) if isinstance(val_sp.get("roi_est"), (int,float)) else None)
            exo_ev_w = exo_summary.get("ev_ratio_weighted")
            total_stake = sp_stake + (exo_summary.get("stake_total") or 0.0)
            roi_global = None
            if total_stake > 0:
                num = 0.0
                if sp_roi is not None:
                    num += sp_roi * sp_stake
                if exo_ev_w is not None:
                    num += exo_ev_w * (exo_summary.get("stake_total") or 0.0)
                roi_global = num / total_stake

            # Filtre ROI global strict (abstention si < 20%)
            if roi_global is None or roi_global < 0.20:
                out.setdefault("notes", []).append(f"Abstention: ROI global trop faible ({roi_global})")
                out["abstain"] = True

            # 4) Décision finale : OK si exotiques validés OU SP ok
            has_tickets = bool(out.get("tickets"))
            sp_ok = (val_sp.get("status") == "ok")
            exo_still_present = any((t.get("type","") or "").upper() in EXOTIC_TYPES for t in out.get("tickets", []))
            ev_ok = bool(sp_ok or exo_still_present)

            out["ev_ok"]   = ev_ok and has_tickets
            out["abstain"] = not bool(out["ev_ok"])
            out.setdefault("validation", {})["exotics"] = val_exo
            out.setdefault("validation", {})["sp"]      = val_sp
            out.setdefault("validation", {})["exotics_summary"] = exo_summary
            out.setdefault("validation", {})["roi_global_est"]  = (round(roi_global,4) if roi_global is not None else None)

            # 4b) EV SP dans diagnostics (pour suivi)
            out.setdefault("diagnostics", {})["sp_ev_ratio"] = val_sp.get("ev_ratio")
            out.setdefault("diagnostics", {})["sp_roi_est"]  = val_sp.get("roi_est")

            if roi_global is not None:
                out.setdefault("notes", []).append(f"ROI global estimé (pondéré mises): {roi_global:.3f}")

            # 5) Persist analyse
            analysis_path = base / f"analysis_{args.phase}.json"
            save_json(str(analysis_path), out)
            print(f"[runner_chain] Analyse H-5 enregistrée: {analysis_path}")

            # 6) Tracking CSV compact (append)
            track_line = export_tracking_csv_line(out, budget=args.budget)
            with (base / "tracking.csv").open("a", encoding="utf-8") as fh:
                fh.write(track_line)
            print(f"[runner_chain] tracking.csv mis à jour (+1 ligne)")

            # 7) Impression commande post-course prête (avec roi_estime auto = SP)
            result_json = base / "arrivee.json"
            roi_estime = val_sp.get("roi_est")
            roi_arg = f' --roi_estime {roi_estime:.4f}' if isinstance(roi_estime, (int,float)) else ""
            cmd = (
                f'python update_excel_with_results.py'
                f' --excel "{args.excel}"'
                f' --result "{result_json}"'
                f' --tickets "<AUTOFILL>"'
                f' --mises {args.budget:.2f}'
                f' --gains <A_REMPLIR>{roi_arg}'
            )
            print("[runner_chain] Commande MAJ Excel (à exécuter après l'arrivée):")
            print(cmd)

            # 8) Sortie console courte
            print(json.dumps({
                "abstain": out["abstain"],
                "tickets": out.get("tickets", []),
                "roi_global_est": out["validation"].get("roi_global_est")
            }, ensure_ascii=False))

    elif args.phase == "RESULT":
        arr_path = base / "arrivee.json"
        try:
            if get_arrivee_geny and hasattr(get_arrivee_geny, "fetch_arrivee_officielle"):
                arr = get_arrivee_geny.fetch_arrivee_officielle(args.reunion, args.course)
                save_json(str(arr_path), arr)
                print(f"[runner_chain] Arrivée officielle enregistrée: {arr_path}")
            else:
                raise RuntimeError("get_arrivee_geny.fetch_arrivee_officielle indisponible")
        except Exception as e:
            print(f"[runner_chain] Avertissement: arrivée non récupérée: {e}", file=sys.stderr)

        try:
            analysis_path = base / "analysis_H5.json"
            roi_est_arg = ""
            if analysis_path.exists():
                ana = load_json(str(analysis_path)) or {}
                val_sp = (ana.get("validation") or {}).get("sp") or {}
                roi = val_sp.get("roi_est")
                if isinstance(roi, (int, float)):
                    roi_est_arg = f" --roi_estime {float(roi):.4f}"

            cmd = (
                f'python update_excel_with_results.py'
                f' --excel "{args.excel}"'
                f' --result "{arr_path}"'
                f' --tickets "<AUTOFILL>"'
                f' --mises {args.budget:.2f}'
                f' --gains <A_REMPLIR>{roi_est_arg}'
            )
            print(f"[runner_chain] MAJ Excel (commande exécutée) : {cmd}")
            subprocess.run(shlex.split(cmd), check=False)
        except Exception as e:
            print(f"[runner_chain] Avertissement: MAJ Excel non exécutée: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
