# modules/tickets_store.py
from __future__ import annotations
import os, json, datetime
from pathlib import Path
from typing import Dict, Any, Optional
from jinja2 import Template
from google.cloud import storage

TICKETS_BUCKET = os.environ.get("TICKETS_BUCKET")
TICKETS_PREFIX = os.environ.get("TICKETS_PREFIX", "tickets")

_HTML_TMPL = Template("""<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ticket {{ reunion }}{{ course }} – {{ date_str }}</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:900px;margin:32px auto;padding:0 16px;}
 h1{margin:0 0 8px} .meta{color:#555;margin-bottom:16px}
 pre{background:#f6f8fa;padding:12px;border-radius:8px;overflow:auto}
 .card{border:1px solid #e4e7eb;border-radius:12px;padding:16px;margin:12px 0}
 .grid{display:grid;gap:12px}
</style></head><body>
<h1>Ticket {{ reunion }}{{ course }}</h1>
<div class="meta">Date: {{ date_str }} – Phase: {{ phase }}</div>

<div class="card">
  <h3>Résumé</h3>
  <div class="grid">
    <div><b>Réunion:</b> {{ reunion }}</div>
    <div><b>Course:</b> {{ course }}</div>
    <div><b>Budget:</b> {{ budget }} €</div>
    <div><b>EV estimée:</b> {{ ev or "n/a" }}</div>
    <div><b>ROI estimé:</b> {{ roi or "n/a" }}</div>
  </div>
</div>

<div class="card">
  <h3>Tickets</h3>
  <pre>{{ tickets_pre }}</pre>
</div>

<div class="card">
  <h3>Snapshot (brut)</h3>
  <pre>{{ payload_pre }}</pre>
</div>

</body></html>
""")

_INDEX_TMPL = Template("""<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tickets – index</title>
<style>
 body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:900px;margin:32px auto;padding:0 16px;}
 h1{margin:0 0 16px}
 ul{line-height:1.8}
 .muted{color:#666}
</style></head><body>
<h1>Tickets disponibles</h1>
<ul>
{% for item in items %}
  <li><a href="/tickets/{{ item.date }}/{{ item.key }}.html">{{ item.date }} – {{ item.key }}</a>
      <span class="muted">({{ item.size }} octets)</span></li>
{% endfor %}
</ul>
</body></html>
""")

def _client() -> storage.Client:
    return storage.Client()

def _blob_path(date_str: str, rxcy: str) -> str:
    return f"{TICKETS_PREFIX}/{date_str}/{rxcy}.html"

def _index_path() -> str:
    return f"{TICKETS_PREFIX}/index.html"

def render_ticket_html(payload: Dict[str, Any], *, reunion: str, course: str, phase: str, budget: float) -> str:
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    ev = payload.get("ev") or payload.get("ev_global")
    roi = payload.get("roi") or payload.get("roi_estime")
    tickets = payload.get("tickets") or payload.get("ticket") or []
    return _HTML_TMPL.render(
        reunion=reunion, course=course, phase=phase, budget=budget,
        date_str=date_str,
        ev=ev, roi=roi,
        tickets_pre=json.dumps(tickets, ensure_ascii=False, indent=2),
        payload_pre=json.dumps(payload, ensure_ascii=False, indent=2),
    )

def save_ticket_html(html: str, *, date_str: str, rxcy: str) -> None:
    assert TICKETS_BUCKET, "TICKETS_BUCKET non défini"
    bkt = _client().bucket(TICKETS_BUCKET)
    blob = bkt.blob(_blob_path(date_str, rxcy))
    blob.cache_control = "no-cache"
    blob.content_type = "text/html; charset=utf-8"
    blob.upload_from_string(html, content_type=blob.content_type)

def build_and_save_ticket(payload: Dict[str, Any], *, reunion: str, course: str, phase: str, budget: float) -> str:
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    rxcy = f"{reunion}{course}"
    html = render_ticket_html(payload, reunion=reunion, course=course, phase=phase, budget=budget)
    save_ticket_html(html, date_str=date_str, rxcy=rxcy)
    return f"{date_str}/{rxcy}.html"

def list_ticket_objects(limit: int = 200) -> list[dict]:
    assert TICKETS_BUCKET, "TICKETS_BUCKET non défini"
    cli = _client()
    bkt = cli.bucket(TICKETS_BUCKET)
    blobs = list(cli.list_blobs(bkt, prefix=f"{TICKETS_PREFIX}/", max_results=limit))
    items = []
    for bl in blobs:
        name = bl.name
        if not name.endswith(".html") or name.endswith("index.html"):
            continue
        # …/tickets/YYYY-MM-DD/R1C3.html
        parts = name.split("/")
        if len(parts) >= 3:
            date_str = parts[-2]
            key = parts[-1].replace(".html", "")
            items.append({"date": date_str, "key": key, "size": bl.size or 0})
    # plus récent en premier
    items.sort(key=lambda x: (x["date"], x["key"]), reverse=True)
    return items

def rebuild_index() -> None:
    items = list_ticket_objects()
    html = _INDEX_TMPL.render(items=items)
    assert TICKETS_BUCKET, "TICKETS_BUCKET non défini"
    bkt = _client().bucket(TICKETS_BUCKET)
    blob = bkt.blob(_index_path())
    blob.cache_control = "no-cache"
    blob.content_type = "text/html; charset=utf-8"
    blob.upload_from_string(html, content_type=blob.content_type)

def load_ticket_html(date_str: str, rxcy: str) -> str:
    assert TICKETS_BUCKET, "TICKETS_BUCKET non défini"
    bkt = _client().bucket(TICKETS_BUCKET)
    blob = bkt.blob(_blob_path(date_str, rxcy))
    return blob.download_as_text(encoding="utf-8")
