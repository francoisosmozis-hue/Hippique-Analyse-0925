# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

RUN python - <<'PY'
from pathlib import Path
source = Path('requirements.txt')
target = Path('requirements.clean.txt')
lines = []
for raw in source.read_text().splitlines():
    stripped = raw.strip()
    if not stripped or stripped.startswith('#'):
        continue
    if stripped.startswith('touch ') or stripped.startswith('grep -q'):
        continue
    lines.append(stripped)
if lines:
    target.write_text('\n'.join(lines) + '\n')
else:
    target.write_text('')
PY

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.clean.txt \
    && pip install --no-cache-dir 'functions-framework==3.*'

COPY . .

EXPOSE 8080

CMD ["functions-framework", "--target", "run_hminus", "--source", "cloud/app.py", "--port", "8080"]
