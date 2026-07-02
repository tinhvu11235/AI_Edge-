#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cmake -S . -B build-pi -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DEDGEVOICE_WITH_ALSA=ON
cmake --build build-pi --target edge_voice_pipeline

mkdir -p benchmark_results
./build-pi/edge_voice_pipeline \
  --audio=alsa \
  --alsa-device="${ALSA_DEVICE:-default}" \
  --iterations="${ITERATIONS:-20}" \
  --period-ms="${PERIOD_MS:-20}" \
  --buffer-ms="${BUFFER_MS:-120}" \
  --jitter-ms="${JITTER_MS:-60}" \
  --split-min-tokens="${SPLIT_MIN_TOKENS:-4}" \
  --split-max-tokens="${SPLIT_MAX_TOKENS:-16}" \
  --out=benchmark_results/pi_native_alsa.jsonl
