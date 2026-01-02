# Matrice de Tests - Hippique Orchestrator

Ce document détaille la stratégie de test, les risques identifiés et les actions de renforcement de la qualité pour le projet.

| Composant | Risque | Tests Existants | Tests Manquants | KPI Cible | Effort | Priorité |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`stats_provider.py`** | <span style="color:red">**Élevé**</span> | Parsing de base, résolution d'ID, cas d'erreurs simples. | Tests sur fixtures HTML invalides/malformées, cas limites de parsing (valeurs manquantes, formats inattendus), gestion des erreurs réseau (timeouts). | > 85% | Moyen | **Haute** |
| **`validator_ev.py`** | <span style="color:red">**Élevé**</span> | Validation de base EV/ROI, policy simple. | Scénarios de validation complexes avec données variées, cas limites sur les budgets (0, négatif), validation des "gates" avec combinaisons de données. | > 85% | Élevé | **Haute** |
| **`config/env_utils.py`** | <span style="color:red">**Élevé**</span> | Le comportement (défaut, alias, fail-fast) est testé. | **Aucun test manquant critique.** La couverture n'était pas mesurée. | > 95% | Faible | **Haute** |
| **`pipeline_run.py`** | <span style="color:orange">Moyen</span> | Scénarios nominaux de génération de tickets. | Tests des branches manquées (abstention, erreurs dans les sous-fonctions), combinaisons de `gates` bloquantes. | > 85% | Moyen | Moyenne |
| **`scrapers` (legacy)** | <span style="color:orange">Moyen</span> | `zeturf.py` est bien couvert, `online_fetch_zeturf.py` a quelques tests sur fixture. | Plus de fixtures HTML pour `online_fetch_zeturf.py` (simuler changements de structure), tests unitaires des fonctions de parsing. | > 75% | Moyen | Moyenne |
| **API Endpoints Sécurisés** | <span style="color:green">Faible</span> | Tests unitaires avec mocks (401/403 sans clé, 200 avec). | Script de smoke test `smoke_prod.sh` pour valider avec une vraie clé via variable d'environnement. | 100% | Faible | Moyenne |
| **Intégration UI + API** | <span style="color:green">Faible</span> | `TestClient` vérifie le statut 200 de la page et de l'API. | Validation plus stricte du schéma JSON de `/api/pronostics`. | 100% | Faible | Faible |
| **`plan.py`** | <span style="color:green">Faible</span> | Couverture complète (100%). | Aucun. | Maintenir | Faible | Faible |
| **`firestore_client.py`** | <span style'color:green'>Faible</span> | Couverture quasi complète (98%). | Aucun. | Maintenir | Faible | Faible |