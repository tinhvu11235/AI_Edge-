# Raspberry Pi 5 ARM64 emulation plan

This project cannot claim real Raspberry Pi 5 performance without the board, but
it can still validate a realistic deployment shape:

- Linux ARM64 userland through Docker/QEMU.
- RAM pressure gates with 4 GB and 8 GB container limits.
- Real model artifacts downloaded into `models/`.
- Native ARM64 build path for `whisper.cpp`.
- Quantized Whisper Tiny artifacts produced from the downloaded model.
- Repeatable benchmark output under `results/`.

## What emulation proves

- The application can start in a Linux ARM64 environment.
- Python and native dependencies can be installed for ARM64.
- Model files exist at the paths the app expects.
- ASR/TTS models can be loaded once during startup.
- Repeated push-to-talk loops do not show obvious RAM growth under 4 GB or 8 GB.
- The packaging flow is deployable as a container or as commands that can be run
  later on Raspberry Pi OS 64-bit.

## What emulation does not prove

- Real Cortex-A76 throughput on Raspberry Pi 5.
- Real ARM NEON timing.
- Thermal throttling behavior.
- Microphone, speaker, ALSA/PulseAudio/PipeWire latency.
- GPIO/button timing.
- Final RTF for the physical robot.

QEMU timing must be reported as "ARM64 emulated", not as Pi 5 benchmark data.

## Minimum gates for the design tasks

1. Download real model artifacts:
   - Whisper Tiny multilingual model:
     `models/whisper/ggml-tiny.bin`
   - Piper Vietnamese voice:
     `models/piper/vi_VN-vais1000-medium/vi_VN-vais1000-medium.onnx`
     and its `.onnx.json` config.
2. Build `whisper.cpp` in a Linux ARM64 environment.
3. Quantize Whisper Tiny into at least `q8_0`, `q5_0`, and `q4_0`.
4. Run ARM64 emulation with both memory profiles:
   - `scripts/run_arm64_emulation.ps1 -Memory 4g`
   - `scripts/run_arm64_emulation.ps1 -Memory 8g`
5. Save CSV/JSON results under `results/` and label them as emulated.
6. Do not use the simulated RTF numbers to claim the KPI is met on Pi 5.

## Expected conclusion without a physical Pi

The strongest honest claim is:

"The project has a reproducible ARM64 deployment and model-preparation flow, and
passes memory/load-once checks under 4 GB and 8 GB ARM64 emulation. Final RTF and
audio I/O latency still require measurement on Raspberry Pi 5 hardware."

