# 🔧 Troubleshooting Guide - Hippique Orchestrator

Guide avancé pour diagnostiquer et résoudre les problèmes courants.

---

## 🔍 Méthodologie de diagnostic

### 1. Vérification rapide (Health Check)

```bash
# Test endpoint healthz
curl https://your-service-url/healthz

# Doit retourner: {"status":"ok","service":"hippique-orchestrator","version":"1.0.0"}
```

### 2. Consulter les logs

```bash
# Logs en temps réel
gcloud logging tail "resource.type=cloud_run_revision" --format=json

# Logs d'une course spécifique (via correlation_id)
gcloud logging read 'jsonPayload.correlation_id="run-20251015-r1c3-h5"' --limit 50

# Logs d'erreurs uniquement
gcloud logging read 'severity>=ERROR' --limit 100
```

### 3. Vérifier état des ressources

```bash
# Cloud Run service
gcloud run services describe hippique-orchestrator --region=europe-west1

# Cloud Tasks queue
gcloud tasks queues describe hippique-analysis-queue --location=europe-west1

# Cloud Scheduler job
gcloud scheduler jobs describe hippique-daily-planning --location=europe-west1
```

---

## ❌ Problèmes fréquents

### Problème 1: Tâches Cloud Tasks non exécutées

**Symptômes :**
- Logs montrent création de tâches mais pas d'exécution
- Queue état: `PAUSED` ou taux d'erreur élevé

**Diagnostic :**
```bash
# Vérifier état queue
gcloud tasks queues describe hippique-analysis-queue --location=europe-west1

# Lister tâches en attente
gcloud tasks list --queue=hippique-analysis-queue --location=europe-west1 --limit=20
```

**Causes possibles :**

#### 1.1. Queue en pause
```bash
# Résolution
gcloud tasks queues resume hippique-analysis-queue --location=europe-west1
```

#### 1.2. Service Cloud Run injoignable
```bash
# Tester manuellement
TOKEN=$(gcloud auth print-identity-token)
curl -X POST https://your-service-url/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"course_url":"...","phase":"H5","date":"2025-10-15"}'
```

Si erreur 403 → problème IAM :
```bash
# Vérifier invoker role
gcloud run services get-iam-policy hippique-orchestrator --region=europe-west1

# Ajouter si manquant
gcloud run services add-iam-policy-binding hippique-orchestrator \
  --region=europe-west1 \
  --member="serviceAccount:YOUR_SA@project.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

#### 1.3. Tâches expirées (scheduleTime passé)
```bash
# Purger queue et recréer planning
gcloud tasks queues purge hippique-analysis-queue --location=europe-west1

# Redéclencher /schedule
make trigger
```

---

### Problème 2: Analyse retourne "UNPLAYABLE"

**Symptômes :**
- Fichier `data/RxCy/UNPLAYABLE.txt` créé
- Logs: "insufficient data", "missing CSV"

**Diagnostic :**
```bash
# Vérifier présence CSV J/E
ls -la data/R1C3/*.csv

# Logs détaillés
gcloud logging read 'jsonPayload.message=~"fetch_je"' --limit 20
```

**Causes et résolutions :**

#### 2.1. CSV J/E manquants (site source down)
```bash
# Retry manuel
python scripts/fetch_je_stats.py --dir data/R1C3
python scripts/fetch_je_chrono.py --dir data/R1C3

# Si persistant, activer fallback heuristique
export ALLOW_HEURISTIC=1
python scripts/analyse_courses_du_jour_enrichie.py --course-url ...
```

#### 2.2. Overround trop élevé
```bash
# Vérifier snapshot
cat data/R1C3/snapshot_H5.json | jq '.market.overround'

# Si > 1.35, ajuster seuil
python scripts/pipeline_run.py analyse \
  --in data/R1C3 \
  --overround-max 1.40
```

#### 2.3. Partants < 5
```bash
# Vérifier
cat data/R1C3/snapshot_H5.json | jq '.runners | length'

# Course non analysable si < 5 partants (normal)
```

---

### Problème 3: ROI réel << ROI estimé (surestimation)

**Symptômes :**
- ROI estimé +25%, ROI réel −5%
- Écart persistant sur 20+ courses

**Diagnostic :**
```bash
# Analyser erreur payout
python scripts/monitor_roi.py --excel excel/modele_suivi_courses_hippiques.xlsx --window 30

# Comparer calibration
diff calibration/payout_calibration.yaml calibration/payout_calibration.yaml.backup
```

**Résolutions :**

#### 3.1. Calibration obsolète
```bash
# Recalibrer avec historique récent
python scripts/recalibrate_payouts_pro.py \
  --history data/results/*.json \
  --out calibration/payout_calibration.yaml

# Redéployer
./scripts/deploy_cloud_run.sh
```

#### 3.2. CLV systématiquement négatif
```bash
# Analyser CLV moyen (doit être >0%)
cat data/*/analysis_H5.json | jq '.tickets[].clv' | awk '{s+=$1; n++} END {print "CLV moyen:", s/n "%"}'

