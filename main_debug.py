import logging
from fastapi import FastAPI
import sys

# Setup basic logging to ensure we see something
logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    logger.info("--- Debug App Startup ---")
    logger.info("This is a minimal application for debugging purposes.")
    logger.info("If you see this log, the basic server (Gunicorn/Uvicorn) is working.")

@app.get("/health")
def health_check():
    logger.info("Health check endpoint was called successfully.")
    return {"status": "ok from debug"}

logger.info("--- main_debug.py has been loaded ---")
