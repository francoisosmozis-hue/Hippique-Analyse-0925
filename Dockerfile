# ==============================================================================
# Dockerfile - Hippique Orchestrator GPI v5.1
# ==============================================================================

# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies, including gnupg for key management
RUN apt-get update && apt-get install -y wget gnupg ca-certificates tzdata curl

# Add Google's official GPG key using the recommended, modern method
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg

# Add the Google Chrome repository and sign it with the key
RUN echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list

# Install Google Chrome Stable
RUN apt-get update && apt-get install -y google-chrome-stable

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
    CMD curl -f http://localhost:8080/health || exit 1

# Run the application
CMD exec gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:$PORT src.service:app