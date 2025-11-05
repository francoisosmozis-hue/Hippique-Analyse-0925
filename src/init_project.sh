#!/usr/bin/env bash
# Initialize Hippique-Analyse project for development and deployment

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Header
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  🐴 Hippique-Analyse GPI v5.1 - Project Initialization"
echo "═══════════════════════════════════════════════════════"
echo ""

# 1. Check Python version
log_info "Checking Python version..."
if ! command -v python &> /dev/null; then
    log_error "Python not found. Please install Python 3.12+"
    exit 1
fi

PYTHON_VERSION=$(python --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
REQUIRED_VERSION="3.12"

if ! python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)"; then
    log_error "Python 3.12+ required (found $PYTHON_VERSION)"
    exit 1
fi

log_success "Python $PYTHON_VERSION detected"
echo ""

# 2. Check gcloud CLI (optional for local dev, required for deployment)
log_info "Checking gcloud CLI..."
if command -v gcloud &> /dev/null; then
    GCLOUD_VERSION=$(gcloud version --format="value(version)" 2>/dev/null || echo "unknown")
    log_success "gcloud CLI $GCLOUD_VERSION detected"
else
    log_warning "gcloud CLI not found (required for Cloud Run deployment)"
    log_warning "Install from: https://cloud.google.com/sdk/docs/install"
fi
echo ""

# 3. Check Docker (optional for local testing)
log_info "Checking Docker..."
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version | grep -oP '\d+\.\d+\.\d+' | head -1)
    log_success "Docker $DOCKER_VERSION detected"
else
    log_warning "Docker not found (optional, needed for local container testing)"
fi
echo ""

# 4. Create project structure
log_info "Creating project structure..."

DIRECTORIES=(
    "src"
    "scripts"
    "config"
    "calibration"
    "data/planning"
    "data/snapshots"
    "data/analyses"
    "data/results"
    "excel"
    "logs"
    "tests"
    ".github/workflows"
)

for DIR in "${DIRECTORIES[@]}"; do
    if [ ! -d "$DIR" ]; then
        mkdir -p "$DIR"
        log_info "  Created: $DIR"
    fi
done

log_success "Project structure ready"
echo ""

# 5. Check required files
log_info "Checking required files..."

REQUIRED_FILES=(
    "requirements.txt"
    "Dockerfile"
    "gunicorn.conf.py"
    "start.sh"
)

MISSING_FILES=()
for FILE in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$FILE" ]; then
        MISSING_FILES+=("$FILE")
        log_warning "  Missing: $FILE"
    fi
done

