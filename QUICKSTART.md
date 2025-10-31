# ⚡ Quick Start - 5 minutes to production

Guide express pour déployer Hippique Orchestrator sur Cloud Run.

---

## 📋 Prérequis (5 min)

```bash
# 1. Installer gcloud CLI
# https://cloud.google.com/sdk/docs/install

# 2. Authentification
gcloud auth login
gcloud auth application-default login

# 3. Créer projet GCP (ou utiliser existant)
gcloud projects create hippique-prod-2025 --name="Hippique Production"
gcloud config set project hippique-prod-2025

# 4. Activer facturation
# https://console.cloud.google.com/billing

# 5. Cloner ce repo
git clone https://github.com/your-org/hippique-orchestrator.git
cd hippique-orchestrator
```

---

## 🚀 Déploiement automatique (3 commandes)

### Option A: Script interactif (recommandé)

```bash
chmod +x scripts/init_project.sh
./scripts/init_project.sh
```

Le script vous guidera pas à pas et configure tout automatiquement.

### Option B: Manuel (pour les experts)

```bash
# 1. Configuration
cp .env.example .env
# Éditer .env avec vos valeurs

# 2. Setup GCP
make setup-gcp

# 3. Déploiement
make deploy

# 4. Scheduler quotidien
make scheduler
```

---

## ✅ Vérification

```bash
# Test endpoint
make trigger

# Consulter logs
make logs

# Healthcheck
curl $(gcloud run services describe hippique-orchestrator \
  --region=europe-west1 --format='value(status.url)')/healthz
```

**Sortie attendue :**
```json
{
  "status": "ok",
  "service": "hippique-orchestrator",
  "version": "1.0.0"
}
```

---

## 📊 Première analyse

### Test manuel (une course)

```bash
# Obtenir token
TOKEN=$(gcloud auth print-identity-token)

# Déclencher analyse H5
curl -X POST \
  https://your-service-url/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "course_url": "https://www.zeturf.fr/fr/course/2025-10-15/R1C3-paris-vincennes-trot",
    "phase": "H5",
    "date": "2025-10-15"
  }'
```

### Planification automatique (toutes les courses du jour)

```bash
# Déclencher planning
curl -X POST \
  https://your-service-url/schedule \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"date": "today", "mode": "tasks"}'
```

**Résultat :**
- Génère `plan.json` avec toutes les courses du jour
- Crée tâches Cloud Tasks pour H-30 et H-5 de chaque course
- Les analyses s'exécutent automatiquement aux heures programmées

---

## 📈 Monitoring

### Dashboard temps réel

```bash
# ROI des 30 derniers jours
python scripts/monitor_roi.py \
  --excel excel/modele_suivi_courses_hippiques.xlsx \
  --window 30

# Avec alertes Slack
python scripts/monitor_roi.py \
  --excel excel/modele_suivi_courses_hippiques.xlsx \
  --slack-webhook $SLACK_WEBHOOK_URL
```

### Logs structurés

```bash
# Tous les logs
make logs

# Erreurs uniquement
gcloud logging read 'severity>=ERROR' --limit=50

# Une course spécifique
gcloud logging read 'jsonPayload.correlation_id="run-20251015-r1c3-h5"'
```

### Métriques GCP

Console → [Cloud Run](https://console.cloud.google.com/run) → Metrics :
- Request count
- Request latency (p50, p95, p99)
- Error rate
- CPU / Memory utilization

---

## 🔧 Configuration avancée

### Ajuster paramètres GPI

Éditer `calibration/payout_calibration.yaml` :

```yaml
# Seuils EV/ROI
EV_MIN_GLOBAL: 0.40        # +40% au lieu de +35%
ROI_MIN_GLOBAL: 0.30       # +30% au lieu de +25%

# Kelly
KELLY_FRACTION: 0.4        # Plus conservateur (0.5 par défaut)

# Budget
BUDGET_TOTAL: 3.0          # 3€ au lieu de 5€
```

Puis redéployer :
```bash
make deploy
```

### Notifications Slack

1. Créer Incoming Webhook : https://api.slack.com/messaging/webhooks
2. Ajouter à .env :
   ```bash
   SLACK_WEBHOOK=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
   ```
3. Tester :
   ```bash
   python scripts/monitor_roi.py --excel excel/*.xlsx --slack-webhook $SLACK_WEBHOOK
   ```

### Backup automatique

Créer Cloud Scheduler job :

```bash
gcloud scheduler jobs create http hippique-daily-backup \
  --location=europe-west1 \
  --schedule="0 23 * * *" \
  --time-zone="Europe/Paris" \
  --uri="https://your-cloud-function-url/backup" \
  --http-method=POST

# Ou cron local
0 23 * * * cd /path/to/project && python scripts/backup_restore.py backup --date $(date +\%Y-\%m-\%d) --bucket my-bucket
```

---

## 🎯 Workflow quotidien typique

**09:00** - Cloud Scheduler déclenche `/schedule`
- Scrape ZEturf + Geny pour liste des courses
- Crée tâches H-30 et H-5 dans Cloud Tasks

**Toute la journée** - Exécutions automatiques
- H-30 : Snapshot cotes (marché early)
- H-5 : Analyse complète + génération tickets

**Soir** - Vérification ROI
```bash
python scripts/monitor_roi.py --excel excel/*.xlsx
```

**Hebdo** - Recalibration
```bash
python scripts/recalibrate_payouts_pro.py \
  --history data/results/*.json \
  --out calibration/payout_calibration.yaml
```

---

## 🆘 En cas de problème

### Logs pas de course trouvée

```bash
# Vérifier scraping ZEturf
python src/plan.py  # Test manuel

# Vérifier date format
curl -X POST .../schedule -d '{"date": "2025-10-15"}'  # YYYY-MM-DD obligatoire
```

### Analyse échoue (UNPLAYABLE)

```bash
# Vérifier données J/E
ls data/R1C3/*.csv

# Forcer retry
python scripts/fetch_je_stats.py --dir data/R1C3
```

### ROI réel << ROI estimé

```bash
# Recalibrer
python scripts/recalibrate_payouts_pro.py --history data/results/*.json --out calibration/payout_calibration.yaml

# Redéployer
make deploy
```

**Troubleshooting complet :** Voir [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

## 📚 Ressources

- **README.md** : Documentation complète
- **ARCHITECTURE.md** : Analyse ROI et décisions techniques
- **TROUBLESHOOTING.md** : Guide dépannage
- **Makefile** : Commandes utiles (`make help`)

---

## 🎉 C'est parti !

Vous êtes maintenant opérationnel. L'analyse hippique automatique est déployée et tourne 24/7.

**Prochaines étapes :**
1. Surveiller ROI sur les 30 premières courses
2. Ajuster seuils si nécessaire (EV, Kelly, overround)
3. Activer notifications Slack
4. Configurer backup automatique

**Objectif :** ROI moyen >+15% sur 100 courses 🎯

Bon turf ! 🏇

---

**Support :** Issues GitHub ou contact dans User-Agent  
**Version :** 1.0.0 (Cloud Run Edition)  
**Dernière MàJ :** Octobre 2025