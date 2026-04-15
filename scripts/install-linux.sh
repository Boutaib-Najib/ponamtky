#!/usr/bin/env bash
# Install news-classifier on Linux (Debian/Ubuntu/RHEL-style).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
PIP="$ROOT/.venv/bin/pip"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. On Debian/Ubuntu: sudo apt install python3 python3-venv python3-pip"
  exit 1
fi

python3 -m venv .venv
"$PIP" install -U pip
"$PIP" install -r requirements.txt

echo "Installing Playwright Firefox browser..."
"$PY" -m playwright install firefox

echo "Installing OS libraries for headless Firefox (needs sudo)..."
if command -v sudo >/dev/null 2>&1; then
  sudo "$PY" -m playwright install-deps firefox
else
  echo "Warning: install deps as root if Firefox fails in headless mode:"
  echo "  sudo $PY -m playwright install-deps firefox"
fi

echo ""
echo "Done. Next:"
echo "  source .venv/bin/activate"
echo "  cp -n .env.example .env   # then edit OPENAI_API_KEY"
echo "  ./scripts/run-linux.sh"
