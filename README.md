# Edge Voice-to-Voice Push-to-Talk Runtime

Repository này là prototype AI Edge cho luồng Voice-to-Voice offline trên
Raspberry Pi 5 / Linux ARM64. Mục tiêu kỹ thuật là kiểm chứng pipeline:

```text
button down -> record PCM in RAM -> button up -> ASR -> TTS -> audio bytes
```

KPI chính: Real Time Factor (RTF) toàn luồng ASR + TTS nhỏ hơn `0.3`, tức
audio 5 giây cần xử lý dưới 1.5 giây. Benchmark cũng theo dõi RSS RAM qua nhiều
vòng để phát hiện memory leak.

## Thiết kế tổng quan

Pipeline được tách thành hai lớp:

1. Runtime pipeline: `VoicePipeline` load ASR/TTS khi khởi động, nhận raw PCM
   chunks, chạy ASR, chạy TTS, đo RTF/RAM và clear buffer sau mỗi lượt.
2. Benchmark/model-prep: chạy cùng pipeline nhiều vòng để so sánh quantization,
   thread count, RAM slope và load-once behavior.

Thiết kế mong muốn trên thiết bị thật:

```text
GPIO/software button pressed
  -> start_recording()
  -> microphone streams 16 kHz mono PCM frames
  -> on each frame: append_audio_chunk()
GPIO/software button released
  -> stop_and_process()
  -> Whisper Tiny ASR
  -> Piper Vietnamese TTS
  -> speaker playback
```

Trong code hiện tại, phần lõi `PCM -> ASR -> TTS -> metrics` đã có. Các module
I/O phần cứng như GPIO button, microphone recorder và speaker player chưa được
đóng gói thành service hoàn chỉnh.

## Pipeline giả lập hoạt động như thế nào

Backend `simulated` dùng để kiểm tra kiến trúc và benchmark nhanh khi chưa có
Raspberry Pi 5 hoặc chưa build real backend.

Luồng giả lập vẫn đi qua cùng `VoicePipeline` như real backend:

```text
generate_synthetic_pcm() hoặc WAV input
  -> start_recording()
  -> append_audio_chunk() theo từng frame PCM
  -> stop_and_process()
  -> SimulatedASRBackend.transcribe_pcm()
  -> SimulatedTTSBackend.synthesize_to_pcm_bytes()
  -> InferenceResult + RTF/RAM metrics
```

Chi tiết mô phỏng:

- Audio input là mono PCM `float32` trong RAM, mặc định 16 kHz.
- ASR giả lập kiểm tra dtype/shape PCM, tính thời gian xử lý theo `quant`,
  `num_threads` và độ dài audio.
- Transcript giả lập deterministic dạng `xin chao robot ma <hash>`, giúp test
  repeatable.
- TTS giả lập tạo sóng PCM `int16` bytes trong RAM, không cần file trung gian.
- `wer_delta_estimate` được gán theo quant: FP16 tốt nhất, Q4 nhanh nhất nhưng
  WER delta cao hơn.
- Buffer audio được clear sau mỗi lượt để tránh giữ RAM.

Vì vậy simulated benchmark chứng minh được kiến trúc, metrics và memory behavior
của pipeline Python, nhưng không thay thế benchmark hiệu năng thật của
`whisper.cpp`/Piper trên Raspberry Pi 5.

## Lựa chọn backend

### ASR

Backend thật ưu tiên là `whisper.cpp` với Whisper Tiny vì:

- Native C/C++, phù hợp CPU ARM64 và không cần GPU.
- Hỗ trợ các model GGML/GGUF đã lượng tử hóa như Q8/Q5/Q4.
- Có thể tận dụng ARM NEON SIMD trên Cortex-A76 khi build native Release.
- Python chỉ orchestration; inference không chạy bằng Python thuần tuần tự.

Repo cũng có backend `simulated` để test nhanh và CI. Backend này deterministic,
không thay thế benchmark thật trên Raspberry Pi 5.

### TTS

Backend thật ưu tiên là Piper TTS cho tiếng Việt vì:

- Chạy offline 100%.
- Model ONNX nhỏ, phù hợp CPU ARM.
- Có CLI/package phổ biến, dễ đóng gói trong image ARM64.

Lưu ý hiện tại: adapter `whisper.cpp` và `piper` đang gọi CLI qua `subprocess`.
Python object được tạo một lần, nhưng CLI process có thể load model lại mỗi lượt.
Để tối ưu latency cuối cùng, nên chuyển sang binding/session persistent nếu
backend hỗ trợ.

## Lượng tử hóa Whisper Tiny

Model được chuẩn bị dưới các mức:

