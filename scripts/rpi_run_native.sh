#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${1:-configs/pipeline.rpi.toml}"
DURATION="${DURATION:-3600}"
MODE="${MODE:-active}"

cd "$ROOT_DIR"
. .venv/bin/activate
python -m edge_assistant.main --config "$CONFIG" --mode "$MODE" --duration "$DURATION"
