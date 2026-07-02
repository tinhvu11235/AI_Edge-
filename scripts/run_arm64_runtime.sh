#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MEMORY="${1:-4g}"
BACKEND="${2:-simulated}"
IMAGE="${IMAGE:-edge-voice-ptt-test:arm64}"

case "$MEMORY" in
  4g|8g) ;;
  *)
    echo "Usage: $0 [4g|8g] [simulated|real]" >&2
    exit 1
    ;;
esac

case "$BACKEND" in
  simulated)
    ASR_BACKEND="simulated"
    TTS_BACKEND="simulated"
    ;;
  real)
    ASR_BACKEND="whisper-cpp"
    TTS_BACKEND="piper"
    ;;
  *)
    echo "Usage: $0 [4g|8g] [simulated|real]" >&2
    exit 1
    ;;
esac

docker run --rm \
  --platform linux/arm64 \
  --memory "$MEMORY" \
  --memory-swap "$MEMORY" \
  --cpus 4 \
  -e PYTHONPATH=/app/src \
  -v "$ROOT/models:/app/models:ro" \
  "$IMAGE" \
  python -m edge_voice_test.runtime \
    --asr-backend "$ASR_BACKEND" \
    --tts-backend "$TTS_BACKEND" \
    --duration 2 \
    --loops 1 \
    --redact-transcript
