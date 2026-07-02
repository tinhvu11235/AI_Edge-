# Deployment Plan

## Giai đoạn 1 - Docker tương đương Raspberry Pi OS

Mục tiêu: kiểm thử pipeline trên Linux ARM64 Bookworm, cùng họ với Raspberry Pi OS hiện đại.

Lệnh:

```powershell
.\scripts\docker_build.ps1
.\scripts\docker_run.ps1
```

Docker image dùng:

- `debian:bookworm-slim`
- `linux/arm64/v8`
- `build-essential`, `cmake`, `ninja-build`, `libasound2-dev`

Ở Windows hoặc máy không có audio device Linux, chạy `--audio=null`. Chế độ này vẫn đo được ASR partial, splitter, TTS worker giả lập, jitter scheduling, TTFT và timeout underrun ở mức pipeline.

## Giai đoạn 2 - Docker có ALSA trên Linux host

Mục tiêu: kiểm tra đường audio native trong container khi host có `/dev/snd`.

```bash
mkdir -p benchmark_results
./scripts/docker_build.sh
docker compose -f docker/compose.yml run --rm --no-build edge-voice-alsa
```

Điều kiện:

- Host là Linux.
- User có quyền audio hoặc container được cấp `--device /dev/snd`.
- Kiểm tra thiết bị bằng `aplay -L`.

## Giai đoạn 3 - Native Raspberry Pi 5

Mục tiêu: build và chạy trực tiếp trên Pi 5 ARM64, không phụ thuộc container.

```bash
chmod +x scripts/*.sh
./scripts/pi_setup.sh
./scripts/pi_build_run.sh
```

Sau khi có thiết bị cụ thể:

```bash
ALSA_DEVICE=hw:0,0 PERIOD_MS=20 BUFFER_MS=120 JITTER_MS=60 ./scripts/pi_build_run.sh
```

## Giai đoạn 4 - Tích hợp model thật

Thứ tự tích hợp:

1. Thay ASR simulator bằng Zipformer multilingual streaming hoặc Whisper Tiny streaming wrapper.
2. Giữ nguyên contract partial text: callback phải đưa text vào splitter ngay khi có partial ổn định.
3. Thay TTS sine generator bằng Valtec-TTS streaming, output PCM S16_LE mono hoặc stereo thống nhất với ALSA config.
4. Giữ nguyên jitter buffer và ALSA sink để benchmark không đổi trước/sau khi thay model.

## Tiêu chí go/no-go

- Docker null sink chạy ổn định 20 iteration, không crash.
- Native Pi ALSA chạy 20 iteration, `underruns = 0`.
- `ttft_max_ms < 500` trên scenario `mixed_vi_en`.
- `barge_in_reaction_ms < 200` trên scenario `barge_in`.
- Không có tiếng crackling khi nghe thực tế trên Pi trong bài test ALSA.
