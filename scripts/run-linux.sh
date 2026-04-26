#!/usr/bin/env bash
# Production-style serve on Linux (Gunicorn). Binds 0.0.0.0:5009 by default.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Do not run this script with sudo/root."
  echo "Playwright Firefox requires a HOME owned by the current user."
  echo "Run as your normal user: ./scripts/run-linux.sh"
  exit 1
fi

if [[ ! -f .venv/bin/activate ]]; then
  echo "Run scripts/install-linux.sh first."
  exit 1
fi

# shellcheck source=/dev/null
source .venv/bin/activate

if [[ -f .env ]]; then
  tmp_env="$(mktemp)"
  trap 'rm -f "$tmp_env"' EXIT
  tr -d '\r' < .env > "$tmp_env"
  set -a
  # shellcheck source=/dev/null
  source "$tmp_env"
  set +a
fi

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
