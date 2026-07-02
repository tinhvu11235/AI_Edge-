#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHISPER_CPP_DIR="$ROOT/third_party/whisper.cpp"
JOBS="${JOBS:-$(nproc)}"

for tool in git cmake; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing required tool: $tool" >&2
    exit 1
  fi
done

mkdir -p "$ROOT/third_party"

if [ ! -d "$WHISPER_CPP_DIR/.git" ]; then
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "$WHISPER_CPP_DIR"
else
  echo "Using existing $WHISPER_CPP_DIR"
fi

cmake -S "$WHISPER_CPP_DIR" -B "$WHISPER_CPP_DIR/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$WHISPER_CPP_DIR/build" -j "$JOBS" --config Release

echo "Built whisper.cpp binaries under $WHISPER_CPP_DIR/build/bin"

