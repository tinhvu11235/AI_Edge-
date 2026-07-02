#!/usr/bin/env bash
set -euo pipefail

BIN="${BIN:-/app/edge_voice_pipeline}"
OUT_DIR="${OUT_DIR:-/app/results}"
mkdir -p "$OUT_DIR"

"$BIN" \
  --audio="${AUDIO_BACKEND:-null}" \
  --alsa-device="${ALSA_DEVICE:-default}" \
  --iterations="${ITERATIONS:-20}" \
  --period-ms="${PERIOD_MS:-20}" \
  --buffer-ms="${BUFFER_MS:-120}" \
  --jitter-ms="${JITTER_MS:-60}" \
  --out="$OUT_DIR/benchmark.jsonl"

"$BIN" \
  --audio="${AUDIO_BACKEND:-null}" \
  --scenario=barge_in \
  --iterations="${BARGE_ITERATIONS:-10}" \
  --barge-in-ms="${BARGE_IN_MS:-450}" \
  --out="$OUT_DIR/benchmark_barge.jsonl"
