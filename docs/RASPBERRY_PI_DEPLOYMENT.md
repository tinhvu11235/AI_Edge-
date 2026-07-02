# Trien khai Docker va Raspberry Pi native

## 1. Docker ARM64 gan Raspberry Pi OS

Build:

```bash
docker buildx build --platform linux/arm64 -f docker/Dockerfile.pi-sim -t ai-edge-assistant:pi-sim --load .
```

Run active benchmark:

```bash
docker run --rm --platform linux/arm64 \
  -v "$PWD/outputs:/opt/edge-assistant/outputs" \
  ai-edge-assistant:pi-sim
```

Run background:

```bash
docker run --rm --platform linux/arm64 ai-edge-assistant:pi-sim \
  python -m benchmarks.bench_pipeline \
  --config configs/pipeline.sim.toml \
  --mode background \
  --duration 60
```

## 2. Native Raspberry Pi

Copy repo len Pi:

```bash
rsync -av --exclude .git ./ pi@raspberrypi.local:/home/pi/ai-edge-assistant/
ssh pi@raspberrypi.local
cd /home/pi/ai-edge-assistant
```

Cai dat:

```bash
chmod +x scripts/rpi_install_native.sh scripts/rpi_run_native.sh
./scripts/rpi_install_native.sh
```

Smoke test khong microphone:

```bash
python -m benchmarks.bench_pipeline --config configs/pipeline.sim.toml --mode active --duration 30
```

Run voi microphone:

```bash
./scripts/rpi_run_native.sh configs/pipeline.rpi.toml
```

## 3. ALSA/microphone check

```bash
arecord -l
arecord -D default -f S16_LE -r 16000 -c 1 -d 5 /tmp/test.wav
aplay /tmp/test.wav
```

Neu microphone khong nam o `default`, sua:

```toml
[audio]
device = "hw:1,0"
```

## 4. Service systemd

Sua `WorkingDirectory` va `ExecStart` trong:

```text
deploy/systemd/ai-edge-assistant.service
```

Sau do:

```bash
sudo cp deploy/systemd/ai-edge-assistant.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-edge-assistant.service
sudo journalctl -u ai-edge-assistant.service -f
```

## 5. Gan model that

Thu tu nen lam:

1. Chay pipeline mock tren Pi va dat nguong CPU.
2. Thay VAD bang WebRTC VAD hoac Silero VAD.
3. Thay ASR bang SenseVoiceSmall, giu interface `transcribe(pcm16le, sample_rate)`.
4. Thay TTS bang Valtec-TTS/VieNeu, giu interface `synthesize(text, urgent)`.
5. Chay lai benchmark background, active, backpressure va soak.

Khong nen gan tat ca model that cung luc ngay tu dau, vi rat kho biet thanh phan nao lam
vuot nguong CPU.
