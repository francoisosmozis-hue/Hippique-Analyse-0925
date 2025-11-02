import uvicorn
import sys

if __name__ == "__main__":
    sys.stdout = open('server.log', 'w')
    sys.stderr = sys.stdout
    uvicorn.run("src.service:app", host="0.0.0.0", port=8080, reload=True)