# Plan de Test - Hippique Orchestrator

Ce document décrit les procédures pour exécuter les suites de tests automatisés du projet, à la fois localement et contre l'environnement de production.

## 1. Validation Locale Complète

Cette suite exécute l'ensemble des tests unitaires et d'intégration. Elle est conçue pour être exécutée avant chaque commit afin de garantir la non-régression et la qualité du code. Les dépendances externes (services Google Cloud, requêtes réseau) sont intégralement mockées pour assurer des tests rapides et déterministes.

### Pré-requis

- Un environnement Python avec les dépendances du projet installées (via `requirements.txt` et `requirements-dev.txt`).
- Être à la racine du projet.

### Exécution

Pour lancer la suite de tests complète, exécutez la commande suivante :

```bash
pytest
```

Pour une sortie plus concise, utilisez l'option `-q` :

```bash
pytest -q
```

### Résultat Attendu

Un passage réussi de la suite de tests se termine par un message indiquant `XXX passed in XX.XXs`, où `XXX` est le nombre total de tests. Aucun `failed` ou `error` ne doit être présent.

**Exemple de sortie en cas de succès :**
```
============================= 250 passed in 15.00s =============================
```

**Exemple de sortie en cas d'échec :**
```
=================================== FAILURES ===================================
... (détails des tests échoués) ...
=========================== short test summary info ============================
FAILED tests/test_example.py::test_failing - AssertionError: assert False
===================== 1 failed, 249 passed in 15.00s =====================
```

## 2. Smoke Tests en Production

Ce script exécute une série de tests de santé (smoke tests) directement sur l'URL du service en production. Il valide que les endpoints critiques sont accessibles, renvoient les codes HTTP et les types de contenu attendus, et que les mécanismes de sécurité (clé API) sont actifs.

### Pré-requis

- Les outils `curl` et `jq` doivent être installés sur votre système.
- Pour le test complet de l'endpoint `/schedule`, la variable d'environnement `HIPPIQUE_INTERNAL_API_KEY` doit être exportée et contenir la clé API valide pour la production.

### Exécution

Pour lancer les smoke tests, exécutez le script suivant depuis la racine du projet :

```bash
# Si la clé API est nécessaire pour le test complet
export HIPPIQUE_INTERNAL_API_KEY="votre_cle_api_ici"

bash scripts/smoke_prod.sh
```

### Résultat Attendu

Un passage réussi de tous les tests affichera un résumé final vert indiquant le nombre de tests passés.

**Exemple de sortie en cas de succès :**
```
--- Running Smoke Tests against: https://hippique-orchestrator-1084663881709.europe-west1.run.app ---
[OK] GET /pronostics: 200 text/html
[OK] GET /api/pronostics: 200 application/json with 'ok:true'
[OK] GET /pronostics/ui: Redirects successfully
[OK] POST /schedule (no key): 403 Forbidden
[OK] POST /schedule (with key): 200 OK
--- Smoke Tests Complete ---

Result: All 5 smoke tests passed.
```

**Exemple de sortie en cas d'échec :**
```
--- Running Smoke Tests against: https://hippique-orchestrator-1084663881709.europe-west1.run.app ---
[OK] GET /pronostics: 200 text/html
[FAIL] GET /api/pronostics: Expected 200 application/json, got 500:text/html
...
--- Smoke Tests Complete ---

Result: 1 failed, 4 passed.
```
Dans ce cas, le script se terminera avec un code de sortie non nul.
