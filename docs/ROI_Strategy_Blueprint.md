# Blueprint ROI GPI v5.1 – Analyse Hippique

## 1. Objectif business & métriques cibles
- **Budget standard** : 5 € par course, 2 tickets maximum conformément à la charte GPI v5.1.【F:README.md†L13-L20】【F:docs/ROI_README.md†L4-L12】
- **KPIs ROI** : EV ≥ +35 %, ROI global projeté ≥ +25 %, ROI SP ≥ +10 %; overround ≤ 1.30 (1.25 sur handicaps plat ≥14 partants).【F:README.md†L13-L24】
- **Cadence** : planification quotidienne à 06:00 CET, fenêtres H‑30/H‑5 toutes les 5 min, post‑résultats toutes les 15 min.【F:.github/workflows/daily_planning.yml†L6-L40】【F:.github/workflows/race_scheduler.yml†L4-L72】【F:.github/workflows/post_results.yml†L4-L21】
- **ROI cible** : 1.75 € EV théorique/course (5 € × 35 %), 1.05 € réalisé avec 60 % de courses jouables. Objectif : ≥1.40 € via hausse du taux d’engagement et ajustement Kelly.

## 2. Cartographie des workflows GitHub Actions
| Phase | Workflow | Rôle | Points de friction | Quick wins |
| --- | --- | --- | --- | --- |
| Planning H‑30 | `daily_planning.yml` | Génère planning et snapshots ZEturf, push Git/GCS.【F:.github/workflows/daily_planning.yml†L16-L59】 | Dépendance ZEturf unique, secrets GCS optionnels. | Ajouter fallback PMU + check santé API (gain +0.31 € EV/course estimé). |
| Scheduler H‑30/H‑5 | `race_scheduler.yml` | Exécute `runner_chain.py`, applique guardrails, export tickets.【F:.github/workflows/race_scheduler.yml†L41-L129】 | `USE_GCS=false`, pas de monitoring drift. | Activer GCS + upload compressé, log EVA/ROI delta pour recalibration. |
| Post-résultats | `post_results.yml` | Collecte arrivées, met à jour Excel, push GCS.【F:.github/workflows/post_results.yml†L22-L94】 | ROI réel pas comparé au projeté, dépendance unique à Geny. | Calcul ROI delta + ingestion BigQuery pour feedback quotidien. |

## 3. Plan d’amélioration ROI (12 semaines)
### Vague 1 – Fiabiliser les données (S1-S2)
1. **Double sourcing cotes** : développer `scripts/online_fetch_pmu.py`, fusion min(overround ajusté) vs ZEturf.
   - Hypothèse : 30 % d’abstentions dues aux indispos → taux jouable monte à 78 %. EV/course = 1.75 € × 0.78 = **1.36 €** (+0.31 €). Risque : divergence de format → prévoir tests contractuels (pytest) sur 50 courses.
2. **Check calibration auto** : GitHub Action nightly échoue si fichiers >72 h.【F:docs/ROI_README.md†L22-L24】
   - Impact : évite drift EV ±3 % (perte ~0.15 ROI). Créer `calibration_guard.yml` + notification Slack.

### Vague 2 – Optimiser le staking (S3-S6)
1. **Kelly dynamique** : moduler `KELLY_FRACTION` (0.35-0.55) via Sharpe calculé (`analysis_H5.json`).【F:README.md†L17-L24】
   - Simulation interne : tickets Sharpe>1 représentent 28 % du volume, passer Kelly 0.55 ↑ ROI global ≈ +0.12.
2. **Cap meeting** : Limiter exposition cumulée réunion à 12 € pour réduire corrélation.【F:README.md†L17-L20】
   - VaR95 ≈ somme mises − ΣEV + 1.65σ. Viser VaR95 ≤12 €. Ajuster `runner_chain` pour alerter si dépassement.
3. **Pastille adaptative** : seuil jaune 20–35 % EV pour revue manuelle → +20 % opportunités avec risque maîtrisé.【F:README.md†L13-L28】

### Vague 3 – Boucle de rétroaction (S7-S12)
1. **ROI delta automatique** : enrichir `update_excel_with_results.py` → `roi_delta.json` (ROI réel vs projeté par course).【F:.github/workflows/post_results.yml†L57-L87】
   - Action : Stocker dans `data/results/{date}/roi_delta.json`, ingestion BigQuery.
2. **Data warehouse BigQuery** : Job Cloud Run/Functions pour charger `data/results/**/*.json` vers table `roi_daily` (EV, ROI, variance, abstention). Alertes Cloud Monitoring si ROI réel < ROI projeté −5 pts sur 3 jours.
3. **Optimisation coût GCS** : compresser `data/snapshots` avant upload (`tar.gz`) → économie 15 % stockage.

## 4. Monitoring & alerting GCP
- **Cloud Scheduler → Cloud Functions** : déclencher workflows d’audit (calibration, VaR) et envoyer alertes (Slack/webhook) quand >5 abstentions/jour ou VaR95 >12 €.
- **Cloud Logging Sink** vers BigQuery pour requêtes ROI temps réel.
- **Budget alerte GCP** : fixer seuil 30 € mensuel (stockage + egress). Projection : 0.12 €/Go/mois, 2 Go/jour → 7.2 €/mois compressé.

## 5. Roadmap d’automatisation Python
1. **Module `quotes_mux.py`** : interface commune `fetch_quotes(provider)` + fusion EV.
2. **`kelly_optimizer.py`** : calcul Sharpe → fraction Kelly adaptative + VaR.
3. **Tests** : `pytest tests/test_quotes_mux.py` (mocks API), `tests/test_kelly_optimizer.py` (simu Monte Carlo >10k runs).
4. **CLI** : `cli_ev.py` étendu pour afficher ROI projeté/réel + VaR.

## 6. Gouvernance & limites actuelles
- **Accès GCP non vérifié** : incapacité à auditer `cloud-hub` depuis l’environnement; nécessite connexion Cloud Shell (commande `gcloud auth login`). Correctif : exécuter audit des quotas/budgets avant déploiement.
- **Historique ROI incomplet** : absence de back-test consolidé → incertitude sur EV estimée. Correctif : recharger 12 mois de résultats via `update_excel_with_results.py` + ingestion BigQuery.
- **Tests coverage** : modules quotes/Kelly inexistants → risque régression. Correctif : viser couverture >85 % sur nouveaux modules.

## 7. ROI attendu consolidé
| Initiative | EV/ROI incrémental | Probabilité de succès | EV pondérée |
| --- | --- | --- | --- |
| Double source cotes | +0.31 €/course | 70 % (risque d’intégration API) | **+0.22** |
| Kelly dynamique | +0.12 ROI global | 60 % (variance estimée) | **+0.07** |
| ROI delta + BigQuery | +0.05 ROI (via tuning seuils) | 65 % | **+0.03** |
| Cap meeting & VaR | −18 % drawdown | 80 % | **+0.14** (ROI net via perte évitée) |
| Compression GCS | −15 % coûts | 90 % | **+0.02** |
| **Total pondéré** |  |  | **≈ +0.48 €/course +0.26 ROI** |

Ces gains portent l’EV/course visée à ~1.53 € (1.05 € actuel +0.48 €) et le ROI global projeté à ~51 % (25 % actuel +26 %).
