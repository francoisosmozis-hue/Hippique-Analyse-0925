# Guide OpÃ©rationnel - Hippique Orchestrator

Ce document dÃ©crit les opÃ©rations quotidiennes, le monitoring et la maintenance du systÃ¨me.

## ðŸ"… Flux Quotidien Automatique

### Timeline Type

```
08:45 - PrÃ©paration systÃ¨me (auto)
09:00 - ðŸ"… Cloud Scheduler dÃ©clenche /schedule
09:01 - ðŸ" Construction du plan du jour (ZEturf + Geny)
09:02 - ðŸ"‹ CrÃ©ation des tÃ¢ches Cloud Tasks (H-30 + H-5 par course)
...
13:30 - ðŸš€ ExÃ©cution H-30 pour course de 14:00
13:55 - ðŸš€ ExÃ©cution H-5 pour course de 14:00
14:00 - ðŸ Course commence
...
19:00 - ðŸ DerniÃ¨res courses du jour
20:00 - ðŸ"Š Analyses post-journÃ©e
```

### Actions Automatiques

| Heure | Action | Description |
|-------|--------|-------------|
| 09:00 | Schedule | CrÃ©ation plan + programmation tÃ¢ches |
| H-30 | Analysis | Snapshot H-30 (donnÃ©es initiales) |
| H-5 | Analysis + Tickets | Snapshot H-5 + gÃ©nÃ©ration tickets |
| H+15 | Results (opt) | RÃ©cupÃ©ration rÃ©sultats officiels |

## 🔍 Monitoring Quotidien

### VÃ©rifications Matinales (09:15)

```bash
# 1. VÃ©rifier que le schedule s'est bien exÃ©cutÃ©
gcloud scheduler jobs describe hippique-daily-planning \
  --location=europe-west1 \
  --format="value(status.lastAttemptTime,status.state)"

# 2. VÃ©rifier le nombre de tÃ¢ches crÃ©Ã©es
gcloud tasks queues describe hippique-tasks \
  --location=europe-west1 \
  --format="value(stats.tasksCount)"

# 3. VÃ©rifier les logs du schedule
gcloud logging read \
  'resource.type=cloud_run_revision AND 
   jsonPayload.correlation_id=~"schedule-"' \
  --limit=10 \
  --format="table(timestamp,jsonPayload.message,jsonPayload.total_races)"
```

### Dashboard Cloud Console

Bookmarker ces URLs:

1. **Cloud Run Service**:
   ```
   https://console.cloud.google.com/run/detail/{REGION}/{SERVICE_NAME}
   ```

2. **Cloud Tasks Queue**:
   ```
   https://console.cloud.google.com/cloudtasks/queue/{REGION}/{QUEUE_ID}
   ```

3. **Cloud Scheduler**:
   ```
   https://console.cloud.google.com/cloudscheduler?project={PROJECT_ID}
   ```

4. **Logs Explorer**:
   ```
   https://console.cloud.google.com/logs/query
   ```

### Alertes Ã  Surveiller

âš ï¸ **Critiques** (immÃ©diat):
- Schedule failed (09:00)
- 0 courses trouvÃ©es
- Queue vide aprÃ¨s 09:05
- >50% analyses Ã©chouÃ©es