- `FP16`: `models/whisper/ggml-tiny.bin`
- `Q8`: `models/whisper/ggml-tiny-q8_0.bin`
- `Q5`: `models/whisper/ggml-tiny-q5_0.bin`
- `Q4`: `models/whisper/ggml-tiny-q4_0.bin`

Kết quả model-prep mô phỏng hiện chọn `Q5`:

```text
selected: models/whisper/ggml-tiny-q5_0.bin
mean_rtf: 0.19459
wer_delta_estimate: 0.012
```

Lý do chọn `Q5`:

- Nhanh hơn và nhẹ RAM/bandwidth hơn FP16/Q8.
- Giữ độ chính xác tốt hơn Q4.
- WER delta ước tính `0.012`, dưới ngưỡng suy giảm 2%.

`Q4` nhanh hơn trong mô phỏng nhưng bị loại vì WER delta ước tính `0.026`, vượt
ngưỡng `0.02`.

## Tối ưu hiệu năng trên Raspberry Pi 5

Build `whisper.cpp` native ARM64:

```bash
git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git
cmake -S whisper.cpp -B whisper.cpp/build \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_NATIVE=ON
cmake --build whisper.cpp/build -j4 --config Release
```

Khuyến nghị benchmark `num_threads = 1, 2, 3, 4`. Raspberry Pi 5 có 4 nhân vật
lý, nhưng `4` threads không luôn nhanh nhất vì cache contention, scheduling
overhead, memory bandwidth và thermal throttling. Điểm bắt đầu hợp lý là `2`
threads, sau đó chọn cấu hình có `mean_rtf` và `p95_rtf` tốt nhất trên board
thật.

## Code map

```text
src/edge_voice_test/pipeline.py
  VoicePipeline, warm_up(), PTT buffer, ASR/TTS orchestration, RTF/RAM metrics

src/edge_voice_test/runtime.py
  CLI smoke test, hỗ trợ simulated hoặc real backend, có warm-up mặc định

src/edge_voice_test/backends/base.py
  BackendConfig, ASR/TTS protocol, backend factory

src/edge_voice_test/backends/simulated.py
  Backend giả lập deterministic cho test nhanh, có RTF/WER giả lập theo quant

src/edge_voice_test/backends/whisper_cpp.py
  Adapter gọi whisper.cpp CLI, ưu tiên temp WAV trong /dev/shm

src/edge_voice_test/backends/piper.py
  Adapter gọi Piper CLI, ưu tiên output temp file trong /dev/shm

benchmarks/benchmark_pipeline.py
  Benchmark nhiều vòng, ghi CSV, summary JSON, warm-up, RTF/RAM/load-once checks

test_matrix.py
  Chạy ma trận FP16/Q8/Q5/Q4 x threads 1/2/3/4

scripts/
  Download model, build ARM64 image, build whisper.cpp, quantize model
```

## Chạy runtime smoke

Simulated backend:

```powershell
$env:PYTHONPATH="src"
python -m edge_voice_test.runtime `
  --asr-backend simulated `
  --tts-backend simulated `
  --duration 2 `
  --loops 2
```

Real backend trên Raspberry Pi 5:

```bash
export PYTHONPATH=src
python -m edge_voice_test.runtime \
  --asr-backend whisper-cpp \
  --tts-backend piper \
  --threads 2 \
  --quant Q5 \
  --whisper-model models/whisper/ggml-tiny.bin \
  --piper-model models/piper/vi_VN-vais1000-medium/vi_VN-vais1000-medium.onnx \
  --piper-config models/piper/vi_VN-vais1000-medium/vi_VN-vais1000-medium.onnx.json
```

Runtime mặc định chạy `warm_up()` trước vòng đo chính. Có thể tắt bằng
`--skip-warm-up` nếu muốn đo cold-start.

## Đã test gì

Unit tests hiện có trong `tests/test_correctness.py` kiểm tra:

- Model ASR/TTS simulated chỉ được load một lần khi tạo `VoicePipeline`.
- Với Q5 và 2 threads, simulated pipeline đạt RTF nhỏ hơn `0.3`.
- Push-to-Talk API hoạt động đúng: `start_recording()`, `append_audio_chunk()`,
  `stop_and_process()`.
- Pipeline nhận raw PCM trong RAM và trả transcript + TTS bytes.
- Không tạo `*.wav` hoặc `temp*.wav` trong thư mục làm việc khi dùng simulated
  backend.
- `warm_up()` chạy được mà không làm tăng load count của model.
- PCM sai shape, ví dụ stereo/2D array, bị reject.

Runtime smoke hiện kiểm tra:

- CLI `edge_voice_test.runtime` tạo pipeline, warm-up, chạy một hoặc nhiều vòng
  PTT giả lập và in JSON result.
- Output có `runtime_ok`, `rtf`, `ram_before_mb`, `ram_after_mb`,
  `asr_load_count`, `tts_load_count` và thông tin warm-up.

