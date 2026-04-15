#!/usr/bin/env bash
# Production-style serve on Linux (Gunicorn). Binds 0.0.0.0:5009 by default.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .venv/bin/activate ]]; then
  echo "Run scripts/install-linux.sh first."
  exit 1
fi

# shellcheck source=/dev/null
source .venv/bin/activate

BIND="${BIND:-0.0.0.0:5009}"
WORKERS="${WORKERS:-1}"
THREADS="${THREADS:-8}"
TIMEOUT="${TIMEOUT:-300}"

exec gunicorn \
  --bind "$BIND" \
  --workers "$WORKERS" \
  --threads "$THREADS" \
  --timeout "$TIMEOUT" \
  --access-logfile - \
  --error-logfile - \
  app:app
