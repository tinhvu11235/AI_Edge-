#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
BUILD_TAG="ai-edge-pi5-voice:build-$(date +%s)"

docker buildx build \
  --platform linux/arm64/v8 \
  -f docker/Dockerfile.pi5 \
  -t "$BUILD_TAG" \
  --load \
  .

docker image tag "$BUILD_TAG" ai-edge-pi5-voice:local
