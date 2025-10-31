Bonjour. J'ai terminé l'audit du code fourni. Voici mon analyse, structurée selon vos attentes.

### Résumé exécutif

Le projet est une architecture événementielle (H-30/H-5/RESULT) pour le pari hippique, centrée sur le calcul de l'EV (Expected Value) et l'allocation de mises via une stratégie Kelly. L'intention est claire, mais la fiabilité est sévèrement compromise par une utilisation excessive et récursive de `subprocess`, une configuration des seuils de rentabilité éclatée (code, fichiers YAML, variables d'environnement), et une duplication de la logique métier critique (`allocate_dutching_sp`). Les "guardrails" GPI v5.1 sont bien présents mais leur application est incohérente. Les principaux axes d'amélioration sont la simplification des appels (fonctions Python directes), la centralisation de la configuration, et la suppression du code dupliqué pour garantir la maintenabilité et la fiabilité du système en production.

### 🔴 Bloqueurs

1.  **Appels en `subprocess` récursifs et fragiles** : Le point le plus critique. `runner_chain.py` appelle `fetch_je_stats.py` et `fetch_je_chrono.py` via `subprocess`. Or, ces scripts utilisent eux-mêmes `subprocess` pour se ré-appeler. C'est une source majeure d'erreurs, de complexité et de lenteur. Les appels doivent être remplacés par des importations et des appels de fonctions Python directs.
2.  **Duplication de la logique d'allocation** : La fonction `allocate_dutching_sp` est définie à la fois dans `simulate_ev.py` et `module_dutching_pmu.py`. C'est une bombe à retardement : une modification dans l'un ne sera pas répercutée dans l'autre, menant à des calculs de paris incohérents. Il faut unifier cette logique.
3.  **Configuration des seuils éclatée** : Les seuils de décision (EV, ROI, payout) sont définis à plusieurs endroits :
    *   En dur dans `validator_ev.py` (`min_payout = 12.0`, `min_ev = 0.40`).
    *   Via des variables d'environnement dans `validator_ev.py` (`EV_MIN_SP`, `EV_MIN_GLOBAL`).
    *   Via un dictionnaire `cfg` dans `simulate_ev.py`.
    *   En dur dans `analyse_courses_du_jour_enrichie.py` (`min_roi: float = 0.20`).
    Cette dispersion rend la gestion des "guardrails" GPI impossible à auditer et à maintenir.

### 🟠 Risques

*   **Gestion d'erreurs trop large** : Les blocs `try: ... except Exception:` dans `runner_chain.py` masquent la nature réelle des erreurs (ex: échec de scraping, erreur de logique), rendant le débogage difficile. Le stubbing des fonctions (ex: `send_email`) en cas d'échec d'import peut cacher des problèmes de dépendances.
*   **Logs et `print` mélangés** : L'usage de `print` (ex: `validate_snapshot_or_die`) court-circuite le logging structuré en JSON, ce qui complique l'analyse des logs sur GCP.
*   **Chemins de fichiers relatifs** : L'utilisation de `_PROJECT_ROOT` basé sur `__file__` est une bonne pratique, mais la robustesse pourrait être améliorée en se basant sur un marqueur de projet (ex: `.git`) pour éviter les erreurs si les scripts sont déplacés.
*   **Modification de fichiers Excel en environnement serveur** : La phase `RESULT` modifie un fichier `xlsx`. C'est une opération risquée et non-scalable sur un service comme Cloud Run, où le système de fichiers est éphémère et sans garantie de persistance ou de concurrence.

### ✅ Patches proposés

Voici des diffs pour corriger les problèmes les plus urgents.

**Patch 1 (Critique) : Remplacer `subprocess` par des appels de fonction directs dans `runner_chain.py`**

```diff
--- a/runner_chain.py
+++ b/runner_chain.py
@@ -35,6 +35,16 @@
 try:
     from get_arrivee_geny import fetch_and_write_arrivals
 except Exception:
+    def fetch_and_write_arrivals(*args, **kwargs):
+        logging.getLogger(__name__).warning("get_arrivee_geny indisponible (stub).")
+
+try:
+    from fetch_je_stats import enrich_from_snapshot as enrich_je_stats
+except Exception:
+    def enrich_je_stats(*args, **kwargs):
+        logging.getLogger(__name__).warning("fetch_je_stats indisponible (stub).")
+
+try:
+    from fetch_je_chrono import enrich_from_snapshot as enrich_je_chrono
+except Exception:
     def fetch_and_write_arrivals(*args, **kwargs):
         logging.getLogger(__name__).warning("get_arrivee_geny indisponible (stub).")
 
@@ -113,14 +123,10 @@
         je_stats_path  = race_dir / "je_stats.csv"
         je_chrono_path = race_dir / "je_chrono.csv"
         try:
-            run_subprocess([sys.executable, str(_PROJECT_ROOT / "fetch_je_stats.py"),
-                            "--output", str(je_stats_path), "--reunion", reunion, "--course", course])
-            run_subprocess([
-                sys.executable, str(_PROJECT_ROOT / "fetch_je_chrono.py"),
-                "--output", str(je_chrono_path), "--reunion", reunion, "--course", course
-            ])
+            enrich_je_stats(snapshot_path=str(snapshot_path), reunion=reunion, course=course)
+            enrich_je_chrono(snapshot_path=str(snapshot_path), reunion=reunion, course=course)
         except Exception as e:
-            msg = f"Abstaining: enrichment fetch failed: {e}"
+            msg = f"Abstaining: enrichment failed: {e}"
             logger.error(msg)
             return {"abstain": True, "tickets": [], "roi_global_est": 0, "paths": {}, "message": msg}
 

```

