# 🔧 Guide de dépannage - Orchestrateur Hippique

Guide complet pour diagnostiquer et résoudre les problèmes courants.

---

## 📋 Table des matières

- [Diagnostic rapide](#diagnostic-rapide)
- [Erreurs de déploiement](#erreurs-de-déploiement)
- [Erreurs d'exécution](#erreurs-dexécution)
- [Problèmes de parsing](#problèmes-de-parsing)
- [Problèmes Cloud Tasks](#problèmes-cloud-tasks)
- [Problèmes Cloud Scheduler](#problèmes-cloud-scheduler)
- [Problèmes de permissions](#problèmes-de-permissions)
- [Performance & Timeout](#performance--timeout)
- [Logs & Monitoring](#logs--monitoring)

---

## 🚨 Diagnostic rapide

### Checklist 5 minutes

```bash
# 1. Service déployé ?
gcloud run services describe horse-racing-orchestrator \
  --region europe-west1 --format 'value(status.url)'
# ✅ Doit retourner une URL
# ❌ Si erreur → voir "Erreurs de déploiement"

# 2. Healthcheck OK ?
SERVICE_URL=$(gcloud run services describe horse-racing-orchestrator \
  --region europe-west1 --format 'value(status.url)')
TOKEN=$(gcloud auth print-identity-token --audiences=$SERVICE_URL)
curl -H "Authorization: Bearer $TOKEN" $SERVICE_URL/healthz
# ✅ Doit retourner {"status":"ok","timestamp":"..."}
# ❌ Si 401/403 → voir "Problèmes de permissions"
# ❌ Si 5xx → voir "Erreurs d'exécution"

# 3. Queue existe ?
gcloud tasks queues describe horse-racing-queue --location europe-west1
# ✅ Doit afficher les détails de la queue
# ❌ Si erreur → voir "Problèmes Cloud Tasks"

# 4. Scheduler configuré ?
gcloud scheduler jobs describe daily-plan-0900 --location europe-west1
# ✅ Doit afficher schedule="0 9 * * *"
# ❌ Si erreur → voir "Problèmes Cloud Scheduler"

# 5. Logs récents ?
gcloud logging read "resource.type=cloud_run_revision" --limit 10
# ✅ Doit afficher des logs JSON
# ❌ Si vide → Le service n'a pas été appelé
```

---

## 🚀 Erreurs de déploiement

### Erreur : "Permission denied" pendant le build

**Symptôme** :
```
ERROR: (gcloud.builds.submit) PERMISSION_DENIED: The caller does not have permission
```

**Causes** :
- API Cloud Build non activée
- Compte sans permissions

**Solutions** :
```bash
# 1. Activer Cloud Build
gcloud services enable cloudbuild.googleapis.com

# 2. Vérifier les permissions
gcloud projects get-iam-policy YOUR_PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:user:YOUR_EMAIL"

# 3. Ajouter rôle Editor (temporaire pour setup)
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="user:YOUR_EMAIL" \
  --role="roles/editor"
```

---

### Erreur : "Container failed to start"

**Symptôme** :
```
ERROR: Container failed to start. Failed to start and then listen on the port defined by the PORT environment variable.
```

**Causes** :
- Port incorrect dans le code
- Gunicorn ne démarre pas
- Dépendances manquantes

**Solutions** :
```bash
# 1. Vérifier les logs de démarrage
gcloud logging read \
  "resource.type=cloud_run_revision AND textPayload=~'Listening'" \
  --limit 20

# 2. Tester localement
docker build -t test .
docker run -p 8080:8080 -e REQUIRE_AUTH=false test

# 3. Vérifier gunicorn.conf.py
# Le bind doit être "0.0.0.0:8080"

# 4. Augmenter le timeout de démarrage
gcloud run services update horse-racing-orchestrator \
  --timeout 300 \
  --region europe-west1
```

---

### Erreur : "Service Account does not exist"

**Symptôme** :
```
ERROR: Service account [...] does not exist
```

**Solution** :
```bash
# Créer le Service Account
SA_NAME="horse-racing-orchestrator"
PROJECT_ID=$(gcloud config get-value project)

gcloud iam service-accounts create $SA_NAME \
  --display-name="Horse Racing Orchestrator"

# Attendre propagation
sleep 10

# Assigner les rôles
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/cloudtasks.enqueuer"

# Redéployer
./scripts/deploy_cloud_run.sh --no-build
```

---

## ⚙️ Erreurs d'exécution

### Erreur : "500 Internal Server Error"

**Diagnostic** :
```bash
# Voir les exceptions
gcloud logging read \
  "resource.type=cloud_run_revision AND severity>=ERROR" \
  --limit 20 --format json | jq .

# Chercher l'exception spécifique
gcloud logging read \
  "resource.type=cloud_run_revision AND jsonPayload.exception" \
  --limit 5
```

**Causes fréquentes** :

1. **Import error** :
   ```
   ModuleNotFoundError: No module named 'xxx'
   ```
   → Ajouter la dépendance dans `requirements.txt`

2. **Environment variable manquante** :
   ```
   KeyError: 'PROJECT_ID'
   ```
   → Vérifier les env vars dans Cloud Run

3. **Timeout subprocess** :
   ```
   TimeoutExpired: Command ... timed out after 300 seconds
   ```
   → Augmenter le timeout dans `runner.py`

**Solutions** :
```bash
# Mettre à jour les env vars
gcloud run services update horse-racing-orchestrator \
  --set-env-vars "PROJECT_ID=your-project,REGION=europe-west1" \
  --region europe-west1

# Redéployer avec correction
./scripts/deploy_cloud_run.sh
```

---

### Erreur : "Task execution failed"

**Symptôme** :
Logs Cloud Tasks montrent des échecs répétés

**Diagnostic** :
```bash
# Voir les erreurs de tasks
gcloud logging read \
  "resource.type=cloud_tasks_queue AND severity>=ERROR" \
  --limit 20

# Voir une tâche spécifique
gcloud tasks describe TASK_NAME \
  --queue horse-racing-queue \
  --location europe-west1
```

**Causes** :
- URL invalide
- Token OIDC expiré/invalide
- Service Cloud Run down
- Payload JSON mal formé

**Solutions** :
```bash
# 1. Vérifier que le service répond
TOKEN=$(gcloud auth print-identity-token --audiences=$SERVICE_URL)
curl -v -H "Authorization: Bearer $TOKEN" $SERVICE_URL/healthz

# 2. Recréer une tâche test
gcloud tasks create-http-task test-task \
  --queue=horse-racing-queue \
  --location=europe-west1 \
  --url="${SERVICE_URL}/run" \
  --method=POST \
  --header="Content-Type: application/json" \
  --body-content='{"course_url":"test","phase":"H30","date":"2025-10-16"}' \
  --oidc-service-account-email="${SA_EMAIL}" \
  --oidc-token-audience="${SERVICE_URL}"

# 3. Si échec répété, purger et recréer
gcloud tasks queues purge horse-racing-queue --location europe-west1
```

---

## 🔍 Problèmes de parsing

### Erreur : "No races found"

**Symptôme** :
```json
{"ok": false, "detail": "No races found for this date"}
```

**Diagnostic** :
```bash
# Tester le parsing manuellement
python -c "
from src.plan import PlanBuilder
builder = PlanBuilder()
plan = builder.build_plan('today')
print(f'Races found: {len(plan)}')
for race in plan[:3]:
    print(race)
"
```

**Causes** :
- Structure HTML ZEturf/Geny a changé
- Date invalide (jour férié, pas de courses)
- Throttling (429 Too Many Requests)
- IP bloquée

**Solutions** :

1. **Vérifier la structure HTML** :
```python
import requests
from bs4 import BeautifulSoup

resp = requests.get("https://www.zeturf.fr/fr/programme-pronostic/2025-10-16")
soup = BeautifulSoup(resp.text, 'lxml')

# Vérifier les liens de courses
links = soup.find_all('a', href=True)
course_links = [l for l in links if '/fr/course/' in l['href']]
print(f"Liens trouvés: {len(course_links)}")
```

2. **Ajuster les sélecteurs dans `src/plan.py`** :
```python
# Si la structure a changé
course_links = soup.select('div.course-card a.course-link')  # Exemple
```

3. **Augmenter le délai anti-throttle** :
```bash
# Dans .env
RATE_LIMIT_DELAY=2.0  # Au lieu de 1.0
```

---

### Erreur : "Error parsing time"

**Symptôme** :
Logs montrent des erreurs lors du parsing des heures

**Diagnostic** :
```bash
gcloud logging read \
  "resource.type=cloud_run_revision AND textPayload=~'Error parsing time'" \
  --limit 10
```

**Solution** :
Adapter le parsing des heures dans `src/plan.py` :

```python
# Supporter plusieurs formats
import re

def parse_time_flexible(time_str):
    """Parse 14h15, 14:15, 2:15 PM, etc."""
    patterns = [
        r'(\d{1,2})h(\d{2})',      # 14h15
        r'(\d{1,2}):(\d{2})',       # 14:15
        r'(\d{1,2})\.(\d{2})',      # 14.15
    ]
    
    for pattern in patterns:
        match = re.search(pattern, time_str)
        if match:
            h, m = match.groups()
            return f"{int(h):02d}:{int(m):02d}"
    
    return None
```

---

## 📦 Problèmes Cloud Tasks

### Erreur : "Queue does not exist"

**Solution** :
```bash
# Créer la queue
gcloud tasks queues create horse-racing-queue \
  --location=europe-west1 \
  --max-dispatches-per-second=5 \
  --max-concurrent-dispatches=10 \
  --max-attempts=3

# Vérifier
gcloud tasks queues describe horse-racing-queue --location europe-west1
```

---

### Erreur : "Task name already exists"

**Cause** :
Les tâches ont des noms déterministes → doublon si relancé

**Solution** :
1. **Purger l'ancienne tâche** :
```bash
gcloud tasks delete TASK_NAME \
  --queue=horse-racing-queue \
  --location=europe-west1
```

2. **Ou purger toute la queue** :
```bash
gcloud tasks queues purge horse-racing-queue \
  --location=europe-west1
```

3. **Code déjà géré** : Le code tente un GET avant CREATE et ignore si existe

---

### Tâches bloquées en "DISPATCHED"

**Diagnostic** :
```bash
gcloud tasks list --queue=horse-racing-queue --location=europe-west1
```

**Causes** :
- Service Cloud Run ne répond pas
- Timeout
- Erreur 5xx côté service

**Solution** :
```bash
# Voir les logs du service pour cette tâche
gcloud logging read \
  "resource.type=cloud_run_revision AND httpRequest.requestUrl=~'/run'" \
  --limit 20

# Si timeout, augmenter dans Cloud Run
gcloud run services update horse-racing-orchestrator \
  --timeout 300 \
  --region europe-west1
```

---

## 📅 Problèmes Cloud Scheduler

### Erreur : "UNAUTHENTICATED: Request had invalid authentication"

**Cause** :
Le job Scheduler utilise un mauvais Service Account ou audience

**Solution** :
```bash
# Vérifier le job
gcloud scheduler jobs describe daily-plan-0900 \
  --location=europe-west1 \
  --format json | jq .

# Recréer avec le bon SA et audience
gcloud scheduler jobs delete daily-plan-0900 --location europe-west1 --quiet

SERVICE_URL=$(gcloud run services describe horse-racing-orchestrator \
  --region europe-west1 --format 'value(status.url)')
SA_EMAIL="horse-racing-orchestrator@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud scheduler jobs create http daily-plan-0900 \
  --location=europe-west1 \
  --schedule="0 9 * * *" \
  --time-zone="Europe/Paris" \
  --uri="${SERVICE_URL}/schedule" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"date":"today","mode":"tasks"}' \
  --oidc-service-account-email=${SA_EMAIL} \
  --oidc-token-audience=${SERVICE_URL}
```

---

### Job ne se déclenche pas à l'heure prévue

**Diagnostic** :
```bash
# Voir l'historique d'exécution
gcloud scheduler jobs describe daily-plan-0900 \
  --location=europe-west1 \
  --format='value(status.lastAttemptTime,status.state)'

# Voir les logs
gcloud logging read "resource.type=cloud_scheduler_job" --limit 20
```

**Causes** :
- Timezone incorrecte
- Schedule mal formé
- Service suspendu

**Solutions** :
```bash
# Vérifier le schedule et timezone
gcloud scheduler jobs describe daily-plan-0900 --location=europe-west1

# Tester manuellement
gcloud scheduler jobs run daily-plan-0900 --location=europe-west1

# Recréer si nécessaire
./scripts/create_scheduler_0900.sh
```

---

## 🔐 Problèmes de permissions

### Erreur : "403 Forbidden"

**Diagnostic** :
```bash
# Vérifier IAM du service
gcloud run services get-iam-policy horse-racing-orchestrator \
  --region=europe-west1

# Doit contenir roles/run.invoker pour le SA
```

**Solution** :
```bash
SA_EMAIL="horse-racing-orchestrator@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud run services add-iam-policy-binding horse-racing-orchestrator \
  --region=europe-west1 \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker"
```

---

### Erreur : "Caller does not have permission to enqueue tasks"

**Solution** :
```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudtasks.enqueuer"

# Attendre propagation (30-60s)
sleep 60
```

---

## ⚡ Performance & Timeout

### Service lent / Timeout

**Diagnostic** :
```bash
# Voir les latences
gcloud logging read \
  "resource.type=cloud_run_revision AND httpRequest.latency" \
  --format json | jq '.[] | {latency: .httpRequest.latency, url: .httpRequest.requestUrl}'
```

**Solutions** :

1. **Augmenter CPU/RAM** :
```bash
gcloud run services update horse-racing-orchestrator \
  --cpu=2 \
  --memory=4Gi \
  --region=europe-west1
```

2. **Augmenter le timeout** :
```bash
gcloud run services update horse-racing-orchestrator \
  --timeout=600 \
  --region=europe-west1
```

3. **Optimiser le code** :
- Paralléliser les requêtes HTTP
- Mettre en cache les résultats
- Réduire les retries

---

## 📊 Logs & Monitoring

### Commandes utiles

```bash
# Logs en temps réel (tail -f)
gcloud logging tail "resource.type=cloud_run_revision" --format json

# Logs avec correlation_id
CORR_ID="xxx-xxx-xxx"
gcloud logging read \
  "jsonPayload.correlation_id=\"${CORR_ID}\"" \
  --format json | jq .

# Erreurs uniquement
gcloud logging read \
  "resource.type=cloud_run_revision AND severity>=ERROR" \
  --limit 50 --format json

# Requêtes lentes (>5s)
gcloud logging read \
  "resource.type=cloud_run_revision AND httpRequest.latency>5s" \
  --limit 20

# Grouper par status code
gcloud logging read \
  "resource.type=cloud_run_revision" \
  --limit 1000 --format json | \
  jq -r '.[] | .httpRequest.status' | \
  sort | uniq -c
```

---

## 🆘 Cas désespéré

Si rien ne fonctionne :

```bash
# 1. Tout supprimer
make destroy  # Ou manuellement

# 2. Nettoyer les résidus
gcloud tasks queues delete horse-racing-queue --location europe-west1 --quiet || true
gcloud scheduler jobs delete daily-plan-0900 --location europe-west1 --quiet || true
gcloud run services delete horse-racing-orchestrator --region europe-west1 --quiet || true

# 3. Redéployer from scratch
make setup
make deploy
make scheduler

# 4. Tester
make test-prod
```

---

## 📞 Support

Si le problème persiste :

1. **Collecter les informations** :
```bash
# Générer un rapport de diagnostic
cat > diagnostic_report.txt <<EOF
Date: $(date)
Project: $(gcloud config get-value project)
Region: europe-west1

=== Service Status ===
$(gcloud run services describe horse-racing-orchestrator --region europe-west1 2>&1)

=== Queue Status ===
$(gcloud tasks queues describe horse-racing-queue --location europe-west1 2>&1)

=== Recent Errors ===
$(gcloud logging read "severity>=ERROR" --limit 20 2>&1)
EOF

cat diagnostic_report.txt
```

2. **Consulter la documentation GCP** :
- [Cloud Run Troubleshooting](https://cloud.google.com/run/docs/troubleshooting)
- [Cloud Tasks Troubleshooting](https://cloud.google.com/tasks/docs/troubleshooting)

3. **Vérifier les status pages** :
- [GCP Status Dashboard](https://status.cloud.google.com/)

---

**Dernière mise à jour** : 2025-10-16
