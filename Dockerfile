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
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
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

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8080/healthz', timeout=2)"

# Run
CMD ["./start.sh"]