â ï¸ **Warnings** (dans l'heure):
- 1-2 analyses Ã©chouÃ©es
- Latence >30s
- Queue saturÃ©e (>100 tasks)

ℹï¸ **Info** (fin de journÃ©e):
- Statistiques globales
- Temps d'exÃ©cution moyen
- Taux de succÃ¨s

## ðŸ› ï¸ OpÃ©rations Manuelles

### DÃ©clencher Manuellement le Schedule

```bash
# MÃ©thode 1: Via Cloud Scheduler
gcloud scheduler jobs run hippique-daily-planning \
  --location=europe-west1

# MÃ©thode 2: Via API directe (avec auth)
curl -X POST https://YOUR_SERVICE_URL/schedule \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"date":"today","mode":"tasks"}'

# MÃ©thode 3: Pour une date spÃ©cifique
curl -X POST https://YOUR_SERVICE_URL/schedule \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"date":"2025-10-30","mode":"tasks"}'
```

### Lancer Manuellement une Analyse

```bash
# Pour une course spÃ©cifique
curl -X POST https://YOUR_SERVICE_URL/run \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "course_url": "https://www.zeturf.fr/fr/course/2025-10-28/R1C3-prix-xxx",
    "phase": "H5",
    "date": "2025-10-28"
  }'
```

### Purger la Queue (en cas de problÃ¨me)

```bash
# Attention: Supprime TOUTES les tÃ¢ches en attente
gcloud tasks queues purge hippique-tasks \
  --location=europe-west1
```

### Red†ployer le Service

```bash
# DÃ©ploiement complet
./scripts/deploy_cloud_run.sh

# DÃ©ploiement rapide (mÃªme config)
gcloud run deploy hippique-orchestrator \
  --region=europe-west1 \
  --image=gcr.io/YOUR_PROJECT/hippique-orchestrator:latest
```

## ðŸ"Š Analyse des Performances

### MÃ©triques ClÃ©s

```bash
# Nombre de courses par jour (moyenne)
gcloud logging read \
  'jsonPayload.total_races>0' \
  --limit=30 \
  --format="value(jsonPayload.total_races)" \
  | awk '{sum+=$1; count++} END {print "Moyenne:", sum/count}'

# Taux de succÃ¨s des analyses
gcloud logging read \
  'jsonPayload.message:"Analysis complete" OR jsonPayload.message:"Analysis failed"' \
  --limit=100 \
  --format="csv(jsonPayload.message)" \
  | sort | uniq -c

# Temps d'exÃ©cution moyen
gcloud logging read \
  'jsonPayload.phase AND jsonPayload.artifacts_count' \
  --format="value(jsonPayload.phase,timestamp)" \
  --limit=100
```

### Analyser les Erreurs

```bash
# Erreurs des derniÃ¨res 24h
gcloud logging read \
  'severity>=ERROR AND resource.type=cloud_run_revision' \
  --limit=50 \
  --format="table(timestamp,jsonPayload.message,jsonPayload.error)"

# Top erreurs
gcloud logging read \
  'severity>=ERROR' \
  --limit=200 \
  --format="value(jsonPayload.error)" \
  | sort | uniq -c | sort -rn | head -10
```

## 🔧 Maintenance

### Hebdomadaire (Lundi matin)

- [ ] VÃ©rifier les logs d'erreur de la semaine
- [ ] Analyser les statistiques de performance
- [ ] VÃ©rifier l'espace disque (si GCS non utilisÃ©)
- [ ] Tester le schedule manuellement

### Mensuel

- [ ] Revoir les coÃ»ts Cloud Run/Tasks/Scheduler
- [ ] Optimiser les images Docker si nÃ©cessaire
- [ ] Mettre Ã  jour les dÃ©pendances Python
- [ ] Backup configuration et secrets
- [ ] Test disaster recovery

### Trimestriel

- [ ] Audit sÃ©curitÃ© IAM
- [ ] Revue des alertes et seuils
- [ ] Optimisation des timeouts
- [ ] Documentation mise Ã  jour

## 🚨 Incidents & RÃ©solution

### Incident: Schedule ne s'exÃ©cute pas

**Symptômes**: Pas de tÃ¢ches crÃ©Ã©es Ã  09:00

**Diagnostic**:
```bash
# 1. VÃ©rifier le job Scheduler
gcloud scheduler jobs describe hippique-daily-planning \
  --location=europe-west1

# 2. VÃ©rifier les logs
gcloud logging read \
  'resource.type=cloud_scheduler_job AND 
   resource.labels.job_id="hippique-daily-planning"' \
  --limit=5
```

**Solutions**:
1. VÃ©rifier que le job existe et est activÃ© (ENABLED)
2. VÃ©rifier l'authentification OIDC
3. Red†clencher manuellement
4. RecrÃ©er le job si nÃ©cessaire: `./scripts/create_scheduler_0900.sh`

### Incident: Analyses Ã©chouent massivement

**Symptômes**: >50% analyses returncode != 0

**Diagnostic**:
```bash
# VÃ©rifier les erreurs communes
gcloud logging read \
  'jsonPayload.returncode!=0' \
  --limit=20 \
  --format="table(timestamp,jsonPayload.correlation_id,jsonPayload.stderr)"
```

**Solutions**:
1. VÃ©rifier connectivitÃ© ZEturf/Geny
2. VÃ©rifier timeout (TIMEOUT_SECONDS)
3. VÃ©rifier les modules Python (imports, dÃ©pendances)
4. Red†ployer si nÃ©cessaire

### Incident: Queue saturÃ©e

**Symptômes**: >200 tÃ¢ches en attente, latence Ã©levÃ©e

**Diagnostic**:
```bash
gcloud tasks queues describe hippique-tasks \
  --location=europe-west1 \
  --format="yaml(stats)"
```

**Solutions**:
1. Augmenter `maxConcurrentDispatches` de la queue
2. Augmenter `maxInstances` du service Cloud Run
3. Optimiser les analyses (rÃ©duire timeout)
4. Purger si nÃ©cessaire (ATTENTION)

### Incident: Service indisponible

**Symptômes**: 5xx errors, /healthz fail

**Diagnostic**:
```bash
# VÃ©rifier le service
gcloud run services describe hippique-orchestrator \
  --region=europe-west1 \
  --format="yaml(status)"

# VÃ©rifier les rÃ©visions
gcloud run revisions list \
  --service=hippique-orchestrator \
  --region=europe-west1
```

**Solutions**:
1. Rollback Ã  derniÃ¨re version stable
2. VÃ©rifier les mÃ©triques (RAM, CPU)
3. Augmenter ressources si nÃ©cessaire
4. Red†ployer

## ðŸ"ž Contact & Escalade

### Niveaux de Support

**Level 1** - OpÃ©rations courantes:
- Monitoring quotidien
- VÃ©rifications post-schedule
- DÃ©clenchements manuels

**Level 2** - Incidents:
- Analyses Ã©chouÃ©es
- Erreurs de configuration
- ProblÃ¨mes de performance

**Level 3** - Critique:
- Service totalement indisponible
- ProblÃ¨mes GCP infrastructure
- Failles de sÃ©curitÃ©

### Escalade

1. **VÃ©rifier la documentation** (ce fichier)
2. **Consulter les logs** (Cloud Logging)
3. **Tester manuellement** (curl + gcloud)
4. **Contacter l'Ã©quipe** si non rÃ©solu en 1h

## 📚 Ressources

- **README.md** - Documentation gÃ©nÃ©rale
- **API Reference** - https://YOUR_SERVICE_URL/docs (FastAPI auto-docs)
- **Cloud Run Docs** - https://cloud.google.com/run/docs
- **Cloud Tasks Docs** - https://cloud.google.com/tasks/docs
- **Cloud Scheduler Docs** - https://cloud.google.com/scheduler/docs

---

**Version**: 1.0  
**Last Updated**: 2025-10-28  
**Maintainer**: Ops Team