Benchmark hiện kiểm tra:

- Chạy nhiều loop qua cùng pipeline để đo steady-state.
- Ghi CSV từng loop vào `results/*.csv`.
- In summary JSON gồm mean/p95 RTF, wall RTF, ASR/TTS time, RAM slope,
  load-once pass và memory-leak pass.
- `test_matrix.py` chạy ma trận `FP16/Q8/Q5/Q4 x threads 1/2/3/4`.

Kết quả đã lưu:

- `results/matrix_summary.csv`: simulated quant/thread matrix.
- `results/model_prep/model_prep_report.json`: báo cáo chọn model quantized.
- `results/model_prep/model_prep_summary.csv`: tóm tắt FP16/Q8/Q5/Q4.

Kết quả nổi bật hiện tại:

```text
Q5, threads=2, audio=5s
mean_rtf_sim = 0.19459
wer_delta_estimate = 0.012
load_once_pass = true
memory_leak_pass_simple = true
```

Chưa test xong trong repo:

- GPIO button thật.
- Microphone thật.
- Speaker playback thật.
- End-to-end latency trên Raspberry Pi 5 vật lý.
- RTF thật của `whisper.cpp` + Piper trên Pi 5.

## Benchmark

Benchmark một cấu hình:

```powershell
$env:PYTHONPATH="src"
python benchmarks/benchmark_pipeline.py `
  --asr-backend simulated `
  --tts-backend simulated `
  --quant Q5 `
  --threads 2 `
  --duration 5 `
  --loops 50 `
  --out results/benchmark_q5_t2.csv
```

Output summary gồm:

- `mean_asr_time_sec`
- `mean_tts_time_sec`
- `mean_total_time_sec`
- `mean_rtf`, `p95_rtf`
- `mean_wall_rtf`, `p95_wall_rtf`
- `ram_slope_mb_per_loop`
- `load_once_pass`
- `memory_leak_pass_simple`
- `rtf_pass`

Chạy ma trận quant/thread:

```powershell
$env:PYTHONPATH="src"
python test_matrix.py
```

Kết quả hiện có trong `results/matrix_summary.csv` cho thấy simulated Q5 với
2 threads đạt `mean_rtf_sim = 0.19459`, load-once pass và RAM slope gần 0.

## Docker ARM64

Build image ARM64:

```powershell
docker buildx build --platform linux/arm64 `
  -t edge-voice-ptt-test:arm64 `
  -f Dockerfile.arm64 `
  --load .
```

Build image có real backend binaries:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_arm64_image.ps1 -RealBackends
```

Runtime smoke ARM64:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_arm64_runtime.ps1 -Memory 4g
```

Benchmark ARM64 emulation:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_arm64_emulation.ps1 -Memory 4g
powershell -ExecutionPolicy Bypass -File .\scripts\run_arm64_emulation.ps1 -Memory 8g
```

QEMU/ARM64 emulation chỉ chứng minh packaging và compatibility, không được dùng
để khẳng định RTF thật trên Raspberry Pi 5.

## Model preparation

Download base models:

```bash
scripts/download_models.sh
```

Build whisper.cpp:

```bash
scripts/build_whisper_cpp.sh
```

Quantize Whisper Tiny:

```bash
scripts/quantize_whisper_tiny.sh
```

Run model-prep report:

```powershell
docker run --rm --platform linux/arm64 `
  -e PYTHONPATH=/app/src `
  -v "${PWD}\models:/app/models" `
  -v "${PWD}\results:/app/results" `
  edge-voice-ptt-test:arm64 `
  python scripts/prepare_whisper_models.py `
    --skip-quantize `
    --threads 2 `
    --duration 5 `
    --loops 10 `
    --results-dir results/model_prep
```

## Trạng thái hiện tại

Đã có:

- Core `VoicePipeline`.
- Warm-up ASR/TTS trước benchmark.
- Simulated ASR/TTS backend.
- Real backend adapters cho `whisper.cpp` và Piper CLI.
- RTF/RAM/load-once metrics.
- Benchmark CSV/JSON summary.
- Quantization/model-prep report.
- Docker ARM64 path.

Chưa có:

- GPIO button service.
- Microphone recorder service.
- Speaker playback service.
- Full end-to-end PTT app trên Raspberry Pi 5.
- Benchmark vật lý trên Raspberry Pi 5 với mic/loa thật.
- Persistent native ASR/TTS session thay cho CLI subprocess mỗi lượt.

Kết luận trung thực: repo đã đủ để kiểm chứng lõi inference/benchmark và chuẩn
bị deployment ARM64. Để thành thiết bị PTT hoàn chỉnh cần thêm lớp hardware I/O
và benchmark trực tiếp trên Raspberry Pi 5.
