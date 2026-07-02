# Edge Voice-to-Voice Push-to-Talk Runtime

Repository này là prototype AI Edge cho luồng Voice-to-Voice offline trên
Raspberry Pi 5 / Linux ARM64. Mục tiêu kỹ thuật là kiểm chứng pipeline:

```text
button down -> record PCM in RAM -> button up -> ASR -> TTS -> audio bytes
```

KPI chính: Real Time Factor (RTF) toàn luồng ASR + TTS nhỏ hơn `0.3`, tức
audio 5 giây cần xử lý dưới 1.5 giây. Benchmark cũng theo dõi RSS RAM qua nhiều
vòng để phát hiện memory leak.

## Bài trả lời theo đề bài kiểm tra

Phần này là phần giải trình trực tiếp theo từng yêu cầu của bài kiểm tra. Các
mục phía sau mô tả chi tiết code, cách chạy và benchmark trong repo.

### Phần 1: Thiết kế tổng quan

Pipeline Voice-to-Voice dạng Push-to-Talk:

```text
Người dùng bấm nút
  -> bắt đầu ghi âm PCM 16 kHz mono vào RAM
Người dùng nhả nút
  -> ghép các PCM frame trong RAM
  -> ASR chuyển audio thành text
  -> TTS chuyển text thành audio bytes
  -> phát audio ra loa
  -> clear buffer, log RTF/RAM
```

Trong repo, phần lõi pipeline nằm ở `src/edge_voice_test/pipeline.py`. API hiện
có:

- `VoicePipeline.__init__()`: tạo ASR/TTS backend một lần.
- `warm_up()`: chạy dummy ASR/TTS để giảm cold-start latency.
- `start_recording()`: bắt đầu lượt PTT, clear buffer cũ.
- `append_audio_chunk()`: nhận raw PCM frame. Hàm này tương đương
  `on_audio_frame()` trong yêu cầu bài.
- `stop_and_process()`: dừng ghi, chạy ASR -> TTS, đo RTF/RAM, clear buffer.

Chọn `whisper.cpp` cho Whisper Tiny trên Raspberry Pi 5 vì:

- Là backend C/C++ native, nhẹ, phù hợp CPU ARM64 không GPU.
- Hỗ trợ model Whisper Tiny đã lượng tử hóa Q8/Q5/Q4.
- Có thể build Release native để tận dụng ARM NEON SIMD trên Cortex-A76.
- Python chỉ điều phối pipeline, không chạy inference bằng Python thuần tuần tự.
- Dễ đóng gói trong Docker ARM64 và chạy offline 100%.

Không chọn `sherpa-onnx` làm hướng chính trong repo này vì mục tiêu bài đang tập
trung vào Whisper Tiny GGML/GGUF và quantization của `whisper.cpp`. Tuy nhiên
`sherpa-onnx` vẫn là phương án hợp lệ nếu muốn dùng ONNX Runtime session
persistent.

Chọn Piper TTS cho tiếng Việt vì:

- Chạy offline 100%.
- Model ONNX nhỏ, phù hợp CPU ARM.
- Có tiếng Việt và dễ triển khai trên Linux ARM64.
- Dễ tích hợp với pipeline Python qua CLI hoặc session/binding nếu có.

Nguyên tắc load model:

- ASR model và TTS model phải được khởi tạo trong `VoicePipeline.__init__()`.
- Khi người dùng bấm hoặc nhả nút, chương trình chỉ xử lý audio mới.
- Không load lại model trong mỗi lượt Push-to-Talk.
- Trong repo hiện tại, simulated backend chứng minh load-once bằng
  `asr_load_count == 1` và `tts_load_count == 1`.
- Lưu ý kỹ thuật: adapter real `whisper.cpp`/Piper hiện gọi CLI qua subprocess,
  nên CLI có thể tự load model lại mỗi lượt. Đây là giới hạn đã ghi rõ; bản tối
  ưu cuối nên dùng binding/session persistent.

### Phần 2: Lượng tử hóa model

Mức lượng tử hóa được chọn: **Q5** cho Whisper Tiny.

Lý do chọn Q5:

- Cân bằng tốt giữa tốc độ, RAM và độ chính xác.
- Nhẹ hơn FP16/Q8 nên giảm memory bandwidth, giúp CPU ARM xử lý nhanh hơn.
- Chính xác hơn Q4, giảm nguy cơ WER tăng quá mức với tiếng Việt.
- Kết quả mô phỏng hiện có: `mean_rtf = 0.19459`,
  `wer_delta_estimate = 0.012`, dưới ngưỡng suy giảm WER 2%.

Vì sao Q5 giúp tối ưu tốc độ trên CPU ARM:

- Model nhỏ hơn làm giảm lượng dữ liệu phải đọc từ RAM/cache.
- CPU Cortex-A76 thường bị giới hạn bởi memory bandwidth khi inference model nhỏ
  chạy nhiều lớp liên tiếp.