# Si CLV < -5%, problème de timing ou drift adverse
# → Ajuster timing snapshot (ex: H-3 au lieu de H-5)
```

#### 3.3. Market makers détectent patterns
```bash
# Diversifier heures snapshot (aléatoire ±2min)
# Modifier scheduler.py ligne ~85
schedule_time = race_dt - timedelta(minutes=5 + random.randint(-2, 2))
```

---

### Problème 4: Cloud Scheduler job échoue à 09:00

**Symptômes :**
- Job status: `FAILED`
- Logs: timeout, 500, ou aucune exécution

**Diagnostic :**
```bash
# Historique exécutions
gcloud scheduler jobs describe hippique-daily-planning --location=europe-west1

# Dernière exécution
gcloud logging read 'resource.type="cloud_scheduler_job"
  AND resource.labels.job_id="hippique-daily-planning"' --limit 10
```

**Résolutions :**

#### 4.1. Timeout (endpoint /schedule trop lent)
```bash
# Augmenter timeout du job
gcloud scheduler jobs update http hippique-daily-planning \
  --location=europe-west1 \
  --attempt-deadline=600s
```

#### 4.2. OIDC token invalide
```bash
# Vérifier SA dans job
gcloud scheduler jobs describe hippique-daily-planning --location=europe-west1 \
  | grep serviceAccountEmail

# Recréer avec bon SA
./scripts/create_scheduler_0900.sh
```

#### 4.3. Service URL changée
```bash
# Après redéploiement, URL peut changer
# Mettre à jour job
NEW_URL=$(gcloud run services describe hippique-orchestrator --region=europe-west1 --format='value(status.url)')

gcloud scheduler jobs update http hippique-daily-planning \
  --location=europe-west1 \
  --uri="${NEW_URL}/schedule"
```

---

### Problème 5: Déploiement Cloud Run échoue

**Symptômes :**
- `gcloud run deploy` erreur 500 ou timeout
- Container ne démarre pas

**Diagnostic :**
```bash
# Logs build
gcloud builds list --limit=5

# Logs runtime
gcloud run services logs read hippique-orchestrator --region=europe-west1 --limit=50
```

**Résolutions :**

#### 5.1. Erreur build (Dockerfile)
```bash
# Build local pour debug
docker build -t hippique-test .
docker run -p 8080:8080 hippique-test

# Tester healthz
curl http://localhost:8080/healthz
```

#### 5.2. Import manquant (requirements.txt)
```bash
# Vérifier dependencies
docker run hippique-test python -c "import fastapi; import google.cloud.tasks"

# Si erreur, ajouter dans requirements.txt puis rebuild
```

#### 5.3. Mémoire insuffisante
```bash
# Augmenter mémoire
gcloud run services update hippique-orchestrator \
  --region=europe-west1 \
  --memory=4Gi
```

---

### Problème 6: Excel non mis à jour après analyse

**Symptômes :**
- Analysis H5 OK mais Excel inchangé
- Logs: "Permission denied" ou "File locked"

**Diagnostic :**
```bash
# Vérifier dernière modif Excel
ls -la excel/modele_suivi_courses_hippiques.xlsx

# Logs du script
gcloud logging read 'jsonPayload.message=~"update_excel"' --limit 20
```

**Résolutions :**

#### 6.1. Excel ouvert localement (lock)
```bash
# Fermer Excel et redémarrer analyse
python scripts/update_excel_planning.py --phase H5 --in data/R1C3 --excel excel/modele_suivi_courses_hippiques.xlsx
```

#### 6.2. Permissions fichier
```bash
# Vérifier propriétaire/permissions
ls -la excel/

