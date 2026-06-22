#!/usr/bin/env bash
# Start the Precedent Database locally. Creates a venv and installs deps on first run.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating virtualenv (.venv) ..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

# Load .env if present so ANTHROPIC_API_KEY / PRECEDENTS_ARCHIVE_DIR are available.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PORT="${PORT:-8765}"
echo "Precedent Database running at http://127.0.0.1:${PORT}"
exec uvicorn server.main:app --host 127.0.0.1 --port "${PORT}" "$@"
