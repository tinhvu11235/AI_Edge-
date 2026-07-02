#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMORY="${1:-4g}"
IMAGE="${IMAGE:-edge-voice-ptt-test:arm64}"

case "$MEMORY" in
  4g|8g) ;;
  *)
    echo "Usage: $0 [4g|8g]" >&2
    exit 1
    ;;
esac

mkdir -p "$ROOT/results" "$ROOT/models"

docker buildx build \
  --platform linux/arm64 \
  -t "$IMAGE" \
  -f "$ROOT/Dockerfile.arm64" \
  --load \
  "$ROOT"

docker run --rm \
  --platform linux/arm64 \
  --memory "$MEMORY" \
  --memory-swap "$MEMORY" \
  --cpus 4 \
  -e PYTHONPATH=/app/src \
  -v "$ROOT/results:/app/results" \
  -v "$ROOT/models:/app/models:ro" \
  "$IMAGE" \
  python benchmarks/benchmark_pipeline.py \
    --asr-backend simulated \
    --tts-backend simulated \
    --quant Q5 \
    --threads 2 \
    --duration 5 \
    --loops 20 \
    --out results/benchmark_sim.csv \
    --redact-transcript
