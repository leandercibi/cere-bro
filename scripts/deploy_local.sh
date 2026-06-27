#!/usr/bin/env bash
# Run Cerebro locally — creates venv, installs deps, starts the bot.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

cd "$ROOT"

if [[ ! -f ".env" ]]; then
    echo "ERROR: .env file not found. Copy .env.example (or create one from docs/ENV_VARS.md) and fill in your secrets."
    exit 1
fi

if [[ ! -d ".venv" ]]; then
    echo "Creating virtual environment..."
    python3.12 -m venv .venv
fi

source .venv/bin/activate
pip install -e ".[dev]" -q

echo "Starting Cerebro (Ctrl-C to stop)..."
exec cerebro