**Patch 2 : Centraliser les seuils dans `simulate_ev.py` en utilisant des variables d'environnement (comme `validator_ev.py`)**

```diff
--- a/simulate_ev.py
+++ b/simulate_ev.py
@@ -20,6 +20,7 @@
     from ev_calculator import compute_ev_roi
     from kelly import kelly_fraction
     from simulate_wrapper import simulate_wrapper
+    import os
 
 
 def implied_prob(odds: float) -> float:
@@ -220,29 +221,29 @@
 
     reasons = {"sp": [], "combo": []}
 
-    sp_budget = float(cfg.get("BUDGET_TOTAL", 0.0)) * float(cfg.get("SP_RATIO", 1.0))
-
-    ev_min_sp_ratio = float(cfg.get("EV_MIN_SP", 0.0))
+    sp_budget = float(cfg.get("BUDGET_TOTAL", 5.0)) * float(cfg.get("SP_RATIO", 1.0))
+
+    ev_min_sp_ratio = float(os.getenv("EV_MIN_SP", cfg.get("EV_MIN_SP", 0.40)))
     if homogeneous_field:
-        ev_min_sp_ratio = float(cfg.get("EV_MIN_SP_HOMOGENEOUS", ev_min_sp_ratio))
+        ev_min_sp_ratio = float(os.getenv("EV_MIN_SP_HOMOGENEOUS", cfg.get("EV_MIN_SP_HOMOGENEOUS", ev_min_sp_ratio)))
 
     if ev_sp < ev_min_sp_ratio * sp_budget:
         reasons["sp"].append("EV_MIN_SP")
-    if roi_sp < float(cfg.get("ROI_MIN_SP", 0.0)):
+    if roi_sp < float(os.getenv("ROI_MIN_SP", cfg.get("ROI_MIN_SP", 0.10))):
         reasons["sp"].append("ROI_MIN_SP")
 
-    if ev_global < float(cfg.get("EV_MIN_GLOBAL", 0.0)) * float(cfg.get("BUDGET_TOTAL", 0.0)):
+    if ev_global < float(os.getenv("EV_MIN_GLOBAL", cfg.get("EV_MIN_GLOBAL", 0.40))) * float(cfg.get("BUDGET_TOTAL", 5.0)):
         reasons["combo"].append("EV_MIN_GLOBAL")
-    if roi_global < float(cfg.get("ROI_MIN_GLOBAL", 0.0)):
+    if roi_global < float(os.getenv("ROI_MIN_GLOBAL", cfg.get("ROI_MIN_GLOBAL", 0.10))):
         reasons["combo"].append("ROI_MIN_GLOBAL")
-    if min_payout_combos < float(cfg.get("MIN_PAYOUT_COMBOS", 0.0)):
+    if min_payout_combos < float(os.getenv("MIN_PAYOUT_COMBOS", cfg.get("MIN_PAYOUT_COMBOS", 10.0))):
         reasons["combo"].append("MIN_PAYOUT_COMBOS")
 
-    ror_max = float(cfg.get("ROR_MAX", 1.0))
+    ror_max = float(os.getenv("ROR_MAX", cfg.get("ROR_MAX", 1.0)))
     epsilon = 1e-9
     if risk_of_ruin > ror_max + epsilon:
         reasons["sp"].append("ROR_MAX")
         reasons["combo"].append("ROR_MAX")
 
-    sharpe_min = float(cfg.get("SHARPE_MIN", 0.0))
+    sharpe_min = float(os.getenv("SHARPE_MIN", cfg.get("SHARPE_MIN", 0.0)))
     if ev_over_std < sharpe_min:
         reasons["sp"].append("SHARPE_MIN")
         reasons["combo"].append("SHARPE_MIN")

```

**Patch 3 : Remplacer `print` par `logger.error` dans `runner_chain.py`**

