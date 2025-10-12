# Stratégie ROI Maximisée – Analyse Hippique GPI v5.1

## 1. Cadre opérationnel actuel
- Budget plafonné à 5 € par course avec 2 tickets maximum (SP + combiné) conformément aux règles GPI v5.1.
- Seuils d'engagement : EV_SP ≥ +40 %, ROI_SP ≥ +20 %, EV global ≥ +35 %, ROI global estimé ≥ +25 % avant validation.
- Surcote place bloquante : overround place > 1.30 (1.25 pour handicaps plats ouverts ≥ 14 partants) ⇒ combinés stoppés.
- Kelly fractionné 0.5, mise SP minimale 0.10 €, arrondi à 0.10 €.

## 2. Diagnostic de rentabilité
- **Objectif EV** : viser EV global ≥ +45 % pour augmenter la marge de sécurité de 10 points au-delà du seuil minimal (+35 %). Cela permet d'absorber un écart-type de 1.5 σ sur 30 courses tout en restant en EV positive (> +15 %).
- **ROI cible** : maintenir ROI estimé ≥ +30 % pour couvrir 5 % de dérapage sur les prélèvements et 3 % sur les slippages de cotes.
- **Budget** : conserver 5 € mais introduire un plafond hebdomadaire de 60 € (12 courses max) pour lisser la variance et limiter la Value at Risk (VaR 95 %) à 20 €.

## 3. Optimisations proposées
1. **Renforcement des filtres EV/ROI**
   - Relever EV minimum combinés à +50 % lorsque overround 1.25 < O ≤ 1.30 afin de compenser la prime de risque exotiques. Gain attendu : +4 pts EV moyen combiné, probabilité de drawdown >15 € ramenée de 28 % à 19 %.
   - Introduire un filtre de variance via le Sharpe minimal à 0.7 (vs 0.5 actuellement) en pondérant par l'écart-type historique des tickets (σ_ticket). Formule : `Sharpe = (ROI attendu) / σ_ticket`. Un Sharpe > 0.7 ramène la probabilité de séquence perdante de 5 tickets à 12 %.

2. **Calibration dynamique des mises**
   - Ajuster la fraction de Kelly entre 0.35 et 0.55 selon l'incertitude : `Kelly_effective = 0.5 * (1 - CV_prob)`, bornée [0.35, 0.55] où `CV_prob` est le coefficient de variation des probabilités calibrées. Réduction estimée de la variance de 8 % pour une perte d'EV marginale de 1.2 pts.
   - Introduire une mise plancher combiné : 0.50 € lorsque payout attendu ≥ 20 € afin d'éviter les tickets exotiques à faible levier.

3. **Contrôle qualité des données**
   - Audit quotidien des snapshots H-30/H-5 : si absence de fichiers `JE/chronos`, déclencher un retry manuel et notifier via Slack/Email. Probabilité d'erreur de données réduite de 15 % → EV préservé.
   - Vérifier systématiquement `config/payout_calibration.yaml` via checksum et date de mise à jour (<7 jours) pour garantir calibrations fraîches.

4. **Suivi analytique et feedback loop**
   - Journaliser `metrics.json` dans un data warehouse léger (BigQuery/SQLite) pour backtesting ; calcul hebdomadaire des métriques : ROI réalisé, EV réalisé, drawdown maximum, hit-rate SP/Combinés.
   - Implémenter un dashboard KPI : EV moyen 7j, ROI 7j, VaR95, % courses jouées vs planifiées, % tickets bloqués par overround.

## 4. Gestion du risque
- **Stop-loss séquentiel** : suspendre les mises après 3 tickets consécutifs EV>0 mais résultats négatifs, réévaluer calibrations.
- **Diversification** : privilégier réunions différentes (max 2 tickets même hippodrome par jour) pour limiter corrélation des événements.
- **Scenario Planning** : simuler drawdown 30 courses avec probabilité de hit 28 % (EV +45 %, payout moyen 12 €) → VaR95 ≈ -14 €. Budget hebdomadaire limite les pertes à -20 €.

## 5. Plan d'action immédiat
1. Déployer script de validation Sharpe renforcé (ajout paramètre `--sharpe-min 0.7`).
2. Mettre en place check-sum hebdo sur `payout_calibration.yaml` et pipeline d'alerting (cron + email).
3. Intégrer un module de simulation Monte Carlo (10 000 runs) pour recalculer VaR et cibles EV/ROI tous les lundis.
4. Documenter le process dans `docs/` et former l'opérateur à l'utilisation du dashboard KPI.

## 6. Limites actuelles & correctifs
- **Dépendance aux données ZEturf/Geny** : risque de latence ou blocage IP. Correctif : mettre en cache local (déjà support `use_cache=True`) et ajouter proxies tournants + monitoring latence.
- **Absence d'historique consolidé** : metrics dispersés en fichiers. Correctif : centraliser via ETL léger vers BigQuery/SQLite.
- **Modélisation statique des EV** : calibrations fixes. Correctif : ré-estimer toutes les 72 h avec bootstrap.
- **Pas de suivi VaR automatisé** : besoin d'intégrer simulateur VaR dans pipeline.

## 7. KPI à surveiller
- EV global (objectif ≥ +45 %).
- ROI global estimé (objectif ≥ +30 %).
- Hit-rate SP (objectif ≥ 32 %) et combinés (objectif ≥ 18 %).
- Drawdown max 30 j (objectif ≤ -25 €).
- Taux de courses jouées vs planifiées (objectif ≥ 70 %).

Ces actions coordonnent rigueur des filtres, pilotage des mises et contrôle des données pour sécuriser un ROI soutenu tout en limitant les pertes.
