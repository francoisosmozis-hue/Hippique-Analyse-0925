# Plan de Test

## Commandes locales

### Exécution des tests unitaires
```bash
pytest -q
```

### Exécution des tests avec couverture
```bash
pytest --cov=src
```

### Vérification de l'absence de tests flaky (10 exécutions)
```bash
for i in {1..10}; do pytest -q || exit 1; done
```

## Smoke Tests en Production

### Prérequis
- L'URL du service en production doit être définie dans la variable d'environnement `PROD_URL`.
- La clé d'API pour l'endpoint `/schedule` doit être définie dans la variable d'environnement `HIPPIQUE_INTERNAL_API_KEY`.

### Script de smoke test
Le script `scripts/smoke_prod.sh` exécute les tests suivants :
- Vérification de la disponibilité de l'endpoint `/pronostics`.
- Vérification de la disponibilité de l'endpoint `/api/pronostics`.
- Vérification que l'endpoint `/schedule` renvoie une erreur 403 sans clé d'API.
- Vérification que l'endpoint `/schedule` fonctionne avec une clé d'API valide.

```bash
#!/bin/bash
set -e

# Vérification de la présence de l'URL de production
if [ -z "$PROD_URL" ]; then
  echo "PROD_URL n'est pas définie."
  exit 1
fi

# Test de l'endpoint /pronostics
curl -sf $PROD_URL/pronostics > /dev/null
echo "/pronostics OK"

# Test de l'endpoint /api/pronostics
curl -sf $PROD_URL/api/pronostics > /dev/null
echo "/api/pronostics OK"

# Test de l'endpoint /schedule sans clé
if [ $(curl -s -o /dev/null -w "%{http_code}" $PROD_URL/schedule) -eq 403 ]; then
  echo "/schedule sans clé OK (403)"
else
  echo "/schedule sans clé KO"
  exit 1
fi

# Test de l'endpoint /schedule avec clé
if [ -z "$HIPPIQUE_INTERNAL_API_KEY" ]; then
  echo "HIPPIQUE_INTERNAL_API_KEY n'est pas définie, skip du test /schedule avec clé."
else
  if [ $(curl -s -o /dev/null -w "%{http_code}" -H "X-API-KEY: $HIPPIQUE_INTERNAL_API_KEY" $PROD_URL/schedule) -eq 200 ]; then
    echo "/schedule avec clé OK (200)"
  else
    echo "/schedule avec clé KO"
    exit 1
  fi
fi
```