if [ ${#MISSING_FILES[@]} -eq 0 ]; then
    log_success "All required files present"
else
    log_warning "${#MISSING_FILES[@]} required file(s) missing"
fi
echo ""

# 6. Setup Python virtual environment
log_info "Setting up Python virtual environment..."

if [ ! -d "venv" ]; then
    python -m venv venv
    log_success "Virtual environment created"
else
    log_info "Virtual environment already exists"
fi

# Activate venv
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    log_success "Virtual environment activated"
elif [ -f "venv/Scripts/activate" ]; then
    # Windows Git Bash
    source venv/Scripts/activate
    log_success "Virtual environment activated"
else
    log_warning "Could not activate virtual environment"
fi
echo ""

# 7. Install Python dependencies
log_info "Installing Python dependencies..."

if [ -f "requirements.txt" ]; then
    pip install --upgrade pip setuptools wheel > /dev/null 2>&1
    pip install -r requirements.txt
    log_success "Dependencies installed"
else
    log_error "requirements.txt not found"
    exit 1
fi
echo ""

# 8. Setup environment file
log_info "Setting up environment configuration..."

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        log_success ".env created from .env.example"
        log_warning "Please edit .env with your configuration"
    else
        log_warning ".env.example not found, creating basic .env"
        cat > .env << 'EOF'
# Google Cloud Configuration
PROJECT_ID=your-project-id
REGION=europe-west1
SERVICE_NAME=hippique-orchestrator
SERVICE_ACCOUNT=hippique-sa@your-project-id.iam.gserviceaccount.com

# Storage
GCS_BUCKET=your-bucket-name
GCS_PREFIX=hippiques/prod

# Security
REQUIRE_AUTH=true

# Application
DATA_DIR=/tmp/data
BUDGET=5.0
EV_MIN=0.40
ROI_MIN=0.25
EOF
        log_success "Basic .env created"
    fi
else
    log_info ".env already exists"
fi
echo ""

# 9. Check calibration files
log_info "Checking calibration files..."

CALIBRATION_FILES=(
    "calibration/payout_calibration.yaml"
    "calibration/probabilities.yaml"
)

MISSING_CAL=()
for FILE in "${CALIBRATION_FILES[@]}"; do
    if [ ! -f "$FILE" ]; then
        MISSING_CAL+=("$FILE")
        log_warning "  Missing: $FILE"
    fi
done

if [ ${#MISSING_CAL[@]} -eq 0 ]; then
    log_success "Calibration files present"
else
    log_warning "${#MISSING_CAL[@]} calibration file(s) missing"
    log_warning "These are needed for EV/ROI calculations"
fi
echo ""

# 10. Check scripts executability
log_info "Setting script permissions..."

if [ -d "scripts" ]; then
    chmod +x scripts/*.sh 2>/dev/null || true
    log_success "Scripts made executable"
fi

if [ -f "start.sh" ]; then
    chmod +x start.sh
fi
echo ""

# 11. Validate Python imports
log_info "Validating Python modules..."

python << 'PYEOF'
import sys
import importlib

modules = [
    'fastapi',
    'pydantic',
    'requests',
    'bs4',
    'pandas',
    'google.cloud.tasks',
    'google.cloud.scheduler',
    'google.cloud.storage',
]

missing = []
for mod in modules:
    try:
        importlib.import_module(mod.split('.')[0])
    except ImportError:
        missing.append(mod)

if missing:
    print(f"⚠️  Missing modules: {', '.join(missing)}")
    sys.exit(1)
else:
    print("✅ All required modules available")
PYEOF

if [ $? -eq 0 ]; then
    log_success "Python modules validated"
else
    log_error "Some Python modules are missing"
    log_info "Run: pip install -r requirements.txt"
fi
echo ""

# 12. Git setup
log_info "Checking Git configuration..."

if [ -d ".git" ]; then
    log_success "Git repository initialized"
    
    # Check .gitignore
    if [ ! -f ".gitignore" ]; then
        log_warning "Creating .gitignore..."
        cat > .gitignore << 'EOF'
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
env/
ENV/

# Environment
.env
.env.local
credentials.json
*.key
*.pem

# Data
data/
logs/
*.log
*.xlsx
*.csv
!excel/modele_suivi_courses_hippiques.xlsx

# IDEs
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Build
build/
dist/
*.egg-info/
EOF
        log_success ".gitignore created"
    fi
else
    log_warning "Not a Git repository"
    log_info "Initialize with: git init"
fi
echo ""

# 13. Summary and next steps
echo "═══════════════════════════════════════════════════════"
echo "  🎉 Initialization Complete!"
echo "═══════════════════════════════════════════════════════"
echo ""

log_success "Project initialized successfully"
echo ""

echo "📋 Next Steps:"
echo ""
echo "1️⃣  Edit configuration:"
echo "   nano .env"
echo ""
echo "2️⃣  Test locally:"
echo "   make test"
echo "   # or: ./scripts/test_local.sh"
echo ""
echo "3️⃣  Setup GCP infrastructure:"
echo "   export PROJECT_ID=your-project-id"
echo "   export BUCKET_NAME=your-bucket-name"
echo "   make setup"
echo "   # or: ./scripts/setup_gcp.sh"
echo ""
echo "4️⃣  Deploy to Cloud Run:"
echo "   make deploy"
echo "   # or: ./scripts/deploy_cloud_run.sh"
echo ""
echo "5️⃣  Create daily scheduler:"
echo "   make scheduler"
echo "   # or: ./scripts/create_scheduler_0900.sh"
echo ""
echo "📚 Documentation:"
echo "   - README.md - General documentation"
echo "   - CLOUD_RUN_DEPLOYMENT.md - Cloud Run guide"
echo "   - DEPLOYMENT_CHECKLIST.md - Step-by-step checklist"
echo ""
echo "💡 Tips:"
echo "   - Run 'make help' to see all available commands"
echo "   - Check logs with 'make logs'"
echo "   - Test endpoints with 'make test-health'"
echo ""
echo "═══════════════════════════════════════════════════════"