- Quantized weights giúp backend native dùng kernel tối ưu tốt hơn so với FP16
  trong môi trường không GPU.

Vì sao không chọn mức khác:

- `FP16`: chính xác nhất nhưng chậm hơn, tốn RAM/bandwidth hơn, khó đạt RTF
  `< 0.3` trên CPU nếu pipeline còn có TTS.
- `INT8`: là lựa chọn hợp lý nếu dùng backend INT8 chuẩn như ONNX Runtime, nhưng
  repo này đang theo flow `whisper.cpp` GGML/GGUF nên dùng Q-format trực tiếp.
- `Q8`: độ chính xác tốt, nhưng tốc độ/RAM chưa tối ưu bằng Q5.
- `Q4`: nhanh và nhẹ hơn Q5, nhưng WER delta ước tính `0.026`, vượt ngưỡng 2%.

Điều kiện chất lượng: WER sau lượng tử hóa không được suy giảm quá 2% so với
bản gốc. Vì vậy Q5 được chọn thay vì Q4.

### Phần 3: Backend và tối ưu hiệu năng

Build `whisper.cpp` trên Raspberry Pi 5 để tận dụng ARM NEON SIMD:

```bash
git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git
cmake -S whisper.cpp -B whisper.cpp/build \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_NATIVE=ON
cmake --build whisper.cpp/build -j4 --config Release
```

Cấu hình nguyên tắc:

- Dùng Linux ARM64 native, không chạy x86 emulation khi benchmark thật.
- Build `Release`, bật native CPU optimization.
- Không dùng Python thuần tuần tự cho inference.
- Python chỉ làm orchestration: nhận PCM, gọi backend native, đo metric, quản lý
  buffer.

Thiết lập `num_threads`:

- Raspberry Pi 5 có 4 nhân Cortex-A76 vật lý.
- Không mặc định chọn `num_threads = 4` cho mọi trường hợp.
- Điểm khởi đầu hợp lý là `num_threads = 2`, sau đó benchmark 1, 2, 3, 4.

Vì sao `num_threads = 4` đôi khi chậm hơn `num_threads = 2`:

- Tranh chấp cache giữa các worker thread.
- Overhead tạo/lập lịch/sync thread.
- Nghẽn memory bandwidth khi nhiều thread cùng đọc model weights.
- Hệ thống vẫn cần CPU cho audio I/O, OS, Python orchestration.
- Raspberry Pi 5 có thể thermal throttling khi chạy full 4 core lâu.

Cách benchmark thực tế:

```bash
for t in 1 2 3 4; do
  python benchmarks/benchmark_pipeline.py \
    --asr-backend whisper-cpp \
    --tts-backend piper \
    --quant Q5 \
    --threads "$t" \
    --wav sample_5s.wav \
    --loops 30 \
    --out "results/pi5_q5_t${t}.csv"
done
```

Chọn cấu hình có:

- `mean_rtf < 0.3`.
- `p95_rtf < 0.3` nếu muốn chắc hơn cho realtime.
- `ram_slope_mb_per_loop` gần 0.
- Transcript vẫn đạt WER trong ngưỡng cho phép.

### Phần 4: Pseudo-code Python kiến trúc chuẩn

Pseudo-code dưới đây mô tả kiến trúc đầy đủ mong muốn trên Raspberry Pi 5. Code
trong repo hiện đã có phần lõi tương ứng, nhưng chưa có GPIO/mic/speaker service
thật.

