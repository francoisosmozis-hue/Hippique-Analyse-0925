<<<<<<< HEAD
# Dockerfile for Cloud Run - Hippique Orchestrator
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
=======
# ==============================================================================
# Dockerfile - Hippique Orchestrator GPI v5.1
# ==============================================================================

FROM python:3.11-slim

# Metadata
LABEL maintainer="Hippique Analysis Team"
LABEL description="Cloud Run service for automated horse racing analysis"
LABEL version="5.1.0"

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Europe/Paris \
    PORT=8080

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    tzdata \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set timezone
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Create app user (non-root)
RUN useradd -m -u 1000 -s /bin/bash appuser

# Set working directory
WORKDIR /app

# Copy requirements first (for layer caching)
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
<<<<<<< HEAD
COPY src/ src/
COPY scripts/ scripts/
COPY calibration/ calibration/
COPY config/ config/
COPY start.sh .
COPY gunicorn.conf.py .

# Create data directory
RUN mkdir -p /tmp/data

# Make start script executable
RUN chmod +x start.sh

# Set environment
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
=======
COPY . .

# Create necessary directories
RUN mkdir -p /app/data /app/logs /app/config && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)

# Expose port
EXPOSE 8080

# Health check
<<<<<<< HEAD
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/healthz', timeout=2)"

# Run
CMD ["./start.sh"]
=======
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

# Start command using gunicorn with uvicorn workers
CMD ["gunicorn", "src.service:app", "-c", "gunicorn_conf.py"]
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
