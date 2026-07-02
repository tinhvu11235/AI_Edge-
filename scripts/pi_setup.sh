#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  alsa-utils \
  build-essential \
  cmake \
  git \
  libasound2 \
  libasound2-dev \
  ninja-build \
  pkg-config \
  procps

if getent group audio >/dev/null 2>&1; then
  sudo usermod -aG audio "$USER" || true
fi

if command -v raspi-config >/dev/null 2>&1; then
  echo "Raspberry Pi OS detected."
fi

if command -v cpufreq-set >/dev/null 2>&1; then
  sudo cpufreq-set -g performance || true
fi

echo "Setup complete. Re-login if your user was just added to the audio group."
