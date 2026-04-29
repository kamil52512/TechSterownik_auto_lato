#!/usr/bin/env bash
set -euo pipefail

HISTORY_FILE="${HISTORY_FILE:-logs/history.json}"

if [ ! -f "$HISTORY_FILE" ]; then
  echo "Brak pliku historii: $HISTORY_FILE"
  exit 0
fi

python3 -m json.tool "$HISTORY_FILE"
