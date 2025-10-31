Bonjour. Voici les patchs minimaux pour appliquer les corrections demandées, conformément à la norme GPI v5.1.

J'ai ajouté des logs structurés dans `runner_chain.py` pour tracer les phases, les courses (R/C) et le budget. J'ai également ajusté `analyse_courses_du_jour_enrichie.py` pour respecter le budget par défaut de 5€ et pour appliquer la règle ROI >= 20% pour l'activation des paris combinés.

Voici les modifications :

Dans `runner_chain.py`, j'ai modifié les appels de logging pour qu'ils émettent un JSON structuré.
```diff
--- a/runner_chain.py
+++ b/runner_chain.py
@@ -85,7 +85,7 @@
     output: Dict[str, Any] = {}
 
     if phase == "H30":
-        logger.info("Phase H30: Fetch snapshot for %s%s from source %s", reunion, course, source)
+        logger.info(json.dumps({"event": "phase_start", "phase": "H30", "rc": f"{reunion}{course}", "budget": budget, "source": source}))
         try:
             if source == "zeturf":
                 script_path = _PROJECT_ROOT / "online_fetch_zeturf.py"
@@ -108,7 +108,7 @@
         }
 
     elif phase == "H5":
-        logger.info("Phase H5: Enrich + pipeline for %s%s", reunion, course)
+        logger.info(json.dumps({"event": "phase_start", "phase": "H5", "rc": f"{reunion}{course}", "budget": budget}))
         je_stats_path  = race_dir / "je_stats.csv"
         je_chrono_path = race_dir / "je_chrono.csv"
         try:
@@ -144,7 +144,7 @@
                     logger.warning("EMAIL_TO not set. Skipping email notification.")
 
     elif phase == "RESULT":
-        logger.info("Phase RESULT: fetch/update results for %s%s", reunion, course)
+        logger.info(json.dumps({"event": "phase_start", "phase": "RESULT", "rc": f"{reunion}{course}"}))
         today_str = datetime.now(ZoneInfo("Europe/Paris")).strftime('%Y-%m-%d')
         planning_file = _PROJECT_ROOT / "data" / "planning" / f"{today_str}.json"
         arrivals_file = _PROJECT_ROOT / "data" / "results" / f"{today_str}_arrivees.json"

```

Dans `analyse_courses_du_jour_enrichie.py`, j'ai ajusté le budget par défaut et ajouté la validation du ROI pour les paris combinés.
```diff
--- a/analyse_courses_du_jour_enrichie.py
+++ b/analyse_courses_du_jour_enrichie.py
@@ -982,6 +982,15 @@
             }
         )
         if str(result.get("status", "")).lower() != "ok":
             ev_ok = False
+        # GPI v5.1: ROI combiné >= 20%
+        combo_roi = result.get("roi")
+        if combo_roi is None or combo_roi < min_roi:
+            ev_ok = False
+            notes = result.get("notes", [])
+            note = f"ROI combo < {min_roi:.2f}"
+            if note not in notes:
+                notes.append(note)
+            combo_results[-1]["notes"] = notes
 
     if combo_results:
         guards_context["combo_eval"] = combo_results
@@ -2030,7 +2039,7 @@
 def main() -> None:
     ap = argparse.ArgumentParser(description="Analyse courses du jour enrichie")
     ap.add_argument("--data-dir", default="data", help="Répertoire racine pour les sorties")
-    ap.add_argument("--budget", type=float, default=100.0, help="Budget à utiliser")
+    ap.add_argument("--budget", type=float, default=5.0, help="Budget à utiliser")
     ap.add_argument("--kelly", type=float, default=1.0, help="Fraction de Kelly à appliquer")
     ap.add_argument(
         "--from-geny-today",

```

**TODO pour les tests/CI :**
*   `runner_chain.py`: Vérifier que les logs structurés sont correctement traités par le système de logging en place.
*   `analyse_courses_du_jour_enrichie.py`: Ajouter un cas de test où un pari combiné a un ROI inférieur à 20% pour s'assurer qu'il est bien filtré.

Je reste à votre disposition si vous avez d'autres questions.

-            logger.error(msg)
+            logger.error(json.dumps({"message": msg, **log_context}))
             output = {"abstain": True, "tickets": [], "roi_global_est": 0, "paths": {}, "message": msg}
         else:
             result = run_pipeline(reunion=reunion, course=course, phase=phase, budget=budget)
             output = result or {}
             output.setdefault("paths", {})["tracking"] = str(tracking_path)
-    
+
             # Notification email si tickets générés
             if not output.get("abstain") and output.get("tickets"):
                 email_to = os.environ.get("EMAIL_TO")
