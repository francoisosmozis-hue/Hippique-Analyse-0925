# TEST_PLAN.md

Ce document décrit les tests manuels (smoke tests) pour valider les correctifs et les nouvelles fonctionnalités implémentées.

## Prérequis

- `curl` et `jq` doivent être installés.
- Le service `hippique-orchestrator` doit être en cours d'exécution (par exemple, via `uvicorn`).
- Une clé API valide doit être exportée dans une variable d'environnement. La valeur par défaut pour les tests est `test-secret`.

  ```bash
  export OPS_TOKEN="test-secret"
  ```

## 1. Validation des Redirections Legacy (Correctif A)

Objectif : Vérifier que les anciennes URLs sont correctement redirigées.

### Test 1.1: Redirection de l'UI Legacy

**Commande :**
```bash
curl -I http://localhost:8000/pronostics/ui
```

**Résultat Attendu :**
La réponse doit être un `307 Temporary Redirect` pointant vers la nouvelle URL.
```
HTTP/1.1 307 Temporary Redirect
server: uvicorn
date: ...
content-length: 0
location: /pronostics
```

### Test 1.2: Redirection de l'API Legacy

**Commande :**
```bash
curl -I http://localhost:8000/api/pronostics/ui
```

**Résultat Attendu :**
La réponse doit être un `307 Temporary Redirect` pointant vers la nouvelle URL de l'API.
```
HTTP/1.1 307 Temporary Redirect
server: uvicorn
date: ...
content-length: 0
location: /api/pronostics
```

## 2. Validation de l'Endpoint d'Observabilité (Correctif B)

Objectif : Vérifier que l'endpoint `/ops/status` fournit un diagnostic clair de l'état du système.

### Test 2.1: Statut d'Opérations

**Commande :**
```bash
curl -s http://localhost:8000/ops/status | jq .
```

**Résultat Attendu :**
Un objet JSON contenant les clés `date`, `config`, `counts`, `firestore_metadata`, et `reason_if_empty`.
- Si aucune course n'a encore été traitée pour la journée, `reason_if_empty` doit avoir une valeur explicite comme `"NO_TASKS_PROCESSED_OR_FIRESTORE_EMPTY"`.
- `counts.total_in_plan` doit être supérieur à 0 si des courses sont prévues.

**Exemple de résultat (système bloqué) :**
```json
{
  "date": "2025-12-29",
  "config": {
    "project_id": "test-project",
    "firestore_collection": "races-test",
    "require_auth": false,
    "plan_source": "boturfers"
  },
  "counts": {
    "total_in_plan": 8,
    "total_processed": 0,
    "total_playable": 0,
    "total_abstain": 0,
    "total_error": 0,
    "total_pending": 8
  },
  "firestore_metadata": {
    "docs_count_for_date": 0,
    "last_doc_id": null,
    "last_update_ts": null
  },
  "reason_if_empty": "NO_TASKS_PROCESSED_OR_FIRESTORE_EMPTY",
  "last_task_attempt": null,
  "last_error": null
}
```

## 3. Validation du Déclenchement Manuel (Correctif C)

Objectif : Prouver qu'une exécution manuelle peut forcer le traitement d'une course et mettre à jour l'état du système.

### Test 3.1: Déclencher le traitement d'une course

**Note :** Assurez-vous qu'une course avec le label `R1C1` existe dans le plan du jour.

**Commande :**
```bash
curl -s -X POST "http://localhost:8000/ops/run?rc=R1C1" -H "X-API-Key: $OPS_TOKEN" | jq .
```

**Résultat Attendu :**
Un JSON indiquant le succès de l'opération et la décision prise.
```json
{
  "status": "success",
  "document_id": "...",
  "gpi_decision": "..."
}
```

### Test 3.2: Vérifier la mise à jour du statut

Immédiatement après le test 3.1, vérifiez que les compteurs globaux ont été mis à jour.

**Commande :**
```bash
curl -s http://localhost:8000/api/pronostics | jq '.counts'
```

**Résultat Attendu :**
Le compteur `total_processed` doit être passé à `1` (ou plus).
```json
{
  "total_in_plan": 8,
  "total_processed": 1,
  "total_analyzed": 1,
  "total_playable": ...,
  "total_abstain": ...,
  "total_error": ...,
  "total_pending": 7
}
```
Ce résultat confirme que le traitement a eu lieu et a été correctement persisté.