# Corriger
chmod 664 excel/modele_suivi_courses_hippiques.xlsx
```

#### 6.3. Onglet "Planning" manquant
```bash
# Vérifier onglets
python -c "import openpyxl; wb = openpyxl.load_workbook('excel/modele_suivi_courses_hippiques.xlsx'); print(wb.sheetnames)"

# Créer onglet si absent (script le fait automatiquement normalement)
python scripts/update_excel_planning.py --phase H30 --in data/meeting --excel excel/modele_suivi_courses_hippiques.xlsx
```

---

## 🚨 Alertes critiques

### Alerte: Risk of Ruin > 1%

**Action immédiate :**
```bash
# 1. Réduire Kelly fraction
# Dans config/gpi_v51.yml:
KELLY_FRACTION: 0.4  # au lieu de 0.5

# 2. Augmenter seuils EV
EV_MIN_GLOBAL: 0.40  # au lieu de 0.35

# 3. Redéployer
./scripts/deploy_cloud_run.sh
```

### Alerte: Drawdown > −30%

**Action immédiate :**
```bash
# 1. Pause automatique combinés
# Créer flag
touch calibration/PAUSE_EXOTIQUES

# 2. Analyse post-mortem
python scripts/monitor_roi.py --excel excel/modele_suivi_courses_hippiques.xlsx --window 30

# 3. Recalibration
python scripts/recalibrate_payouts_pro.py --history data/results/*.json --out calibration/payout_calibration.yaml
```

### Alerte: Taux abstention > 20%

**Investigation :**
```bash
# Identifier causes
grep -r "UNPLAYABLE" data/*/UNPLAYABLE.txt | wc -l

# Analyser raisons
for f in data/*/UNPLAYABLE.txt; do
  echo "=== $f ==="
  cat "$f"
done

# Solutions possibles:
# - Ajuster seuils overround
# - Activer fallback J/E heuristique
# - Améliorer robustesse fetch CSV
```

---

## 🛠️ Outils de debug

### Script de diagnostic complet

```bash
#!/bin/bash
# debug.sh - Diagnostic complet

echo "=== CLOUD RUN ==="
gcloud run services describe hippique-orchestrator --region=europe-west1

echo -e "\n=== CLOUD TASKS ==="
gcloud tasks queues describe hippique-analysis-queue --location=europe-west1
gcloud tasks list --queue=hippique-analysis-queue --location=europe-west1 --limit=5

echo -e "\n=== CLOUD SCHEDULER ==="
gcloud scheduler jobs describe hippique-daily-planning --location=europe-west1

echo -e "\n=== RECENT ERRORS ==="
gcloud logging read 'severity>=ERROR' --limit=10 --format=json | jq -r '.[] | "\(.timestamp) [\(.severity)] \(.jsonPayload.message)"'

echo -e "\n=== METRICS (last 24h) ==="
python scripts/monitor_roi.py --excel excel/modele_suivi_courses_hippiques.xlsx --window 1

echo -e "\n=== DISK USAGE ==="
du -sh data/* excel/
```

### Mode verbose pour debugging

```bash
# Activer logs détaillés
export LOG_LEVEL=debug

# Analyser une course avec traces complètes
python scripts/analyse_courses_du_jour_enrichie.py \
  --course-url "https://www.zeturf.fr/fr/course/2025-10-15/R1C3-..." \
  --phase H5 \
  --verbose
```

---

## 📞 Escalade

Si problème persiste après ces vérifications :

1. **Collecter diagnostics** :
   ```bash
   ./debug.sh > diagnostic.txt
   gcloud logging read --limit=500 --format=json > logs.json
   ```

2. **Créer issue GitHub** avec :
   - Description problème
   - Steps to reproduce
   - Logs pertinents (masquer infos sensibles)
   - diagnostic.txt

3. **Contact support GCP** si infrastructure :
   - Cloud Run console → Support
   - Inclure correlation_id des requêtes échouées

---

## 📚 Ressources complémentaires

- [Cloud Run Troubleshooting](https://cloud.google.com/run/docs/troubleshooting)
- [Cloud Tasks Error Handling](https://cloud.google.com/tasks/docs/creating-http-target-tasks#error-handling)
- [Structured Logging Best Practices](https://cloud.google.com/logging/docs/structured-logging)

---

**Dernière mise à jour** : Octobre 2025  
**Mainteneur** : Architecture Cloud Run (Claude + Deletrez GPI v5.1)