```python
import time
from pathlib import Path

import numpy as np
import psutil


class VoicePipeline:
    def __init__(self, asr_model_path, tts_model_path, sample_rate=16000, num_threads=2):
        self.sample_rate = sample_rate
        self.num_threads = num_threads
        self.buffer = []
        self.recording = False
        self.process = psutil.Process()

        # Load ASR model đúng 1 lần khi chương trình khởi động.
        # Backend nên là native persistent engine, không load lại mỗi lần bấm nút.
        self.asr = WhisperCppEngine(
            model_path=asr_model_path,
            language="vi",
            num_threads=num_threads,
            input_format="pcm_float32",
        )

        # Load TTS model đúng 1 lần khi chương trình khởi động.
        self.tts = PiperEngine(
            model_path=tts_model_path,
            output_format="pcm_s16le",
            sample_rate=sample_rate,
        )

        # Mở audio output một lần để phát PCM trực tiếp ra loa.
        self.speaker = AlsaPcmPlayer(
            sample_rate=sample_rate,
            channels=1,
            sample_format="s16le",
        )

    def warm_up(self):
        # Chạy dummy inference để tránh cold-start latency ở lượt đầu.
        dummy_pcm = np.zeros(self.sample_rate // 4, dtype=np.float32)
        _ = self.asr.transcribe_pcm(dummy_pcm)
        _ = self.tts.synthesize_to_pcm_bytes("xin chao")

    def start_recording(self):
        # Sự kiện bấm nút: bắt đầu lượt Push-to-Talk mới.
        self.buffer.clear()
        self.recording = True
        self.record_start_time = time.perf_counter()

    def on_audio_frame(self, pcm_frame):
        # Nhận raw PCM frame từ microphone, lưu trong RAM.
        # Không ghi temp.wav xuống MicroSD/SSD.
        if not self.recording:
            return
        if pcm_frame.ndim != 1:
            raise ValueError("Expected mono PCM frame")
        self.buffer.append(np.ascontiguousarray(pcm_frame, dtype=np.float32))

    def stop_and_process(self):
        # Sự kiện nhả nút: dừng ghi âm và chạy ASR -> TTS -> speaker.
        if not self.recording:
            return None
        self.recording = False
        if not self.buffer:
            return None

        ram_before = self.rss_mb()

        try:
            pcm = np.concatenate(self.buffer)
            audio_duration_sec = len(pcm) / self.sample_rate

            start = time.perf_counter()

            # Truyền raw PCM trực tiếp vào ASR.
            transcript = self.asr.transcribe_pcm(pcm)

            # TTS sinh PCM audio bytes.
            tts_pcm_bytes = self.tts.synthesize_to_pcm_bytes(transcript)

            processing_time_sec = time.perf_counter() - start
            rtf = processing_time_sec / max(audio_duration_sec, 1e-6)

            # Phát PCM trực tiếp ra loa.
            self.speaker.play_pcm(tts_pcm_bytes)

            ram_after = self.rss_mb()
            return {
                "transcript": transcript,
                "audio_duration_sec": audio_duration_sec,
                "processing_time_sec": processing_time_sec,
                "rtf": rtf,
                "ram_before_mb": ram_before,
                "ram_after_mb": ram_after,
                "ram_delta_mb": ram_after - ram_before,
                "passed_rtf": rtf < 0.3,
            }

        finally:
            # Clear buffer sau mỗi lượt để tránh memory leak.
            self.buffer.clear()

    def save_temp_for_external_process(self, data: bytes, filename="tts_output.pcm"):
        # Nếu bắt buộc dùng file tạm, dùng /dev/shm vì đây là tmpfs trên RAM.
        # Không ghi file tạm xuống MicroSD/SSD.
        base = Path("/dev/shm") if Path("/dev/shm").exists() else Path("/tmp")
        path = base / filename
        path.write_bytes(data)
        return path

    def rss_mb(self):
        return self.process.memory_info().rss / 1024 / 1024


def benchmark_memory_stability(pipeline, test_pcm, loops=50):
    results = []
    for i in range(loops):
        pipeline.start_recording()
        for frame in split_pcm(test_pcm, frame_size=1600):
            pipeline.on_audio_frame(frame)
        result = pipeline.stop_and_process()
        results.append(result)
        print(
            f"loop={i + 1} rtf={result['rtf']:.3f} "
            f"ram_after={result['ram_after_mb']:.1f}MB "
            f"ram_delta={result['ram_delta_mb']:.3f}MB"
        )

    ram_slope = (
        results[-1]["ram_after_mb"] - results[0]["ram_after_mb"]
    ) / max(loops - 1, 1)
    print(f"RAM slope: {ram_slope:.4f} MB/loop")
    assert ram_slope < 0.05, "Possible memory leak"
    return results
```

### Trả lời ngắn 4 câu giải trình

1. Chọn `whisper.cpp` hay `sherpa-onnx`?

   Chọn `whisper.cpp` cho repo này vì nhẹ, native C/C++, hỗ trợ Whisper Tiny
   quantized Q5/Q8/Q4, chạy tốt trên CPU ARM64/NEON và phù hợp offline. Nếu cần
   ONNX Runtime session persistent, `sherpa-onnx` là phương án thay thế hợp lệ.

2. Raspberry Pi 5 có 4 nhân vật lý thì nên set `num_threads` bao nhiêu?

   Bắt đầu với `num_threads = 2`, sau đó benchmark 1, 2, 3, 4. `4` threads đôi
   khi chậm hơn `2` vì tranh chấp cache, thread overhead, nghẽn memory bandwidth
   và thermal throttling.

3. Nếu TTS bắt buộc lưu file tạm thì lưu ở đâu?

   Lưu vào `/dev/shm` trên Linux. Đây là tmpfs trên RAM, nhanh hơn và không làm
   hao mòn MicroSD/SSD.

4. Chọn FP16, INT8, Q8, Q5 hay Q4?

   Chọn Q5. FP16 chính xác nhưng chậm/tốn RAM, Q8 chính xác nhưng nặng hơn Q5,
   INT8 phù hợp hơn với backend ONNX INT8, Q4 nhanh nhưng WER delta dễ vượt 2%.
   Q5 cân bằng tốc độ, RAM và độ chính xác, với WER delta ước tính `0.012`.

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