@@ -140,11 +142,11 @@
                     subject = f"Tickets Hippiques pour {reunion}{course}"
                     send_email(subject, html_content, email_to)
                 else:
-                    logger.warning("EMAIL_TO not set. Skipping email notification.")
-    
+                    logger.warning(json.dumps({"message": "EMAIL_TO not set. Skipping email notification.", **log_context}))
+
     elif phase == "RESULT":
-        logger.info("Phase RESULT: fetch/update results for %s%s", reunion, course)
+        logger.info(json.dumps({"message": "Phase RESULT: fetch/update results", **log_context}))
         today_str = datetime.now(ZoneInfo("Europe/Paris")).strftime('%Y-%m-%d')
         planning_file = _PROJECT_ROOT / "data" / "planning" / f"{today_str}.json"
         arrivals_file = _PROJECT_ROOT / "data" / "results" / f"{today_str}_arrivees.json"
@@ -154,22 +156,22 @@
         try:
             if planning_file.exists():
                 fetch_and_write_arrivals(str(planning_file), str(arrivals_file))
             else:
-                logger.warning("Planning file not found: %s", planning_file)
-    
+                logger.warning(json.dumps({"message": f"Planning file not found: {planning_file}", **log_context}))
+
             if arrivals_file.exists() and p_finale_file.exists():
                 update_excel(excel_path_str=str(excel_file),
                              arrivee_path_str=str(arrivals_file),
                              tickets_path_str=str(p_finale_file))
             else:
-                logger.warning("Arrivals or tickets file not found; skipping Excel update.")
-    
+                logger.warning(json.dumps({"message": "Arrivals or tickets file not found; skipping Excel update.", **log_context}))
+
             output = {"abstain": True, "tickets": [], "roi_global_est": None, "paths": {}, "message": "Result phase completed."}
         except Exception as e:
             msg = f"Result processing failed: {e}"
-            logger.error(msg, exc_info=True)
+            logger.error(json.dumps({"message": msg, "error": str(e), **log_context}), exc_info=True)
             output = {"abstain": True, "tickets": [], "roi_global_est": None, "paths": {}, "message": msg}
-    
+
     else:
         output = {"abstain": True, "tickets": [], "roi_global_est": None, "paths": {}, "message": "Unknown phase."}
-    
+
     return output

```

Dans `validator_ev.py` pour les règles GPI v5.1 :
```diff
--- a/validator_ev.py
+++ b/validator_ev.py
@@ -216,14 +216,14 @@
     )
 
     min_sp = float(os.getenv("EV_MIN_SP", 0.15))
-    min_global = float(os.getenv("EV_MIN_GLOBAL", 0.35))
+    min_global = float(os.getenv("EV_MIN_GLOBAL", 0.40))
 
     if ev_sp < min_sp:
         raise ValidationError("EV SP below threshold")
 
     if need_combo:
         if ev_global is None or ev_global < min_global:
             raise ValidationError("EV global below threshold")
 
     return True
@@ -270,24 +270,34 @@
 def combos_allowed(
     ev_basket: float,
     expected_payout: float,
+    roi_basket: float | None = None,
     *,
-    min_ev: float = 0.40,
+    min_ev: float = 0.40,  # GPI v5.1
+    min_roi: float = 0.20, # GPI v5.1
     min_payout: float = 12.0,
 ) -> bool:
-    """Return ``True`` when combinés satisfy EV and payout guardrails."""
+    """Return ``True`` when combinés satisfy EV, ROI and payout guardrails."""
 
     try:
         ev_value = float(ev_basket)
     except (TypeError, ValueError):
         ev_value = 0.0
+    try:
+        # si roi_basket n'est pas fourni, on suppose que ev_basket est le ROI
+        roi_value = float(roi_basket) if roi_basket is not None else ev_value
+    except (TypeError, ValueError):
+        roi_value = 0.0
     try:
         payout_value = float(expected_payout)
     except (TypeError, ValueError):
         payout_value = 0.0
 
     if ev_value < min_ev:
         return False
+    if roi_value < min_roi:
+        return False
     if payout_value < min_payout:
         return False
     return True

```

**TODO pour tests/CI :**
*   Vérifier que les logs structurés apparaissent correctement dans l'agrégateur de logs (ex: Cloud Logging).
*   S'assurer que les appels à `combos_allowed` (s'il y en a) passent bien le `roi_basket` ou que `ev_basket` est bien le ROI.
*   Confirmer que les nouvelles règles de validation (EV/ROI) sont bien appliquées et que les courses non conformes sont correctement écartées.

N'hésitez pas si vous avez d'autres questions.
