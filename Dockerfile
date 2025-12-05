# ==============================================================================
# Dockerfile - Hippique Orchestrator GPI v5.1
# ==============================================================================

# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

ENV PYTHONPATH=/app

# Install system dependencies, including gnupg for key management
RUN apt-get update && apt-get install -y ca-certificates tzdata curl && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
# Create a non-root user to run the application
RUN addgroup --system appuser && adduser --system --ingroup appuser appuser



# Copy the rest of the application code
COPY . .

# Create necessary directories and change ownership
RUN mkdir -p /app/data /app/logs /app/config && chown -R appuser:appuser /app

# Switch to the non-root user
USER appuser

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/healthz || exit 1

# Run the application
CMD uvicorn hippique_orchestrator.service:app --host 0.0.0.0 --port $PORT --log-level info