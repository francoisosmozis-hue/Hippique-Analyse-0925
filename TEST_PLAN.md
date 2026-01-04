# Plan de Validation - Projet Hippique Orchestrator

Ce document décrit les procédures de test à exécuter pour valider la qualité, la stabilité et la non-régression de l'application.

## 1. Validation Locale Complète

Ces commandes doivent être exécutées depuis la racine du projet, avec l'environnement virtuel activé.

### 1.1. Exécution de la suite de tests de base

Cette commande lance tous les tests unitaires et d'intégration. Elle doit s'exécuter sans aucune erreur.

**Commande :**
```bash
pytest -q
```

**Résultat Attendu :**
-   Aucun test ne doit échouer (`... passed in ...`).
-   Le statut de sortie doit être `0`.

### 1.2. Vérification de la couverture de code

Cette commande exécute les tests tout en mesurant la couverture de code sur les modules critiques.

**Commande :**
```bash
pytest --cov=hippique_orchestrator --cov-report=term-missing
```

**Résultat Attendu :**
-   Tous les tests passent.
-   La couverture globale doit être supérieure à 65%.
-   La couverture pour les modules `plan.py`, `firestore_client.py`, et `analysis_pipeline.py` doit être supérieure à 80%.

### 1.3. Test de non-régression (Anti-Flaky)

Cette commande exécute la suite de tests 10 fois consécutivement pour détecter les tests "flaky" (instables).

**Commande :**
```bash
for i in $(seq 1 10); do echo "--- Run $i/10 ---"; pytest -q || exit 1; done
```

**Résultat Attendu :**
-   Les 10 exécutions doivent se terminer sans aucune erreur.
-   Aucun test ne doit échouer de manière intermittente.

## 2. Validation en Production (Smoke Test)

Cette procédure est destinée à être exécutée manuellement ou dans un pipeline de déploiement après une mise en production pour vérifier l'état de santé de base du service.

### 2.1. Prérequis

-   Le service doit être déployé et accessible via une URL.
-   La variable d'environnement `PROD_URL` doit être définie avec l'URL de base du service (ex: `export PROD_URL="https://hippique-orchestrator-xxxx.run.app"`).
-   Pour les tests d'endpoints sécurisés, la variable `HIPPIQUE_INTERNAL_API_KEY` doit être exportée avec une clé valide.

### 2.2. Exécution du script

Le script `smoke_prod.sh` automatise les vérifications de base.

**Commande :**
```bash
scripts/smoke_prod.sh
```

**Résultat Attendu :**
-   Le script doit se terminer avec un code de sortie `0`.
-   Les logs du script doivent indiquer le succès de chaque étape :
    -   `[OK] /health endpoint is healthy.`
    -   `[OK] /pronostics UI page loads.`
    -   `[OK] /api/pronostics returns data.`
    -   `[OK] /schedule rejects request without API key.`
    -   `[OK] /schedule accepts request with valid API key.`
-   Aucune information sensible (comme la clé API) ne doit être affichée dans les logs.
