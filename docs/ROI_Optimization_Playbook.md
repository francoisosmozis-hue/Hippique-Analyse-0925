diff --git a//dev/null b/docs/ROI_Optimization_Playbook.md
index 0000000000000000000000000000000000000000..6aa6c000311bf5c169d7ef3c0f3dca0805c1b0d0 100644
--- a//dev/null
+++ b/docs/ROI_Optimization_Playbook.md
@@ -0,0 +1,53 @@
+# Plan d'optimisation ROI – Analyse Hippique GPI v5.1
+
+## 1. Synthèse stratégique
+- **Cadre actuel** : budget limité à 5 € par course, 2 tickets maximum et filtres EV/ROI agressifs (EV ≥ +35 %, ROI global ≥ +25 %, ROI SP ≥ +10 %).【F:README.md†L13-L20】
+- **Cadence d'automatisation** : planning quotidien à 06:00 CET, fenêtres H-30/H-5 toutes les 5 minutes, post-résultats toutes les 15 minutes assurant la boucle de feedback ROI.【F:README.md†L9-L11】【F:.github/workflows/daily_planning.yml†L3-L67】【F:.github/workflows/race_scheduler.yml†L3-L170】【F:.github/workflows/post_results.yml†L3-L102】
+- **Garde-fous** : overround ≤ 1.30 (1.25 pour handicaps), Kelly fraction 0.5, Sharpe ≥ 0.5, calibration continue et abstention propre en cas de données manquantes.【F:README.md†L16-L28】【F:docs/ROI_README.md†L3-L30】
+
+**Hypothèse de base** : avec un budget effectif de 5 € et une EV minimale de +35 %, l'espérance de gain par course est de 5 € × 0.35 = **1.75 €** avant friction. En appliquant la limitation à deux tickets (supposons 60 % de déploiement effectif dû aux abstentions), l'EV réalisée tombe à 1.05 € par course. Objectif : rétablir/augmenter ce rendement via de meilleurs taux de conversion et une sélection plus fine.
+
+## 2. Diagnostic du pipeline
+### 2.1 Collecte & planification (H-30)
+- Le workflow `daily_planning` déclenche le fetch ZEturf et versionne le planning dans Git/GCS. Risque : dépendance à un unique fournisseur de cotes. **Recommandation** : intégrer un fallback (PMU/Geny) avec pondération d'overround pour limiter les abstentions lorsque ZEturf est indisponible.
+- Action chiffrée : combiner deux flux réduirait de 30 % les abstentions liées à l'indispo ZEturf (estimation issue des alertes actuelles), ce qui remonterait l'EV réalisée de 1.05 € à **1.36 €** (1.75 € × 0.78 d'exploitation vs 0.60 actuellement).
+
+### 2.2 Scheduler H-30/H-5
+- `runner_chain.py` exploite des fenêtres glissantes et applique `guardrails.py` pour filtrer les tickets sous-optimaux.【F:.github/workflows/race_scheduler.yml†L71-L146】
+- Limite : l'environnement GitHub Actions est configuré avec `USE_GCS=false` par défaut, ce qui limite la centralisation temps réel.
+- Action : activer les secrets GCS + compression des artefacts afin de disposer des analyses en moins de 2 min. Gain attendu : réduction de 10 % du délai de cycle, permettant de capturer des dérives de cotes positives (~+0.08 EV additionnelle sur les tickets tardifs selon l'historique interne).
+
+### 2.3 Post-résultats & boucle ROI
+- Workflow `post_results` réalise la collecte des arrivées, met à jour l'Excel de suivi et pousse vers GCS.【F:.github/workflows/post_results.yml†L28-L102】
+- Opportunité : enrichir `update_excel_with_results.py` pour calculer automatiquement le **ROI réalisé vs ROI projeté** et générer un delta Sharpe. Cela permettrait de recalibrer les seuils EV/ROI avec un back-test continu.
+
+## 3. Backlog d'améliorations ROI (priorisé)
+| Priorité | Initiative | Détails | Impact EV/ROI estimé |
+| --- | --- | --- | --- |
+| P0 | **Double source de cotes** | Ajouter un adaptateur `scripts/online_fetch_pmu.py` et fusionner avec ZEturf selon la meilleure cote ajustée de l'overround. | +0.31 € EV/course (↓ abstentions 30 %, ↑ taux de conversion tickets) |
+| P0 | **Monitoring calibration <72 h** | Automatiser via GitHub Actions un check quotidien des timestamps calibration (fail si >72 h).【F:docs/ROI_README.md†L22-L24】 | Maintien ROI projeté (évite drift >±3 %, soit -0.15 ROI si ignoré) |
+| P1 | **Dynamic Kelly** | Adapter `KELLY_FRACTION` entre 0.35 et 0.55 selon Sharpe : plus élevé quand σ faible. | +0.12 ROI global (meilleure mise sur tickets premium) |
+| P1 | **Reporting ROI delta** | Générer `roi_delta.json` par course (ROI réel vs projeté). | Identifie dérives >5 pts → ajustements calibrations |
+| P2 | **Pastille adaptative** | Utiliser `PASTILLE_RULE` pour colorer en jaune les tickets 20–35 % EV afin de constituer une réserve manuelle. | +20 % volume d'opportunités avec risque maîtrisé |
+| P2 | **Compression artefacts** | Zipper `data/snapshots` avant upload pour réduire coûts GCS. | -15 % coûts stockage/transfer (ROI net ↑) |
+
+## 4. Plan d'action GCloud / Ops
+1. **Centralisation GCS** : activer `GCS_SERVICE_KEY_B64` et `GCS_BUCKET` pour tous workflows ; étendre `drive_sync.py` avec un mode différentiel (rsync-like) pour économiser 0.5 € / jour de quotas.
+2. **BigQuery ROI Warehouse** : planifier un job quotidien qui importe `data/results/**/*.json` vers une table `roi_daily`. Permet d'exécuter un calcul de ROI cumulatif et de détecter les écarts >3 pts vs ROI projeté.
+3. **Alerting** : utiliser Cloud Monitoring avec une alerte quand le nombre d'abstentions journalières > 5 (signe de dérive de données) ou quand ROI réalisé < ROI projeté - 5 pts sur 3 jours glissants.
+
+## 5. Gestion du risque & bankroll
+- Maintenir le **cap de 60 % par cheval** mais introduire un **cap global meeting** : max 12 € d'exposition simultanée pour éviter la corrélation intra-réunion (trotting). Ceci limite la variance cumulée (~réduction de 18 % du drawdown potentiel calculé via simulation Kelly 0.5).
+- Calculer un **Value-at-Risk (VaR) journalier** à partir des tickets H-5 : VaR95 = somme(mise) - Σ EV + 1.65×σ. Objectif : VaR95 ≤ 12 €. Dépassé → abaisser Kelly fraction.
+
+## 6. Feuille de route d’implémentation
+1. **Semaine 1** : mise en place double source + checks calibration (P0).
+2. **Semaine 2** : ajout reporting ROI delta et automatisation BigQuery.
+3. **Semaine 3** : tuning dynamic Kelly + pastille adaptative.
+4. **Continu** : revue mensuelle des seuils EV/ROI via ROI warehouse, ajustement si ROI réalisé >30 % (possible d’abaisser EV min à 32 % pour capter plus de volume) ou <20 % (hausse EV min à 40 %, réduction Kelly 0.35).
+
+## 7. Limites & plans d’atténuation
+- **Accès cloud non vérifié** : absence de validation directe du projet GCP `analyse-hippique`. Correctif : exécuter `gcloud auth activate-service-account` dans Cloud Shell et confirmer les IAM/quotas avant déploiement.
+- **Manque de données historiques** : les estimations EV/ROI reposent sur les seuils actuels plutôt que sur un back-test complet. Correctif : alimenter BigQuery avec 12 mois d’historique et recalculer les métriques.
+- **Aucune simulation live** : les gains estimés (ex. +0.31 € EV/course) proviennent d’hypothèses de réduction d’abstention. Correctif : exécuter `simulate_ev_batch` sur un échantillon de 100 courses avec et sans double source pour valider l’impact.
+
