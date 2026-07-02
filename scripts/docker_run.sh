#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS="$ROOT/benchmark_results"
mkdir -p "$RESULTS"

docker run --rm \
  --platform linux/arm64/v8 \
  -v "$RESULTS:/app/results" \
  ai-edge-pi5-voice:local \
  --audio=null \
  --iterations=5 \
  --out=/app/results/benchmark.jsonl
