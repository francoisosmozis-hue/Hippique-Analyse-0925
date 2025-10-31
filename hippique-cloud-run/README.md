# 🏇 GPI Hippique Analyzer - Cloud Run

Système d'analyse hippique automatisé avec GPI v5.1 sur Google Cloud Run.

## 🚀 Démarrage Rapide

```bash
# 1. Configuration
cp .env.example .env
# Éditer avec vos valeurs GCP

# 2. Copier vos modules GPI
cp /chemin/vers/gpi/*.py .

# 3. Setup GCP
./scripts/setup_gcp.sh

# 4. Déployer
./scripts/deploy_cloud_run.sh
./scripts/create_scheduler_0900.sh
```

## 📚 Documentation

Voir [docs/GUIDE.md](docs/GUIDE.md) pour le guide complet.

## 🏗️ Architecture

- **Cloud Run**: Service HTTP pour orchestration
- **Cloud Scheduler**: Déclenchement quotidien à 09:00
- **Cloud Tasks**: Programmation H-30 et H-5
- **GCS**: Stockage optionnel des artefacts

## 📡 Endpoints

- `POST /schedule` - Génère plan et programme analyses
- `POST /run` - Exécute analyse d'une course
- `GET /healthz` - Health check

## 📊 Features

✅ Planification automatique quotidienne  
✅ Snapshots H-30 et H-5 par course  
✅ Idempotence (Cloud Tasks)  
✅ Logs structurés JSON  
✅ OIDC authentication  
✅ Rate limiting (CGU compliant)  
✅ Timezone Europe/Paris  

## 📞 Support

Pour questions, voir documentation dans `docs/`.
