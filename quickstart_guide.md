# 🚀 Quickstart - Orchestrateur Hippique Cloud Run

Déployez en **5 minutes** votre système d'orchestration d'analyses hippiques sur Google Cloud.

---

## ⚡ Installation express

### 1. Prérequis (2 min)

```bash
# Vérifier gcloud CLI
gcloud version

# Authentification
gcloud auth login
gcloud config set project VOTRE_PROJECT_ID

# Activer les APIs
gcloud services enable \
  run.googleapis.com \
  cloudtasks.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com
```

### 2. Configuration (1 min)

```bash
# Copier le template
cp .env.example .env

# Éditer les valeurs essentielles
nano .env
```

**Valeurs à modifier** :
```bash
PROJECT_ID=votre-project-id
SCHEDULER_SA_EMAIL=horse-racing-orchestrator@votre-project-id.iam.gserviceaccount.com
```

### 3. Déploiement (2 min)

```bash
# Rendre les scripts exécutables
chmod +x scripts/*.sh

# Déployer Cloud Run (création auto du SA)
./scripts/deploy_cloud_run.sh

# Créer le scheduler quotidien 09:00
./scripts/create_scheduler_0900.sh
```

**C'est terminé !** 🎉

---

## 🧪 Premier test

```bash
# Récupérer l'URL du service
SERVICE_URL=$(gcloud run services describe horse-racing-orchestrator \
  --region europe-west1 --format 'value(status.url)')

# Tester le healthcheck
TOKEN=$(gcloud auth print-identity-token --audiences=$SERVICE_URL)
curl -H "Authorization: Bearer $TOKEN" $SERVICE_URL/healthz

# Déclencher le planning du jour
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"date":"today","mode":"tasks"}' \
  $SERVICE_URL/schedule
```

---

## 📊 Vérification

```bash
# Voir les tâches programmées
gcloud tasks list --queue=horse-racing-queue --location=europe-west1

# Voir les logs
gcloud logging read "resource.type=cloud_run_revision" --limit 20

# Statut complet
make status  # Si vous utilisez le Makefile
```

---

## 🔧 Avec Makefile (recommandé)

Si vous avez copié le `Makefile` :

```bash
# Setup initial (APIs + SA + queue)
make setup

# Déployer
make deploy

# Créer le scheduler
make scheduler

# Tester
make test-prod

# Voir les logs
make logs

# Statut complet
make status
```

---

## 📅 Fonctionnement automatique

Une fois déployé :

1. **Chaque jour à 09:00 Europe/Paris** :
   - Cloud Scheduler déclenche `POST /schedule`
   - Le service génère le plan du jour (parsing ZEturf + Geny)
   - Il crée automatiquement 2 tâches par course : **H-30** et **H-5**

2. **Aux heures précises** :
   - Cloud Tasks invoque `POST /run`
   - Les modules GPI v5.1 s'exécutent
   - Les artefacts sont générés (local + GCS si configuré)

**Aucune intervention manuelle nécessaire** ✅

---

## 🐛 Problème ?

```bash
# Voir les erreurs
make logs-errors

# Ou manuellement
gcloud logging read \
  "resource.type=cloud_run_revision AND severity>=ERROR" \
  --limit 20
```

**Erreurs courantes** :

1. **"Permission denied"** → Vérifier IAM :
   ```bash
   gcloud run services add-iam-policy-binding horse-racing-orchestrator \
     --region=europe-west1 \
     --member="serviceAccount:SA_EMAIL" \
     --role="roles/run.invoker"
   ```

2. **"Queue not found"** → Recréer la queue :
   ```bash
   gcloud tasks queues create horse-racing-queue \
     --location=europe-west1 \
     --max-attempts=3
   ```

3. **"Service not found"** → Redéployer :
   ```bash
   make deploy
   ```

---

## 🎯 Prochaines étapes

1. **Personnaliser** : Ajuster les paramètres dans `.env`
2. **Monitorer** : Configurer des alertes Cloud Monitoring
3. **Optimiser** : Ajuster les ressources (CPU/RAM) selon l'usage
4. **Archiver** : Configurer `GCS_BUCKET` pour sauvegarder les artefacts

---

## 📖 Documentation complète

Voir [README.md](README.md) pour :
- Architecture détaillée
- Configuration avancée
- Monitoring approfondi
- Troubleshooting complet

---

## 💡 Tips

**Tester manuellement** :
```bash
# Déclencher le planning maintenant
gcloud scheduler jobs run daily-plan-0900 --location=europe-west1

# Ou via API
TOKEN=$(gcloud auth print-identity-token --audiences=$SERVICE_URL)
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"date":"today","mode":"tasks"}' \
  $SERVICE_URL/schedule
```

**Voir une course spécifique** :
```bash
# Lister les tâches
gcloud tasks list --queue=horse-racing-queue --location=europe-west1

# Logs avec correlation_id
gcloud logging read \
  "jsonPayload.correlation_id=\"xxx\"" \
  --format json
```

**Nettoyer les tâches** :
```bash
# Purger la queue
make clean-tasks

# Ou manuellement
gcloud tasks queues purge horse-racing-queue --location=europe-west1
```

---

## ✅ Checklist de déploiement

- [ ] APIs GCP activées
- [ ] `.env` configuré avec PROJECT_ID
- [ ] Service Cloud Run déployé
- [ ] Service Account créé avec les bons rôles
- [ ] Queue Cloud Tasks créée
- [ ] Job Scheduler créé (09:00)
- [ ] Healthcheck OK
- [ ] Test manuel du planning OK
- [ ] Logs visibles dans Cloud Logging

---

**Besoin d'aide ?** Consultez les logs détaillés :

```bash
# Logs structurés
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=horse-racing-orchestrator" \
  --format json \
  --limit 50 | jq .
```

**Happy racing! 🐴**
