#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${IMAGE:-edge-voice-ptt-test:arm64}"
INSTALL_REAL_BACKENDS="${INSTALL_REAL_BACKENDS:-0}"

docker buildx build \
  --platform linux/arm64 \
  -t "$IMAGE" \
  -f "$ROOT/Dockerfile.arm64" \
  --build-arg "INSTALL_REAL_BACKENDS=$INSTALL_REAL_BACKENDS" \
  --load \
  "$ROOT"
