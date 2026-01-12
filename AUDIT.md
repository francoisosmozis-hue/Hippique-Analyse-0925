# Audit Rapide - hippique-orchestrator

Ce document résume les conclusions de l'audit de code (Phase 1). Les problèmes sont classés par ordre d'impact décroissant.

### Synthèse
Le système souffre de deux problèmes critiques qui empêchent le fonctionnement nominal : une authentification OIDC cassée pour les tâches asynchrones et une logique métier de "drift" non implémentée. Un problème de scraping en amont est la cause la plus probable de l'absence de données (`total_races=0`). Le reste du code semble globalement robuste mais pourrait être simplifié.

### Causes Racines Probables (par ordre d'impact)

| Impact | Problème | Fichiers Clés | Cause Racine |
| :--- | :--- | :--- | :--- |
| **CRITIQUE** | **Auth Cloud Tasks (OIDC) échoue** | `service.py`, `auth.py` | Incohérence de l'audience : `https://host` à la création vs `https://host/` (avec slash final) à la validation. La validation OIDC échoue, bloquant toute analyse asynchrone (H-30, H-5). |
| **CRITIQUE** | **Logique de Drift (H-30/H-5) inactive** | `analysis_pipeline.py`, `pipeline_run.py` | Le snapshot H-30 n'est jamais rechargé. Un dictionnaire vide (`{}`) est passé au moteur d'analyse (`pipeline_run.py`), qui est pourtant prêt à l'utiliser. Le statut de drift est donc toujours "Stable". |
| **ÉLEVÉ** | **Aucune course affichée (`total_races=0`)** | `plan.py`, `scrapers/boturfers.py` | L'endpoint API (`/api/pronostics`) est fonctionnel, mais il dépend du scraping du programme du jour (`plan.build_plan_async`). Si ce scraping échoue ou ne trouve rien, l'API renvoie 0 course. Le problème est en amont. |
| **MOYEN** | **Dépendances externes multiples** | `scrapers/boturfers.py`, `fetch_je_stats.py` | Le système dépend de deux sites externes (`boturfers.fr`, `geny.com`), ce qui le rend fragile et potentiellement lent. `fetch_je_stats.py` est particulièrement lent (plusieurs requêtes séquentielles par course). |
| **FAIBLE** | **Code mort et complexité inutile** | `api/tasks.py`, `fetch_je_stats.py` | Le fichier `api/tasks.py` n'est pas utilisé. La fonction `enrich_from_snapshot` dans `fetch_je_stats.py` qui s'appelle elle-même en sous-processus est du code mort. |

### Schéma du chemin de données
1.  **Planification (`/schedule`)**: `service.py` appelle `plan.py` -> `scrapers/boturfers.py` pour lister les courses du jour.
2.  **Création des tâches**: `service.py` appelle `scheduler.py` pour créer des tâches Cloud Tasks (une pour H-30, une pour H-5) pour chaque course. **L'audience OIDC est mal configurée ici.**
3.  **Exécution de la tâche (`/tasks/run-phase`)**: Cloud Tasks appelle ce endpoint. **L'authentification OIDC échoue ici.**
4.  **Pipeline d'analyse**: Si l'auth passait, `service.py` appellerait `analysis_pipeline.run_analysis_for_phase`.
    a.  **Snapshot**: Le scraping est ré-exécuté et le résultat est sauvé sur GCS (ex: `.../R1C1/snapshots/xxx_H-5.json`).
    b.  **Enrichissement JE**: `fetch_je_stats.py` est appelé, scrape `geny.com` et sauve `stats_je.json` sur GCS.
    c.  **Moteur GPI**: `pipeline_run.py` est appelé. **Il ne reçoit pas les données H-30.**
5.  **Persistance**: Le résultat de l'analyse est écrit dans un document Firestore (ex: `YYYY-MM-DD_R1C1`).
6.  **Lecture (UI)**: `GET /api/pronostics` lit les documents Firestore et le plan du jour pour construire la réponse JSON.

### Dépendances fantômes
- La seule dépendance fantôme majeure identifiée est l'incohérence OIDC qui est une erreur de configuration logique plutôt qu'un module manquant.
- Les variables d'environnement semblent correctement gérées via `config.py`.
- Le code mort (`api/tasks.py`, `enrich_from_snapshot`) devrait être supprimé pour éviter toute confusion future.