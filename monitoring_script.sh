#!/bin/bash
set -e

# ============================================================================
# Script de monitoring - Orchestrateur Hippique
# ============================================================================
# Usage: ./monitor.sh [--watch N] [--alerts]
# Options:
#   --watch N : Rafraîchir toutes les N secondes
#   --alerts  : Vérifier et afficher les alertes uniquement
# ============================================================================

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

PROJECT_ID=${PROJECT_ID:-$(gcloud config get-value project)}
REGION=${REGION:-"europe-west1"}
SERVICE_NAME=${SERVICE_NAME:-"horse-racing-orchestrator"}

# Mode watch
WATCH_MODE=false
WATCH_INTERVAL=30
ALERTS_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --watch)
            WATCH_MODE=true
            WATCH_INTERVAL=${2:-30}
            shift 2
            ;;
        --alerts)
            ALERTS_ONLY=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ----------------------------------------------------------------------------
# Fonctions utilitaires
# ----------------------------------------------------------------------------

print_header() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}  $1"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}"
}

print_section() {
    echo ""
    echo -e "${CYAN}▶ $1${NC}"
    echo "─────────────────────────────────────────────"
}

check_status() {
    local cmd="$1"
    local success_msg="$2"
    local error_msg="$3"
    
    if eval "$cmd" &>/dev/null; then
        echo -e "${GREEN}✓${NC} $success_msg"
        return 0
    else
        echo -e "${RED}✗${NC} $error_msg"
        return 1
    fi
}

get_metric() {
    local query="$1"
    gcloud logging read "$query" --limit 1 --format json 2>/dev/null | jq -r '.[0]' || echo "null"
}

# ----------------------------------------------------------------------------
# Fonction principale de monitoring
# ----------------------------------------------------------------------------

