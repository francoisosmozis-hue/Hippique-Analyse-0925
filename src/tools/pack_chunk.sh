#!/usr/bin/env bash
set -euo pipefail
PROMPT_FILE="${1:?AUDIT_OR_PATCH_PROMPT.md}"
OUT="${2:-/dev/stdout}"
shift 2 || true

MAX_BYTES=${MAX_BYTES:-160000}  # ~40k tokens
tmp="$(mktemp)"
cat "$PROMPT_FILE" > "$tmp"
echo -e "\n---\nCONTEXTE CODE (tronqué si nécessaire):\n" >> "$tmp"

BYTES=$(wc -c < "$tmp")
for f in "$@"; do
  [ -f "$f" ] || continue
  echo -e "\n===== FICHIER: $f =====" >> "$tmp"
  # Numérote les lignes pour que l’IA référence précisément
  nl -ba "$f" >> "$tmp"
  BYTES=$(( BYTES + $(wc -c < "$f") ))
  if [ "$BYTES" -gt "$MAX_BYTES" ]; then
    echo -e "\n[TRONQUÉ: limite atteinte]" >> "$tmp"
    break
  fi
done

cat "$tmp" > "$OUT"
rm -f "$tmp"
