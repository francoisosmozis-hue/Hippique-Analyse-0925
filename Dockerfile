# ==============================================================================
# Dockerfile - Hippique Orchestrator GPI v5.2 (Optimized - Final)
# ==============================================================================

# Use an official Python runtime as a parent image
FROM python:3.12-slim as base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app
RUN apt-get update && apt-get install -y ca-certificates tzdata curl && rm -rf /var/lib/apt/lists/*

# --- Builder Stage ---
# This stage builds the Python wheels
FROM base as builder
RUN pip install --upgrade pip
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt

FROM base

# Create the non-root user first
RUN addgroup --system appuser && adduser --system --ingroup appuser appuser

# Copy installed dependencies from the builder stage
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache /wheels/*

# Copy the application source code
COPY . .
COPY templates /app/hippique_orchestrator/templates
COPY static /app/static

# Set permissions for the entrypoint BEFORE changing user
RUN chmod +x /app/entrypoint.sh

# Change ownership of all application files to the non-root user
RUN chown -R appuser:appuser /app

# Switch to the non-root user
USER appuser

# Expose port and set health check
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run the application
ENTRYPOINT ["/app/entrypoint.sh"]
CMD []