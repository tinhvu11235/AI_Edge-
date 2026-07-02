#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip portaudio19-dev alsa-utils

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "Native environment ready at $ROOT_DIR/.venv"
echo "Optional microphone deps: python -m pip install -r requirements-pi.txt"
echo "Smoke test: python -m benchmarks.bench_pipeline --config configs/pipeline.sim.toml --mode active --duration 30"
