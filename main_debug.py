import logging
import sys
from fastapi import FastAPI
import google.cloud.logging

# Instantiates a client
client = google.cloud.logging.Client()

# Retrieves a Cloud Logging handler and sets it up as the default handler
# This is the recommended way to log from GKE, GCF, and Cloud Run
client.setup_logging()

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    logging.info("--- Debug App with Google Cloud Logging Startup ---")
    logging.info("If you see this, the new logging configuration is working.")

@app.get("/health")
def health_check():
    logging.info("Health check endpoint was called successfully (via google-cloud-logging).")
    return {"status": "ok from debug"}

logging.info("--- main_debug.py with google-cloud-logging has been loaded ---")