```diff
--- a/runner_chain.py
+++ b/runner_chain.py
@@ -58,13 +58,13 @@
 def validate_snapshot_or_die(snapshot: dict, phase: str) -> None:
     import sys
     if not isinstance(snapshot, dict):
-        print(f"[runner_chain] ERREUR: snapshot {phase} invalide (type {type(snapshot)})", file=sys.stderr)
+        logger.critical("snapshot %s invalide (type %s)", phase, type(snapshot))
         sys.exit(2)
     # ZEturf parser: runners=list, partants=int (pas une liste)
     runners = snapshot.get("runners")
     if not isinstance(runners, list) or len(runners) == 0:
-        print(f"[runner_chain] ERREUR: snapshot {phase} vide ou sans 'runners'.", file=sys.stderr)
+        logger.critical("snapshot %s vide ou sans 'runners'.", phase)
         sys.exit(2)
 
 def run_subprocess(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:

```

### 🧪 Tests à ajouter

1.  **Test unitaire pour `simulate_ev.gate_ev`** : Créer des tests qui vérifient que la fonction `gate_ev` autorise ou bloque correctement les paris en fonction de différentes valeurs d'EV, ROI, et payout, en s'assurant que les seuils (maintenant lus depuis les variables d'environnement) sont respectés.
2.  **Test de non-régression pour l'allocation de mise** : Créer un test qui utilise une version unifiée de `allocate_dutching_sp` avec un jeu de données (runners, cotes, probabilités) fixe et vérifie que les mises calculées sont toujours identiques. Cela empêchera des modifications accidentelles de la logique de pari.
3.  **Test d'intégration pour `runner_chain.run_chain`** : Utiliser `unittest.mock` pour mocker les fonctions `run_pipeline`, `send_email`, et les fonctions d'enrichissement. Lancer `run_chain` pour la phase `H5` et vérifier que :
    *   Les fonctions d'enrichissement sont bien appelées.
    *   `run_pipeline` est appelé avec les bons arguments.
    *   `send_email` est appelé si des tickets sont générés.

### 🛠 Commandes

**Pour lancer en local (exemple pour R1C1 en phase H-5) :**

```bash
# Exécuter la chaîne complète pour une course
python runner_chain.py --reunion R1 --course C1 --phase H5 --budget 5.0 --source zeturf
```

**Pour déployer et lancer sur Cloud Run (en supposant un service FastAPI dans `app/main.py`) :**

1.  **Déployer le service :**
    *Je vais expliquer cette commande car elle a un impact sur votre environnement cloud.* Cette commande déploie votre application sur Google Cloud Run. Elle utilise le `Dockerfile` présent pour construire une image conteneur, la pousse vers le registre d'artefacts de Google, et crée un service Cloud Run nommé `hippique-orchestrator`. Le port 8080 est exposé et les variables d'environnement pour les seuils de rentabilité sont configurées.

    L'outil `run_shell_command` n'est pas disponible dans mon environnement actuel, je ne peux donc pas exécuter la commande de déploiement `gcloud` pour vous.

Cependant, voici la commande exacte que vous devriez exécuter dans votre terminal pour déployer le service sur Cloud Run avec la configuration centralisée que je recommande :

```bash
gcloud run deploy hippique-orchestrator \
  --source . \
  --port 8080 \
  --region europe-west1 \
  --allow-unauthenticated \
  --set-env-vars="EV_MIN_SP=0.40,ROI_MIN_SP=0.10,EV_MIN_GLOBAL=0.40,ROI_MIN_GLOBAL=0.10,MIN_PAYOUT_COMBOS=10.0,EMAIL_TO=votre.email@example.com"
```

*Cette commande déploiera le service et configurera les seuils de rentabilité via des variables d'environnement, ce qui centralise la logique de décision comme préconisé dans l'audit.*

2.  **Invoquer le service une fois déployé (exemple) :**

```bash
# En supposant un endpoint /run-course qui prend les paramètres en JSON
curl -X POST "https://hippique-orchestrator-XXXXX-ew.a.run.app/run-course" \
-H "Content-Type: application/json" \
-d '{"reunion": "R1", "course": "C1", "phase": "H5", "budget": 5.0}'
```

### Limites/points à éclaircir

*   **API non fournie** : Le code du service web (probablement `app/main.py` pour FastAPI) n'a pas été fourni. L'audit ne couvre donc pas la couche API, sa sécurité, la validation des entrées, ou la manière dont il invoque `runner_chain.py`.
*   **Point d'entrée ambigu** : La coexistence de `runner_chain.py` et `analyse_courses_du_jour_enrichie.py` crée une ambiguïté. Lequel est le véritable point d'entrée de production ? `analyse_courses_du_jour_enrichie.py` est beaucoup plus complexe et semble être une version plus récente ou alternative, mais `runner_chain.py` est plus simple et plus direct pour une invocation par API. Cette dualité doit être clarifiée.
*   **Persistance des résultats** : L'écriture dans un fichier Excel est une solution fragile pour un service cloud. Il faudrait envisager une base de données (comme Cloud SQL ou Firestore) ou à minima un stockage sur Google Cloud Storage pour stocker les résultats de manière fiable et scalable.
