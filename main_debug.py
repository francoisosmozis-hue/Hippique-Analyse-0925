import sys
from fastapi import FastAPI
from datetime import datetime

# Using basic print to stdout and stderr to ensure capture
print("--- [stdout] main_debug.py loading...", flush=True)
print("--- [stderr] main_debug.py loading...", file=sys.stderr, flush=True)

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    print("--- [stdout] Debug App Startup event ---", flush=True)
    print("--- [stderr] Debug App Startup event ---", file=sys.stderr, flush=True)

@app.get("/health")
def health_check():
    timestamp = datetime.now().isoformat()
    print(f"--- [stdout] Health check called at {timestamp} ---", flush=True)
    print(f"--- [stderr] Health check called at {timestamp} ---", file=sys.stderr, flush=True)
    return {"status": "ok from direct print debug"}

print("--- [stdout] main_debug.py loaded successfully ---", flush=True)
print("--- [stderr] main_debug.py loaded successfully ---", file=sys.stderr, flush=True)
