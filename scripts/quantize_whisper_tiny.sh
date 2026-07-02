#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHISPER_MODEL="${WHISPER_MODEL:-tiny}"
QUANTS="${WHISPER_QUANTS:-q8_0 q5_0 q4_0}"
MODEL_IN="$ROOT/models/whisper/ggml-${WHISPER_MODEL}.bin"
QUANTIZE_BIN="${QUANTIZE_BIN:-$ROOT/third_party/whisper.cpp/build/bin/whisper-quantize}"

if [ ! -s "$MODEL_IN" ]; then
  echo "Missing model: $MODEL_IN" >&2
  echo "Run scripts/download_models.sh first." >&2
  exit 1
fi

if [ ! -x "$QUANTIZE_BIN" ] && [ -x "$ROOT/third_party/whisper.cpp/build/bin/quantize" ]; then
  QUANTIZE_BIN="$ROOT/third_party/whisper.cpp/build/bin/quantize"
fi

if [ ! -x "$QUANTIZE_BIN" ]; then
  echo "Missing quantize binary: $QUANTIZE_BIN" >&2
  echo "Run scripts/build_whisper_cpp.sh first." >&2
  exit 1
fi

for quant in $QUANTS; do
  out="$ROOT/models/whisper/ggml-${WHISPER_MODEL}-${quant}.bin"
  if [ -s "$out" ]; then
    echo "Already exists: $out"
    continue
  fi
  "$QUANTIZE_BIN" "$MODEL_IN" "$out" "$quant"
done

(
  cd "$ROOT/models"
  find . -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS.txt
)

echo "Quantized Whisper model(s). Updated $ROOT/models/SHA256SUMS.txt"
