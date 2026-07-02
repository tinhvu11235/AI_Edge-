#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-active}"
DURATION="${2:-60}"

docker run --rm --platform linux/arm64 \
  -v "$PWD/outputs:/opt/edge-assistant/outputs" \
  ai-edge-assistant:pi-sim \
  python -m benchmarks.bench_pipeline \
  --config configs/pipeline.sim.toml \
  --mode "$MODE" \
  --duration "$DURATION" \
  --out "outputs/benchmark.${MODE}.docker.json"
