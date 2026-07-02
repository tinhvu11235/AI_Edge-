# Ke hoach benchmark

## Muc tieu pass/fail

| Che do | Dieu kien | Gioi han |
| --- | --- | --- |
| Background listening | Audio + VAD, khong co speech | CPU avg <= 40% tong CPU |
| Active inference | Co speech, ASR + TTS duoc kich hoat | CPU avg <= 70% tong CPU |
| Memory soak | Chay 2-8 gio | RSS khong tang tuyen tinh |
| Queue stability | ASR/TTS cham hon producer | Queue khong tran, process khong treo |
| Latency | Speech end -> TTS ready | Do va bao cao p50/p95/max |

CPU trong benchmark duoc tinh la phan tram cua tong nang luc may:

```text
process_cpu_percent_total = process_cpu_delta / wall_time / cpu_count * 100
```

Tren Raspberry Pi 5 co 4 core, 100% tong CPU tuong duong ca 4 core day tai.

## 1. Benchmark local smoke

```powershell
python -m unittest discover -s tests
python -m benchmarks.bench_pipeline --config configs/pipeline.sim.toml --mode background --duration 30 --out outputs/background.local.json
python -m benchmarks.bench_pipeline --config configs/pipeline.sim.toml --mode active --duration 30 --out outputs/active.local.json
```

Can ghi lai:

- `cpu_avg_percent_of_total`
- `cpu_max_percent_of_total`
- `segments_enqueued`, `segments_processed`, `segments_dropped`
- `queue_max_observed`
- `asr_avg_ms`, `tts_avg_ms`, `end_to_end_avg_ms`, `end_to_end_max_ms`

## 2. Benchmark Docker ARM64

Muc dich: test userland Linux ARM64 giong Pi truoc khi dua len thiet bi that.

```powershell
docker buildx build --platform linux/arm64 -f docker/Dockerfile.pi-sim -t ai-edge-assistant:pi-sim --load .
docker run --rm --platform linux/arm64 -v ${PWD}\outputs:/opt/edge-assistant/outputs ai-edge-assistant:pi-sim
```

Chay rieng:

```powershell
docker run --rm --platform linux/arm64 ai-edge-assistant:pi-sim python -m benchmarks.bench_pipeline --config configs/pipeline.sim.toml --mode background --duration 60
docker run --rm --platform linux/arm64 ai-edge-assistant:pi-sim python -m benchmarks.bench_pipeline --config configs/pipeline.sim.toml --mode active --duration 60
```

Luu y: neu Docker Desktop dang chay tren x86 va dung QEMU de emulate ARM64, so CPU tuyet
doi khong dai dien cho Pi that. Gia tri cua buoc nay la bat loi OS/dependency/threading,
khong phai ket luan hieu nang cuoi cung.

## 3. Benchmark Raspberry Pi native

Tren Pi:

```bash
./scripts/rpi_install_native.sh
python -m benchmarks.bench_pipeline --config configs/pipeline.rpi.toml --mode background --duration 300 --out outputs/background.pi.json
python -m benchmarks.bench_pipeline --config configs/pipeline.rpi.toml --mode active --duration 300 --out outputs/active.pi.json
```

Chay soak test:

```bash
python -m benchmarks.bench_pipeline --config configs/pipeline.rpi.toml --mode background --duration 14400 --out outputs/background-soak-4h.pi.json
```

## 4. Backpressure test

Tang `asr.work_ms` va `tts.work_ms` trong config de mo phong model cham:

```toml
[asr]
work_ms = 300

[tts]
work_ms = 200
```

Tieu chi:

- Process khong crash.
- `queue_max_observed <= queue.max_segments`.
- `segments_dropped` co the tang, nhung producer van doc frame tiep.
- End-to-end latency khong tang vo han.

## 5. Audio/VAD test

Voi microphone that:

- Background: bat xe/quat/gio gia lap, khong noi. Ky vong VAD trigger rat thap.
- Speech: doc cau "He thong dang kiem tra BMS, phat hien loi Overcurrent tren duong
  nguon 24V".
- Noise burst: bam coi/tieng dong co ngan. Ky vong khong tao segment dai.

Can tinh them:

- False trigger/minute trong background.
- Segment duration distribution.
- VAD timeout count.

## 6. Bao cao can nop

Moi lan benchmark nen nop 4 file:

- `outputs/background.local.json`
- `outputs/active.local.json`
- `outputs/background.pi.json`
- `outputs/active.pi.json`

Kem bang tong hop:

| Run | CPU avg | CPU max | Dropped | Queue max | ASR avg | TTS avg | E2E max | Pass |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

Ket luan chi duoc dua ra tu run tren Pi native; Docker ARM64 chi la cong cu tien kiem.
