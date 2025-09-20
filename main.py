import os
from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def root():
    return {"ok": True, "app": "Hippique Analyse GPI v5.1"}


if __name__ == "__main__":
    # IMPORTANT : lit PORT fourni par Cloud Run (fallback 8080)
    port = int(os.getenv("PORT", "8080"))
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=port)
