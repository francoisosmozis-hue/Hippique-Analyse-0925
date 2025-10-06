#!/usr/bin/env bash
# Orchestrate H-30 / H-5 processing for a day based on a planning file.
#
# The planning file is expected to contain one race per line using the
# following semi-colon separated format:
#
#   R1C3;Vincennes;Trot Attelé;https://www.zeturf.fr/fr/course/...
#
# Lines starting with a ``#`` or blank lines are ignored.  The script delegates
# the heavy lifting to helper functions.  Each helper can be overridden by
# defining the environment variables ``RUN_DAY_H30_CMD``/``RUN_DAY_H5_CMD`` and
# ``RUN_DAY_LOG_H30_CMD``/``RUN_DAY_LOG_H5_CMD``.  The placeholder ``{RC}``
# within these variables is substituted with the race identifier, ``{HIPPO}``
# with the hippodrome name, ``{DISC}`` with the discipline label and ``{URL}``
# with the race URL before executing the command.
#
# Example:
#   export RUN_DAY_H30_CMD='python analyse_courses_du_jour_enrichie.py \
#       --reunion-url {URL} --phase H30'
#   export RUN_DAY_H5_CMD='python analyse_courses_du_jour_enrichie.py \
#       --reunion-url {URL} --phase H5'
#
# With the environment configured, simply run ``./scripts/run_day.sh``.  The
# script logs each processed race and stops at the first command failure.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PLANNING_FILE="${PLANNING_FILE:-$ROOT_DIR/schedules.csv}"

# shellcheck disable=SC2034 # Allow future consumers to override the shell used
SHELL_BIN="${SHELL_BIN:-/bin/bash}"

# --- Helpers -----------------------------------------------------------------

_substitute_tokens() {
  local template="$1" rc="$2" hippo="$3" disc="$4" url="$5"
  template="${template//\{RC\}/$rc}"
  template="${template//\{HIPPO\}/$hippo}"
  template="${template//\{DISC\}/$disc}"
  template="${template//\{URL\}/$url}"
  printf '%s\n' "$template"
}

_run_cmd_if_defined() {
  local env_name="$1" rc="$2" hippo="$3" disc="$4" url="$5"
  local cmd_template
  cmd_template="${!env_name-}"
  if [[ -z "$cmd_template" ]]; then
    return 0
  fi
  local rendered
  rendered="$(_substitute_tokens "$cmd_template" "$rc" "$hippo" "$disc" "$url")"
  echo "[run_day] $env_name → $rendered"
  eval "$rendered"
}

_parse_line() {
  local line="$1"
  line="${line%$'\r'}"
  local separator=';'
  if [[ "$line" == *'|'* && "$line" != *';'* ]]; then
    separator='|'
  elif [[ "$line" == *$'\t'* && "$line" != *';'* ]]; then
    separator=$'\t'
  fi
  local rc hippo disc url extra
  IFS="$separator" read -r rc hippo disc url extra <<<"$line"
  rc="${rc:-}"
  hippo="${hippo:-}"
  disc="${disc:-}"
  url="${url:-${extra:-}}"
  printf '%s\t%s\t%s\t%s\n' "$rc" "$hippo" "$disc" "$url"
}

_norm() {
  local value="$1"
  local cleaned
  cleaned="${value//[[:space:]]/}"
  cleaned="${cleaned^^}"
  if [[ "$cleaned" =~ ^R?([0-9]+)C?([0-9]+)$ ]]; then
    printf 'R%uC%u\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
    return
  fi
  printf '%s\n' "$cleaned"
}

_run_h30() {
  local rc="$1" url="$2"
  echo "[run_day] H30 → $rc"
  _run_cmd_if_defined RUN_DAY_H30_CMD "$rc" "${3:-}" "${4:-}" "$url"
}

_log_h30_excel() {
  local rc="$1" hippo="$2" disc="$3"
  _run_cmd_if_defined RUN_DAY_LOG_H30_CMD "$rc" "$hippo" "$disc" "${4:-}"
}

_run_h5() {
  local rc="$1" url="$2"
  echo "[run_day] H5  → $rc"
  _run_cmd_if_defined RUN_DAY_H5_CMD "$rc" "${3:-}" "${4:-}" "$url"
}

_log_h5_excel_from_json() {
  local rc="$1" hippo="$2" disc="$3"
  _run_cmd_if_defined RUN_DAY_LOG_H5_CMD "$rc" "$hippo" "$disc" "${4:-}"
}

main() {
  test -f "$PLANNING_FILE" || { echo "Planning introuvable: $PLANNING_FILE"; exit 1; }

  while IFS= read -r LINE; do
    [[ -z "$LINE" || "$LINE" =~ ^# ]] && continue

    # Déstructure proprement la ligne via la fonction _parse_line
    read RC HIPPO DISC URL < <(_parse_line "$LINE")

    RC="$(_norm "$RC")"
    HIPPO="$(echo "$HIPPO" | sed 's/^ *//;s/ *$//')"
    DISC="$(echo "$DISC" | sed 's/^ *//;s/ *$//')"

    echo "=== TRAITEMENT $RC | $HIPPO | $DISC ==="
    _run_h30 "$RC" "$URL"
    _log_h30_excel "$RC" "$HIPPO" "$DISC"

    _run_h5 "$RC" "$URL"
    _log_h5_excel_from_json "$RC" "$HIPPO" "$DISC"

    echo "=== OK $RC ==="
  done < "$PLANNING_FILE"
}

main "$@"
