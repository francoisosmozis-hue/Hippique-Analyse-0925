# Plan de Test (TEST_PLAN.md)

Ce document décrit les procédures pour valider le projet `hippique-orchestrator`.

## 1. Validation Locale Complète

### 1.1. Exécution de la Suite de Tests Unitaires

Cette commande exécute l'intégralité des tests unitaires et d'intégration mockés.

**Commande :**
```bash
pytest -q
```

**Résultat Attendu :**
- `786 passed`
- Aucun échec (`failed`) ou erreur (`error`).

### 1.2. Vérification de la Couverture de Code

Cette commande génère un rapport de couverture détaillé pour identifier les zones non testées.

**Commande :**
```bash
pytest --cov=hippique_orchestrator
```

**Résultat Attendu :**
- Un rapport tabulaire affichant le pourcentage de couverture par fichier.
- **Objectif :** Atteindre >80% sur `plan.py`, `firestore_client.py`, et `analysis_pipeline.py`.

### 1.3. Détection des Tests Instables (Flaky Tests)

Cette commande exécute la suite de tests 10 fois consécutivement pour détecter toute instabilité.

**Commande :**
```bash
pytest -q --count=10
```

**Résultat Attendu :**
- `7860 passed` (786 tests * 10 runs).
- Aucun échec. Si un test échoue ne serait-ce qu'une fois, il est considéré comme "flaky" et doit être corrigé.

## 2. Validation en Production (Smoke Tests)

Ces tests sont à exécuter manuellement après un déploiement pour s'assurer que les services critiques sont opérationnels.

### 2.1. Script de Smoke Test

Le script `scripts/smoke_prod.sh` automatise les vérifications de base sur un environnement déployé.

**Prérequis :**
- `URL_PROD` : Variable d'environnement contenant l'URL de base du service (ex: `https://<service-url>.run.app`).
- `HIPPIQUE_INTERNAL_API_KEY` : Variable d'environnement contenant la clé API pour les endpoints protégés.

**Commande :**
```bash
./scripts/smoke_prod.sh
```

**Résultat Attendu :**
- Chaque test affiche `[OK]` ou `[FAIL]`.
- Tous les tests doivent afficher `[OK]`.

### 2.2. Contenu du Script `smoke_prod.sh`

```bash
#!/bin/bash

# Configuration
URL_PROD="${URL_PROD:-""}"
API_KEY="${HIPPIQUE_INTERNAL_API_KEY:-""}"

# Fonctions de test
assert_status() {
    local url=$1
    local expected_status=$2
    local extra_args=$3
    local description=$4

    # shellcheck disable=SC2086
    local status_code=$(curl -s -o /dev/null -w "%{{http_code}}" $extra_args "$url")

    if [ "$status_code" -eq "$expected_status" ]; then
        echo "[OK] $description (Status: $status_code)"
    else
        echo "[FAIL] $description (Expected: $expected_status, Got: $status_code)"
        exit 1
    fi
}

# --- Début des Tests ---

if [ -z "$URL_PROD" ]; then
    echo "[FAIL] La variable d'environnement URL_PROD n'est pas définie."
    exit 1
fi

echo "--- Démarrage des Smoke Tests sur $URL_PROD ---"

# 1. Test de l'endpoint public /api/pronostics
assert_status "${URL_PROD}/api/pronostics?date=$(date +%F)" 200 "" "Endpoint /api/pronostics"

# 2. Test de l'interface utilisateur /pronostics
assert_status "${URL_PROD}/pronostics" 200 "" "Endpoint /pronostics UI"

# 3. Test de /schedule sans clé API (accès refusé)
assert_status "${URL_PROD}/schedule" 403 "-X POST" "/schedule (sans API Key)"

# 4. Test de /schedule avec clé API (accès autorisé)
if [ -z "$API_KEY" ]; then
    echo "[SKIP] HIPPIQUE_INTERNAL_API_KEY non définie. Le test /schedule avec authentification est sauté."
else
    assert_status "${URL_PROD}/schedule" 200 "-X POST -H \"X-API-KEY: ${API_KEY}\"" "/schedule (avec API Key)"
fi

echo "--- Smoke Tests terminés avec succès ---"
```