# TEST_PLAN.md

Ce document fournit une série de commandes `curl` pour effectuer un "smoke test" de base sur l'application `hippique-orchestrator` une fois déployée.

**Prérequis :**
- Remplacez `<YOUR_CLOUD_RUN_URL>` par l'URL de base de votre service Cloud Run (ex: `https://hippique-orchestrator-xxxx-ew.a.run.app`).
- Remplacez `<YOUR_API_KEY>` par la valeur de la variable d'environnement `INTERNAL_API_SECRET`.
- Remplacez `<YYYY-MM-DD>` par une date valide pour laquelle vous attendez des courses (ex: `$(date +%F)` pour aujourd'hui).

---

### 1. Test de Santé (Health Check)
**Objectif :** Vérifier que le service est en ligne et répond.
**Commande :**
```bash
curl -s <YOUR_CLOUD_RUN_URL>/health | jq .
```
**Résultat Attendu :**
- **Code HTTP :** 200 OK
- **JSON :**
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```
*(La version peut varier)*

---

### 2. Test de l'API Pronostics (sans authentification)
**Objectif :** Vérifier que l'endpoint est bien protégé.
**Commande :**
```bash
curl -s -o /dev/null -w "%{http_code}" <YOUR_CLOUD_RUN_URL>/api/pronostics?date=<YYYY-MM-DD>
```
**Résultat Attendu :**
- **Code HTTP :** 403 Forbidden
*(Note : si `REQUIRE_AUTH` est à `False` en production, ce test retournera 200. Le comportement attendu en production est 403).*

---

### 3. Test de l'API Pronostics (avec authentification)
**Objectif :** Vérifier que l'API renvoie des données de pronostics pour une date donnée.
**Commande :**
```bash
curl -s -H "X-API-Key: <YOUR_API_KEY>" "<YOUR_CLOUD_RUN_URL>/api/pronostics?date=<YYYY-MM-DD>" | jq .
```
**Résultat Attendu :**
- **Code HTTP :** 200 OK
- **JSON (Structure) :** Un JSON valide contenant les clés `"ok": true`, `"date"`, `"counts"` et `"pronostics"`. La valeur de `"counts.total_in_plan"` devrait être supérieure à 0 si des courses sont prévues pour la date.

---

### 4. Test de Déclenchement de la Planification (Scheduling)
**Objectif :** Vérifier que l'endpoint de planification des tâches fonctionne.
**Commande :**
```bash
curl -s -X POST -H "Content-Type: application/json" -H "X-API-Key: <YOUR_API_KEY>" \
-d '{"date": "<YYYY-MM-DD>", "dry_run": true}' \
"<YOUR_CLOUD_RUN_URL>/schedule" | jq .
```
**Résultat Attendu :**
- **Code HTTP :** 200 OK
- **JSON (Structure) :** Un JSON valide contenant les clés `"message"`, `"races_in_plan"`, et `"details"`. `races_in_plan` doit être supérieur à 0 et `details` doit contenir une liste des tâches qui seraient planifiées.