#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHISPER_MODEL="${WHISPER_MODEL:-tiny}"
WHISPER_DIR="$ROOT/models/whisper"
PIPER_DIR="$ROOT/models/piper/vi_VN-vais1000-medium"

mkdir -p "$WHISPER_DIR" "$PIPER_DIR"

fetch() {
  local url="$1"
  local out="$2"
  local part="${out}.part"

  if [ -s "$out" ]; then
    echo "Already exists: $out"
    return
  fi

  rm -f "$part"
  echo "Downloading $url"
  curl -L --fail --retry 3 --output "$part" "$url"
  mv "$part" "$out"
}

fetch \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-${WHISPER_MODEL}.bin" \
  "$WHISPER_DIR/ggml-${WHISPER_MODEL}.bin"

fetch \
  "https://huggingface.co/rhasspy/piper-voices/resolve/main/vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx" \
  "$PIPER_DIR/vi_VN-vais1000-medium.onnx"

fetch \
  "https://huggingface.co/rhasspy/piper-voices/resolve/main/vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium.onnx.json" \
  "$PIPER_DIR/vi_VN-vais1000-medium.onnx.json"

(
  cd "$ROOT/models"
  find . -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS.txt
)

echo "Wrote $ROOT/models/SHA256SUMS.txt"
