# Plan de Test - Hippique Orchestrator

Ce document décrit les procédures de test à exécuter pour valider la qualité et la non-régression du projet.

## 1. Tests Unitaires et d'Intégration Locaux

Ces tests constituent la base de la validation et doivent être exécutés avant chaque commit.

### Commande d'Exécution Complète

Cette commande exécute l'intégralité de la suite de tests, génère un rapport de couverture et effectue 10 passes pour détecter les tests instables (flaky).

```bash
pytest --cov -q --cov-report=term-missing -n auto && \
for i in {1..10}; do \
  echo "---\nRUN $i/10 ---"; \
  pytest -q -n auto || exit 1; \
done
```

**Résultat Attendu :**
- `100% passed` pour chaque exécution.
- Aucune erreur ou échec.
- La couverture doit rester stable ou augmenter.

### Commande de Couverture Uniquement

Pour une analyse rapide de la couverture de code :

```bash
pytest --cov
```

**Résultat Attendu :**
- Un rapport tabulaire indiquant la couverture par fichier.
- L'objectif est de maintenir ou d'augmenter la couverture sur les modules critiques (>80%).

## 2. Validation Manuelle des Endpoints Sensibles

Ces tests ne doivent **pas** être automatisés dans la suite de tests CI pour éviter de stocker des secrets. Ils doivent être exécutés manuellement dans un environnement de pré-production ou de production.

### Endpoint `/schedule`

1.  **Test sans clé API :**
    ```bash
    curl -X POST "https://<URL_PROD>/schedule" -H "Content-Type: application/json" -d '{"date": "2025-01-01"}'
    ```
    **Résultat Attendu :**
    - Code de statut HTTP `401` ou `403`.
    - Réponse JSON : `{"detail":"Not authenticated"}` ou similaire.

2.  **Test avec clé API (via variable d'environnement) :**
    ```bash
    export HIPPIQUE_INTERNAL_API_KEY="votre_cle_api"
    curl -X POST "https://<URL_PROD>/schedule" -H "Content-Type: application/json" -H "X-API-Key: $HIPPIQUE_INTERNAL_API_KEY" -d '{"date": "2025-01-01"}'
    unset HIPPIQUE_INTERNAL_API_KEY
    ```
    **Résultat Attendu :**
    - Code de statut HTTP `200`.
    - Une réponse JSON indiquant le succès de la planification.

## 3. Smoke Tests de Production

Un script `smoke_prod.sh` est disponible pour effectuer une vérification de santé rapide sur l'environnement de production.

### Contenu de `scripts/smoke_prod.sh`

```bash
#!/bin/bash
set -e

# Vérifier que l'URL de production est fournie
if [ -z "$1" ]; then
  echo "Usage: $0 <production_url>"
  exit 1
fi
URL=$1

echo "### Smoke Test - Health Check ###"
curl -fL "$URL/health" | grep '"status":"healthy"'

echo -e "\n### Smoke Test - API Pronostics (JSON) ###"
curl -fL "$URL/api/pronostics" | grep '"ok":true'

echo -e "\n### Smoke Test - UI Pronostics (HTML) ###"
curl -fL "$URL/pronostics" | grep '<title>Hippique Orchestrator - Pronostics</title>'

echo -e "\n### Smoke Test - /schedule (sans API Key) ###"
# Nous attendons un code 403, donc nous ne voulons pas que -f échoue le script
response_code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$URL/schedule" -H "Content-Type: application/json" -d '{"date": "2025-01-01"}')
if [ "$response_code" -eq 403 ]; then
  echo "OK: Received expected 403 Forbidden"
else
  echo "FAIL: Expected 403, but received $response_code"
  exit 1
fi

if [ -z "$HIPPIQUE_INTERNAL_API_KEY" ]; then
  echo -e "\n### SKIP: /schedule (avec API Key) - HIPPIQUE_INTERNAL_API_KEY non définie ###"
else
  echo -e "\n### Smoke Test - /schedule (avec API Key) ###"
  curl -f -X POST "$URL/schedule" -H "Content-Type: application/json" -H "X-API-Key: $HIPPIQUE_INTERNAL_API_KEY" -d '{"date": "2025-01-01"}' | grep '"ok":true'
fi

echo -e "\n### Tous les smoke tests ont réussi ! ###"
```

### Exécution des Smoke Tests

```bash
# Exécuter sans la clé API pour les tests publics
bash scripts/smoke_prod.sh https://<URL_PROD>

# Exécuter avec la clé API pour le test complet
export HIPPIQUE_INTERNAL_API_KEY="votre_cle_api"
bash scripts/smoke_prod.sh https://<URL_PROD>
unset HIPPIQUE_INTERNAL_API_KEY
```

**Résultat Attendu :**
- Le script doit se terminer avec le message "Tous les smoke tests ont réussi !".
- Aucun code de sortie d'erreur.