monitor() {
    clear
    
    print_header "🐴 Monitoring Orchestrateur Hippique - $(date '+%Y-%m-%d %H:%M:%S')"
    
    # ========================================================================
    # 1. SERVICE CLOUD RUN
    # ========================================================================
    if [ "$ALERTS_ONLY" = false ]; then
        print_section "1. Service Cloud Run"
        
        SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
            --region $REGION \
            --project $PROJECT_ID \
            --format 'value(status.url)' 2>/dev/null || echo "")
        
        if [ -z "$SERVICE_URL" ]; then
            echo -e "${RED}✗ Service non déployé${NC}"
        else
            echo -e "${GREEN}✓ Service actif${NC}"
            echo "  URL: $SERVICE_URL"
            
            # État du service
            SERVICE_STATE=$(gcloud run services describe $SERVICE_NAME \
                --region $REGION \
                --format 'value(status.conditions[0].status)' 2>/dev/null)
            
            if [ "$SERVICE_STATE" = "True" ]; then
                echo -e "  État: ${GREEN}Ready${NC}"
            else
                echo -e "  État: ${YELLOW}Not Ready${NC}"
            fi
            
            # Révisions
            REVISION_COUNT=$(gcloud run revisions list \
                --service $SERVICE_NAME \
                --region $REGION \
                --format 'value(name)' | wc -l)
            echo "  Révisions: $REVISION_COUNT"
            
            # Healthcheck
            if TOKEN=$(gcloud auth print-identity-token --audiences=$SERVICE_URL 2>/dev/null); then
                if curl -s -f -H "Authorization: Bearer $TOKEN" "$SERVICE_URL/healthz" &>/dev/null; then
                    echo -e "  Healthcheck: ${GREEN}OK${NC}"
                else
                    echo -e "  Healthcheck: ${RED}FAILED${NC}"
                fi
            fi
        fi
    fi
    
    # ========================================================================
    # 2. CLOUD TASKS QUEUE
    # ========================================================================
    if [ "$ALERTS_ONLY" = false ]; then
        print_section "2. Cloud Tasks Queue"
        
        QUEUE_STATE=$(gcloud tasks queues describe horse-racing-queue \
            --location $REGION \
            --format 'value(state)' 2>/dev/null || echo "NOT_FOUND")
        
        if [ "$QUEUE_STATE" = "RUNNING" ]; then
            echo -e "${GREEN}✓ Queue active${NC}"
            
            # Nombre de tâches
            TASK_COUNT=$(gcloud tasks list \
                --queue=horse-racing-queue \
                --location=$REGION \
                --format='value(name)' 2>/dev/null | wc -l)
            
            if [ "$TASK_COUNT" -eq 0 ]; then
                echo "  Tâches en attente: ${YELLOW}0${NC}"
            elif [ "$TASK_COUNT" -lt 10 ]; then
                echo "  Tâches en attente: ${GREEN}${TASK_COUNT}${NC}"
            else
                echo "  Tâches en attente: ${CYAN}${TASK_COUNT}${NC}"
            fi
            
            # Prochaine tâche
            NEXT_TASK=$(gcloud tasks list \
                --queue=horse-racing-queue \
                --location=$REGION \
                --format='table[no-heading](scheduleTime)' \
                --sort-by=scheduleTime \
                --limit=1 2>/dev/null)
            
            if [ -n "$NEXT_TASK" ]; then
                echo "  Prochaine: $NEXT_TASK"
            fi
        else
            echo -e "${RED}✗ Queue non trouvée ou inactive${NC}"
        fi
    fi
    
    # ========================================================================
    # 3. CLOUD SCHEDULER
    # ========================================================================
    if [ "$ALERTS_ONLY" = false ]; then
        print_section "3. Cloud Scheduler"
        
        JOB_STATE=$(gcloud scheduler jobs describe daily-plan-0900 \
            --location $REGION \
            --format 'value(state)' 2>/dev/null || echo "NOT_FOUND")
        
        if [ "$JOB_STATE" = "ENABLED" ]; then
            echo -e "${GREEN}✓ Job actif${NC}"
            
            LAST_RUN=$(gcloud scheduler jobs describe daily-plan-0900 \
                --location $REGION \
                --format 'value(status.lastAttemptTime)' 2>/dev/null)
            
            if [ -n "$LAST_RUN" ]; then
                echo "  Dernière exécution: $LAST_RUN"
            else
                echo -e "  Dernière exécution: ${YELLOW}Jamais${NC}"
            fi
            
            SCHEDULE=$(gcloud scheduler jobs describe daily-plan-0900 \
                --location $REGION \
                --format 'value(schedule)' 2>/dev/null)
            echo "  Schedule: $SCHEDULE (Europe/Paris)"
        else
            echo -e "${RED}✗ Job non trouvé ou désactivé${NC}"
        fi
    fi
    
    # ========================================================================
    # 4. MÉTRIQUES & LOGS (dernières 24h)
    # ========================================================================
    print_section "4. Métriques (24h)"
    
    # Requêtes totales
    TOTAL_REQUESTS=$(gcloud logging read \
        "resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE_NAME AND timestamp>=\"$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)\"" \
        --limit 10000 --format json 2>/dev/null | jq '. | length' || echo "0")
    echo "  Requêtes totales: $TOTAL_REQUESTS"
    
    # Requêtes /schedule
    SCHEDULE_REQUESTS=$(gcloud logging read \
        "resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE_NAME AND httpRequest.requestUrl=~'/schedule' AND timestamp>=\"$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)\"" \
        --limit 1000 --format json 2>/dev/null | jq '. | length' || echo "0")
    echo "  Requêtes /schedule: $SCHEDULE_REQUESTS"
    
    # Requêtes /run
    RUN_REQUESTS=$(gcloud logging read \
        "resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE_NAME AND httpRequest.requestUrl=~'/run' AND timestamp>=\"$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)\"" \
        --limit 1000 --format json 2>/dev/null | jq '. | length' || echo "0")
    echo "  Requêtes /run: $RUN_REQUESTS"
    
    # Erreurs (5xx)
    ERROR_COUNT=$(gcloud logging read \
        "resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE_NAME AND httpRequest.status>=500 AND timestamp>=\"$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)\"" \
        --limit 1000 --format json 2>/dev/null | jq '. | length' || echo "0")
    
    if [ "$ERROR_COUNT" -eq 0 ]; then
        echo -e "  Erreurs 5xx: ${GREEN}$ERROR_COUNT${NC}"
    elif [ "$ERROR_COUNT" -lt 5 ]; then
        echo -e "  Erreurs 5xx: ${YELLOW}$ERROR_COUNT${NC}"
    else
        echo -e "  Erreurs 5xx: ${RED}$ERROR_COUNT${NC} ⚠️"
    fi
    
    # ========================================================================
    # 5. ALERTES
    # ========================================================================
    print_section "5. Alertes & Anomalies"
    
    ALERTS=0
    
    # Alerte 1: Service down
    if [ -z "$SERVICE_URL" ]; then
        echo -e "${RED}🚨 CRITIQUE: Service non déployé${NC}"
        ((ALERTS++))
    fi
    
    # Alerte 2: Erreurs récentes
    RECENT_ERRORS=$(gcloud logging read \
        "resource.type=cloud_run_revision AND severity>=ERROR AND timestamp>=\"$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)\"" \
        --limit 10 --format json 2>/dev/null | jq '. | length' || echo "0")
    
    if [ "$RECENT_ERRORS" -gt 0 ]; then
        echo -e "${YELLOW}⚠️  $RECENT_ERRORS erreurs dans la dernière heure${NC}"
        ((ALERTS++))
    fi
    
    # Alerte 3: Tâches échouées
    FAILED_TASKS=$(gcloud tasks list \
        --queue=horse-racing-queue \
        --location=$REGION \
        --filter="attemptDispatchCount>1" \
        --format='value(name)' 2>/dev/null | wc -l || echo "0")
    
    if [ "$FAILED_TASKS" -gt 0 ]; then
        echo -e "${YELLOW}⚠️  $FAILED_TASKS tâches avec retries${NC}"
        ((ALERTS++))
    fi
    
    # Alerte 4: Scheduler jamais exécuté
    if [ "$JOB_STATE" = "ENABLED" ] && [ -z "$LAST_RUN" ]; then
        echo -e "${YELLOW}⚠️  Scheduler jamais exécuté${NC}"
        ((ALERTS++))
    fi
    
    # Alerte 5: Latence élevée
    HIGH_LATENCY=$(gcloud logging read \
        "resource.type=cloud_run_revision AND httpRequest.latency>10s AND timestamp>=\"$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)\"" \
        --limit 10 --format json 2>/dev/null | jq '. | length' || echo "0")
    
    if [ "$HIGH_LATENCY" -gt 0 ]; then
        echo -e "${YELLOW}⚠️  $HIGH_LATENCY requêtes >10s dans la dernière heure${NC}"
        ((ALERTS++))
    fi
    
    if [ "$ALERTS" -eq 0 ]; then
        echo -e "${GREEN}✓ Aucune alerte${NC}"
    else
        echo ""
        echo -e "${YELLOW}Total: $ALERTS alertes détectées${NC}"
    fi
    
    # ========================================================================
    # 6. DERNIERS LOGS
    # ========================================================================
    if [ "$ALERTS_ONLY" = false ]; then
        print_section "6. Derniers logs (5 entrées)"
        
        gcloud logging read \
            "resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE_NAME" \
            --limit 5 \
            --format 'table(timestamp.date("%Y-%m-%d %H:%M:%S"),severity,jsonPayload.message)' 2>/dev/null || \
            echo "Aucun log récent"
    fi
    
    # ========================================================================
    # FOOTER
    # ========================================================================
    echo ""
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "Dernière mise à jour: $(date '+%H:%M:%S')"
    
    if [ "$WATCH_MODE" = true ]; then
        echo -e "${CYAN}Rafraîchissement dans ${WATCH_INTERVAL}s... (Ctrl+C pour quitter)${NC}"
    fi
}

# ----------------------------------------------------------------------------
# Boucle principale
# ----------------------------------------------------------------------------

if [ "$WATCH_MODE" = true ]; then
    while true; do
        monitor
        sleep $WATCH_INTERVAL
    done
else
    monitor
fi
