# AI Edge Assistant Offline trên Raspberry Pi 5

README này là bài nộp tóm tắt cho bài kiểm tra năng lực AI Edge số 2. Nội dung được
viết dựa trên repository hiện tại: source đang là prototype/simulated pipeline, có mock
backend để kiểm tra thiết kế đa luồng, ring buffer, queue/backpressure,
text-normalization cho TTS code-switching và benchmark CPU local. Repository chưa wire
model thật Silero/WebRTC VAD, SenseVoiceSmall, Valtec-TTS hoặc VieNeu-TTS.

## 1. Giới Thiệu Dự Án

Mục tiêu hệ thống là xây dựng trợ lý ảo offline cho bảng điều khiển xe điện thông minh
trên Raspberry Pi 5. Microphone luôn mở ở chế độ Always-on để nhận lệnh rảnh tay, nhưng
ASR/TTS không được chạy liên tục. VAD đóng vai trò gate: chỉ khi phát hiện tiếng người
hợp lệ, audio mới được đóng gói thành segment và đưa sang thread inference.

Pipeline tổng quát:

```text
Microphone always-on / simulated audio
  -> Audio frame 20 ms, PCM16 mono, 16 kHz
  -> VAD nhẹ
  -> Ring Buffer cố định 3 giây
  -> Thread-safe Queue có maxsize
  -> ASR adapter
  -> Text-normalization / prosody
  -> TTS adapter
  -> Audio output / dashboard alert
```

Thiết bị và backend mục tiêu theo đề bài:

- Device: Raspberry Pi 5, Broadcom BCM2712, 4 nhân Cortex-A76, RAM 4GB/8GB,
  Linux ARM64.
- VAD mục tiêu: Silero VAD hoặc WebRTC VAD.
- ASR mục tiêu: SenseVoiceSmall.
- TTS mục tiêu: Valtec-TTS zero-shot cloning khoảng 74.8M parameters hoặc
  VieNeu-TTS v2-Turbo.
- KPI background: Audio + VAD không vượt 40% tổng CPU.
- KPI active: ASR + TTS không vượt 70% tổng CPU.
- KPI RAM: không tăng dần theo thời gian.

Trạng thái repo hiện tại:

- Đã có simulated audio, EnergyVAD fallback, MockASR, MockTTS.
- Đã có producer-consumer threading, fixed-size ring buffer, queue maxsize,
  VAD timeout, cooldown, drop-oldest/drop-newest policy.
- Đã có benchmark CPU simulated local và Docker ARM64 target.
- Chưa có adapter model thật và chưa có benchmark trên Raspberry Pi 5 thật.
- Chưa có module phát audio ra loa; `MockTTS` trả về bytes/metadata để chứng minh
  hợp đồng TTS.

## 2. Bài Trả Lời Theo Đề Bài Kiểm Tra

### Phần 1: Thiết Kế Tổng Quan Hệ Thống Always-on

Pipeline đề xuất:

```text
Microphone luôn mở
  -> Audio frame
  -> VAD
  -> Ring Buffer
  -> Thread-safe Queue
  -> ASR
  -> TTS
  -> Audio output
```

Cần tách riêng luồng thu âm và luồng inference vì audio capture là tác vụ realtime.
Microphone phải được đọc đều theo frame 10/20/30 ms; nếu đưa ASR/TTS vào cùng luồng này,
một lần inference chậm có thể làm mất frame audio hoặc treo toàn pipeline. Trong repo,
`AlwaysOnPipeline.run()` tạo hai thread:

- Producer: `producer_audio_vad_thread()` đọc audio, ghi ring buffer, chạy VAD, emit
  `AudioSegment`.
- Consumer: `consumer_asr_thread()` lấy segment từ queue, chạy ASR/TTS mock.

VAD giúp giảm CPU bằng cách chặn ASR/TTS trong lúc chờ. Ở Background Listening,
`SimulatedAudioSource` không tạo speech, VAD chỉ tính RMS frame và pipeline không enqueue
segment nào. Do đó ASR/TTS không chạy liên tục.

Cách kiểm soát CPU trong thiết kế:

- Background: chỉ chạy audio source + VAD nhẹ, frame 20 ms, queue rỗng.
- Active: ASR/TTS chỉ chạy theo segment đã cắt, không stream liên tục.
- Giới hạn utterance bằng `max_utterance_ms` để inference không bị kéo dài vô hạn.
- Queue có maxsize để không tích lũy backlog.
- Benchmark đo CPU theo phần trăm tổng CPU:
  `process_cpu_delta / wall_time / cpu_count * 100`.
- Khi lên Pi thật, cần giới hạn thread của backend native/BLAS và chọn model/quantization
  phù hợp nếu CPU vượt 40%/70%.

### Phần 2: Thiết Kế VAD Và Ring Buffer

Audio được thu liên tục theo frame nhỏ. Cấu hình simulated hiện tại:

```text
sample_rate = 16000 Hz
frame_ms = 20 ms
format = PCM16 mono
frame_bytes = 16000 * 20 / 1000 * 2 = 640 bytes
ring_buffer_seconds = 3.0
ring_buffer_bytes = 16000 * 3 * 2 = 96000 bytes
```

Ring buffer nằm trong `edge_assistant/ring_buffer.py` và dùng `bytearray` có capacity cố
định. Nó không dùng list/array tăng vô hạn. Khi buffer đầy, byte cũ bị ghi đè. Hàm
`snapshot()` trả về audio theo thứ tự thời gian để thêm pre-roll vào utterance khi VAD
bắt đầu trigger.

Trạng thái VAD trong `producer_audio_vad_thread()`:

- `speech_start_ms`: số ms speech liên tiếp để bắt đầu utterance.
- `speech_end_ms`: số ms silence để đóng utterance.
- `max_utterance_ms`: timeout để cắt utterance quá dài.
- `cooldown_ms`: nghỉ ngắn sau mỗi trigger để giảm noise trigger liên tục.

Khi VAD phát hiện speech, producer tạo utterance buffer có capacity cố định:

```text
max_segment_bytes = ring_buffer_bytes + max_utterance_ms * sample_rate * 2 / 1000
```

Sau khi emit segment, utterance buffer được `clear()`, counters được reset, và producer
tiếp tục đọc audio.

### Phần 3: Kiến Trúc Đa Luồng Producer-Consumer

Thread 1 là Producer:

- Đọc audio từ simulated source, WAV hoặc microphone.
- Ghi mỗi frame vào ring buffer.
- Chạy VAD nhẹ trên frame.
- Nếu speech hợp lệ, gom pre-roll + audio speech vào utterance buffer.
- Đóng segment khi im lặng đủ `speech_end_ms` hoặc chạm `max_utterance_ms`.
- Đẩy `AudioSegment` vào queue bằng timeout ngắn.

Thread 2 là Consumer:

- Gọi `queue.get(timeout=0.05)` nên không block cứng toàn hệ thống khi queue rỗng.
- Nếu lấy được segment, gọi ASR adapter, sau đó TTS adapter.
- Ghi latency ASR/TTS/end-to-end vào `collections.deque(maxlen=512)`.

Queue là `queue.Queue(maxsize=config.queue.max_segments)`, thread-safe và có kích thước
cố định. Khi queue đầy, `_put_segment()` áp dụng policy:

- `drop_oldest`: bỏ segment cũ để ưu tiên cảnh báo mới.
- `drop_newest`: bỏ segment mới nếu muốn bảo toàn backlog cũ.

Dừng hệ thống an toàn:

- Producer kết thúc trước.
- `_stop` event được set.
- Sentinel `None` được đưa vào queue.
- Consumer xử lý hết segment đang chờ và thoát.

Tránh memory leak:

- Ring buffer có capacity cố định.
- Utterance buffer có capacity cố định.
- Queue có `maxsize`.
- Error/latency telemetry dùng `deque(maxlen=...)`.
- Không có list audio toàn cục tăng theo thời gian.

### Phần 4: Tối Ưu Code-switching TTS Anh-Việt

Vấn đề của TTS trong xe điện là cần đọc các câu cảnh báo trộn Anh-Việt:

```text
Hệ thống đang kiểm tra BMS, phát hiện lỗi Overcurrent trên đường nguồn 24V
Mã lỗi CAN bus communication timeout
```

Với model TTS nhỏ dưới 100M parameters, không nên nhúng từ điển tiếng Anh lớn vào model.
Phương án nhẹ hơn là xử lý ở tầng Text-normalization/Phonemizer trước TTS. Repo đã có
`TextNormalizer` trong `edge_assistant/tts.py`, dùng regex/rules và dictionary nhỏ:

- `BMS -> bi em ét`
- `CAN bus -> can bớt`
- `Overcurrent -> âu vờ cờ rần`
- `communication -> com mu ni cây shần`
- `timeout -> thai ao`
- `24V -> hai mươi bốn vôn`
- `15% -> mười lăm phần trăm`

Ưu điểm Regex/rules:

- Rất nhẹ về CPU so với ASR/TTS inference.
- Dễ kiểm soát trong miền từ vựng dashboard xe điện.
- Dễ thêm/sửa rule mà không retrain model.
- Không làm tăng kích thước model TTS.

Nhược điểm:

- Cần bảo trì danh sách thuật ngữ.
- Từ mới có thể bị đọc sai nếu chưa có rule.
- Cách đọc là quy ước domain, cần thống nhất với người dùng/đội sản phẩm.

So với can thiệp Lexicon/Tokenizer:

- Lexicon/tokenizer có thể chính xác hơn ở mức âm vị nếu model hỗ trợ phoneme đa ngôn ngữ.
- Nhưng can thiệp sâu hơn vào pipeline model, dễ gây regression, khó test hơn và tốn công
  bảo trì hơn.
- Với prototype Edge nhỏ, nên ưu tiên regex/rules; chỉ can thiệp tokenizer khi rule-based
  không đạt chất lượng đọc các thuật ngữ quan trọng.

### Phần 5: Prosody Control Cho Cảnh Báo Khẩn Cấp

Cảnh báo khẩn cấp cần nói nhanh hơn và rõ hơn nhưng không thêm model nặng. Thiết kế nên
truyền trực tiếp tham số prosody vào TTS inference:

- `speed`: tăng nhẹ, ví dụ 1.10-1.20.
- `pitch`: tăng vừa phải, ví dụ 1.05-1.10.
- `energy`: tăng vừa phải, ví dụ 1.10-1.15.
- `style_id`: chọn preset `alert` nếu model hỗ trợ.

Trong repo, `TtsConfig` có:

```toml
default_speed = 1.0
urgent_speed = 1.18
default_pitch = 1.0
urgent_pitch = 1.08
default_energy = 1.0
urgent_energy = 1.12
default_style = "neutral"
urgent_style = "alert"
```

`MockTTS.synthesize(text, urgent=True)` trả về `Prosody(speed, pitch, energy, style_id)`
để chứng minh tham số được truyền qua adapter. Nếu model thật không hỗ trợ pitch trực
tiếp, có thể dùng preset voice/style đã chuẩn bị sẵn hoặc post-processing nhẹ, nhưng
phải benchmark lại để đảm bảo active CPU vẫn dưới 70%.

### Phần 6: Quản Lý Queue, Backpressure Và Chống Tràn

Queue có thể đầy khi người dùng nói quá dài, môi trường ồn làm VAD trigger liên tục,
hoặc ASR/TTS chậm hơn producer. Repo có các cơ chế:

- `queue.max_segments = 8`: giới hạn chunk đang chờ ASR.
- `put_timeout_ms = 5`: producer không chờ queue quá lâu.
- `backpressure_policy = "drop_oldest"`: mặc định bỏ segment cũ, giữ cảnh báo mới.
- `max_utterance_ms = 6000`: cắt utterance quá dài trong simulated config.
- `cooldown_ms = 250`: cooldown sau mỗi trigger.
- `warn_at_percent = 0.75`: log warning khi queue gần đầy.
- Metric: `segments_dropped`, `queue_max_observed`, `queue_near_full_events`,
  `vad_timeout_segments`.

Tác dụng phụ:

- Có thể mất một phần câu nói nếu drop segment.
- ASR có thể thiếu ngữ cảnh.
- Hệ thống có thể cần yêu cầu người dùng nói lại.
- Đổi lại, RAM không tăng vô hạn và producer không bị block cứng, phù hợp hệ thống Edge
  cần chạy dài hạn.

### Phần 7: Pseudo-code Python

Pseudo-code theo kiến trúc class, dùng `collections.deque(maxlen=N)` để minh họa ring
buffer cố định. Source thật trong repo dùng `FixedSizeRingBuffer` bằng `bytearray`, cùng
mục tiêu: capacity cố định, không tăng theo thời gian.

```python
import threading
import queue
import time
import collections


class AlwaysOnPipeline:
    def __init__(self, config):
        self.config = config

        self.vad = create_vad(config.vad)
        self.asr = create_asr(config.asr)
        self.tts = create_tts(config.tts)

        ring_frames = int(config.audio.ring_buffer_seconds * 1000 / config.audio.frame_ms)
        max_utterance_frames = int(config.vad.max_utterance_ms / config.audio.frame_ms)

        self.ring_buffer = collections.deque(maxlen=ring_frames)
        self.utterance_buffer = collections.deque(maxlen=ring_frames + max_utterance_frames)

        self.audio_queue = queue.Queue(maxsize=config.queue.max_segments)
        self.stop_event = threading.Event()

        self.cpu_samples = collections.deque(maxlen=240)
        self.ram_samples = collections.deque(maxlen=240)
        self.latency_samples = collections.deque(maxlen=512)

    def producer_audio_vad_thread(self):
        in_speech = False
        speech_ms = 0
        silence_ms = 0
        utterance_ms = 0
        cooldown_until = 0.0

        while not self.stop_event.is_set():
            frame = read_microphone_frame()
            now = time.time()

            self.ring_buffer.append(frame)

            if now < cooldown_until:
                speech_ms = 0
                silence_ms = 0
                continue

            vad = self.vad.infer(frame)
            if vad.speech:
                speech_ms += self.config.audio.frame_ms
                silence_ms = 0
            else:
                silence_ms += self.config.audio.frame_ms
                if not in_speech:
                    speech_ms = 0

            if not in_speech and speech_ms >= self.config.vad.speech_start_ms:
                in_speech = True
                utterance_ms = 0
                self.utterance_buffer.clear()
                for old_frame in self.ring_buffer:
                    self.utterance_buffer.append(old_frame)

            if in_speech:
                self.utterance_buffer.append(frame)
                utterance_ms += self.config.audio.frame_ms

            should_close = in_speech and silence_ms >= self.config.vad.speech_end_ms
            should_timeout = in_speech and utterance_ms >= self.config.vad.max_utterance_ms

            if should_close or should_timeout:
                audio_chunk = b"".join(self.utterance_buffer)
                self._safe_put(audio_chunk)
                self.utterance_buffer.clear()
                in_speech = False
                speech_ms = 0
                silence_ms = 0
                utterance_ms = 0
                cooldown_until = now + self.config.vad.cooldown_ms / 1000.0

            self._log_cpu_ram()

    def consumer_asr_thread(self):
        while not self.stop_event.is_set() or not self.audio_queue.empty():
            try:
                audio_chunk = self.audio_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            try:
                text = self.asr.transcribe(audio_chunk)
                urgent = detect_urgent(text)
                audio = self.tts.synthesize(text, urgent=urgent)
                play_audio(audio)
            finally:
                self.audio_queue.task_done()

    def _safe_put(self, audio_chunk):
        try:
            self.audio_queue.put_nowait(audio_chunk)
        except queue.Full:
            if self.config.queue.backpressure_policy == "drop_oldest":
                try:
                    self.audio_queue.get_nowait()
                    self.audio_queue.task_done()
                except queue.Empty:
                    pass
                try:
                    self.audio_queue.put_nowait(audio_chunk)
                except queue.Full:
                    log_warning("drop newest because queue is still full")
            else:
                log_warning("drop newest because queue is full")

    def _log_cpu_ram(self):
        cpu = read_process_cpu_percent_of_total()
        rss = read_process_rss_mb()
        self.cpu_samples.append(cpu)
        self.ram_samples.append(rss)

    def stop(self):
        self.stop_event.set()
        self.producer.join(timeout=2.0)
        self.consumer.join(timeout=5.0)
        self.utterance_buffer.clear()
```

### Phần 8: Trả Lời 3 Câu Hỏi Giải Trình

1. Code-switching: Nên dùng Text-normalization Regex/Rules trước. Về CPU, rules gần như
không đáng kể so với inference. Về độ chính xác, rules đủ tốt cho domain hẹp như BMS,
CAN bus, Overcurrent, 24V, 15%. Về bảo trì, rules dễ sửa hơn retrain/can thiệp tokenizer.
Lexicon/Tokenizer có thể chính xác âm vị hơn nhưng phức tạp, dễ phá pipeline và cần test
nhiều hơn.

2. Prosody Control: Dùng tham số runtime của TTS như `speed`, `pitch`, `energy`,
`style_id`. Với cảnh báo khẩn, tăng speed nhẹ và pitch/energy vừa phải, không đổi model
và không chạy model phụ. Nếu model không hỗ trợ pitch trực tiếp, dùng preset voice/style
hoặc post-processing nhẹ và phải benchmark lại.

3. Queue & Backpressure: Nên kết hợp queue maxsize, VAD timeout, cooldown và drop policy.
Nếu cần ưu tiên cảnh báo mới trên dashboard xe, dùng `drop_oldest`; nếu cần bảo toàn thứ
tự hội thoại, dùng `drop_newest`. Tác dụng phụ là có thể mất một phần câu nói, ASR thiếu
ngữ cảnh hoặc cần yêu cầu người dùng nói lại. Đổi lại, hệ thống không tràn RAM và không
bị block cứng.

## 3. Pipeline Giả Lập / Pipeline Test

Repo hiện tại có pipeline simulated để kiểm tra kiến trúc mà không cần model lớn:

- `SimulatedAudioSource`: tạo frame PCM16 16 kHz. Background mode không có speech; active
  mode tạo speech-like tone theo chu kỳ.
- `EnergyVAD`: tính RMS để phân biệt silence/speech trong simulated audio.
- `MockASR`: mô phỏng chi phí ASR bằng busy work, trả về một trong hai câu cảnh báo:
  `Hệ thống đang kiểm tra BMS...24V` hoặc `Mã lỗi CAN bus communication timeout`.
- `MockTTS`: normalize text, gán prosody urgent/neutral, mô phỏng chi phí TTS và trả về
  payload bytes dạng mock.

Input giả lập:

- Frame PCM16 mono, 20 ms, 16 kHz.
- Background: noise thấp, kỳ vọng không enqueue segment.
- Active: speech-like signal, kỳ vọng tạo segment và kích hoạt ASR/TTS mock.

Output giả lập:

- JSON stats từ pipeline và benchmark.
- `MockTTS` payload bytes/metadata, chưa phát ra loa.

Simulated test chứng minh được:

- Threading producer-consumer hoạt động.
- Ring buffer/utterance buffer không tăng vô hạn.
- Queue maxsize và drop policy có đường code.
- Text-normalization và prosody được áp dụng.
- CPU monitor local có thể so với KPI 40%/70%.

Simulated benchmark không thay thế benchmark trên Raspberry Pi 5 thật. CPU trên máy local
hoặc Docker ARM64/QEMU chỉ dùng để bắt lỗi logic, không kết luận hiệu năng cuối cùng.

## 4. Code Map

| Đường dẫn | Vai trò |
| --- | --- |
| `edge_assistant/main.py` | Entry point CLI để chạy pipeline theo config, mode và duration. |
| `edge_assistant/pipeline.py` | Core logic: AlwaysOnPipeline, producer-consumer, queue, VAD state, backpressure, stats. |
| `edge_assistant/audio_source.py` | Audio source: simulated, WAV, microphone qua `sounddevice`. |
| `edge_assistant/vad.py` | `EnergyVAD` fallback; nơi cần thay bằng Silero/WebRTC VAD. |
| `edge_assistant/ring_buffer.py` | Fixed-size byte ring buffer cho PCM audio. |
| `edge_assistant/asr.py` | `MockASR`; nơi cần thay bằng SenseVoiceSmall adapter. |
| `edge_assistant/tts.py` | `TextNormalizer`, prosody config, `MockTTS`; nơi cần thay bằng Valtec/VieNeu adapter. |
| `edge_assistant/metrics.py` | Process CPU monitor tính percent trên tổng CPU. |
| `edge_assistant/config.py` | Dataclass config và loader TOML. |
| `configs/pipeline.sim.toml` | Config local/simulated benchmark. |
| `configs/pipeline.rpi.toml` | Config microphone trên Pi, backend vẫn là mock/energy. |
| `benchmarks/bench_pipeline.py` | Benchmark CPU và pipeline stats, có `--out` JSON. |
| `tests/test_ring_buffer.py` | Unit test ring buffer overwrite/clear. |
| `tests/test_tts_normalizer.py` | Unit test code-switching rules và urgent prosody. |
| `docs/ARCHITECTURE.md` | Mô tả kiến trúc chi tiết. |
| `docs/BENCHMARK_PLAN.md` | Kế hoạch benchmark local, Docker ARM64, Pi native, soak/backpressure. |
| `docs/RASPBERRY_PI_DEPLOYMENT.md` | Hướng dẫn Docker ARM64, Pi native, ALSA, systemd. |
| `docker/Dockerfile.pi-sim` | Image Python 3.11 slim để chạy benchmark simulated. |
| `docker/compose.pi-sim.yml` | Compose service ARM64 cho benchmark active. |
| `scripts/docker_run_benchmark.sh` | Script run benchmark trong container ARM64. |
| `scripts/rpi_install_native.sh` | Cài Python venv và dependency cơ bản trên Raspberry Pi. |
| `scripts/rpi_run_native.sh` | Chạy pipeline native từ config. |
| `deploy/systemd/ai-edge-assistant.service` | Service systemd mẫu cho Raspberry Pi. |
| `outputs/background.local.json` | Kết quả benchmark background local mới nhất. |
| `outputs/active.local.json` | Kết quả benchmark active local mới nhất. |

## 5. Đã Test Gì

Unit test đã chạy:

```powershell
& "C:\Users\TinhCute\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s tests
```

Kết quả hiện tại:

```text
Ran 6 tests in 0.015s
OK
```

Unit test kiểm tra:

- Ring buffer chỉ giữ byte mới nhất khi vượt capacity.
- Ghi lớn hơn capacity thay thế bằng suffix mới nhất.
- `clear()` reset snapshot và size.
- Text-normalization cho `BMS`, `Overcurrent`, `24V`.
- Phrase/percent rules cho `CAN bus`, `communication`, `timeout`, `15%`.
- Urgent prosody truyền `speed`, `pitch`, `energy`, `style_id` vào TTS adapter.

Runtime smoke test đã được bao phủ thông qua benchmark 10 giây:

- Background: 500 frames, 0 speech frames, 0 segment, ASR/TTS không chạy.
- Active: 500 frames, 170 speech frames, 2 segments processed, 0 dropped.
- Consumer không treo khi queue rỗng.
- Sentinel shutdown hoạt động.

Benchmark đã đo:

- CPU avg/max theo percent của tổng CPU.
- Số frame, speech frame.
- Segment enqueued/processed/dropped.
- Queue max observed và queue near-full events.
- VAD timeout segments và cooldown skipped frames.
- ASR/TTS/end-to-end latency average/max.

Kết quả benchmark hiện có:

- `outputs/background.local.json`
- `outputs/active.local.json`
- `outputs/audit.background.local.json` và `outputs/audit.active.local.json` là output
  cũ hơn trong workspace.

Kết quả nổi bật từ lần benchmark local 10 giây mới nhất:

| Mode | Duration | CPU avg | CPU max | Pass | Enqueued | Processed | Dropped | Queue max | ASR avg | TTS avg | E2E max |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| background | 10s | 1.248% | 3.688% | true | 0 | 0 | 0 | 0 | 0 ms | 0 ms | 0 ms |
| active | 10s | 1.060% | 2.261% | true | 2 | 2 | 0 | 1 | 20.176 ms | 12.655 ms | 46.644 ms |

Những phần chưa test xong:

- Chưa benchmark trên Raspberry Pi 5 real hardware.
- Chưa test microphone real/sounddevice trong môi trường xe.
- Chưa wire/chạy Silero VAD, WebRTC VAD, SenseVoiceSmall, Valtec-TTS, VieNeu-TTS.
- Chưa có soak test 2-8 giờ để kết luận RAM slope.
- Chưa có benchmark Docker ARM64 mới trong lần cập nhật README này.
- Chưa có test audio output ra loa.

## 6. Benchmark

Chạy benchmark local/simulated:

```powershell
& "C:\Users\TinhCute\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m benchmarks.bench_pipeline --config configs/pipeline.sim.toml --mode background --duration 10 --out outputs/background.local.json
& "C:\Users\TinhCute\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m benchmarks.bench_pipeline --config configs/pipeline.sim.toml --mode active --duration 10 --out outputs/active.local.json
```

Metric được ghi nhận hiện tại:

- `cpu_avg_percent_of_total`: CPU trung bình của process tính theo tổng số core.
- `cpu_max_percent_of_total`: mẫu CPU cao nhất trong run.
- `cpu_pass`: so sánh CPU avg với ngưỡng 40% background hoặc 70% active.
- `frames_seen`: số audio frames producer đã đọc.
- `vad_speech_frames`: số frames được VAD xem là speech.
- `segments_enqueued`: số segment đưa vào queue.
- `segments_processed`: số segment consumer xử lý xong.
- `segments_dropped`: số segment bị drop do backpressure.
- `queue_max_observed`: kích thước queue lớn nhất quan sát được.
- `queue_near_full_events`: số lần queue gần đầy theo `warn_at_percent`.
- `vad_timeout_segments`: số segment bị cắt do VAD timeout.
- `cooldown_skipped_frames`: số frame bị bỏ qua trong cooldown.
- `asr_avg_ms`, `tts_avg_ms`: latency trung bình của adapter mock.
- `end_to_end_avg_ms`, `end_to_end_max_ms`: latency từ khi segment kết thúc đến khi TTS
  mock hoàn thành.

Metric cần có nhưng chưa được benchmark code ghi tự động:

- RAM/RSS slope theo thời gian.
- p50/p95 latency.
- False trigger/minute với microphone thật.
- Power/thermal throttling trên Raspberry Pi 5.

File kết quả:

- Local simulated: `outputs/background.local.json`, `outputs/active.local.json`.
- Docker ARM64 nếu chạy script: `outputs/benchmark.<mode>.docker.json`.
- Pi native theo plan: `outputs/background.pi.json`, `outputs/active.pi.json`.

Ý nghĩa mỗi loại benchmark:

- Local simulated: bắt lỗi logic thread/queue/ring buffer và có baseline CPU trên máy dev.
- Docker ARM64: bắt lỗi dependency/userland ARM64, nhưng nếu chạy qua QEMU thì CPU không
  đại diện Pi thật.
- Raspberry Pi native: mới là benchmark để kết luận đạt KPI 40%/70%.
- Soak test: cần chạy nhiều giờ để xác nhận RAM không tăng tuyến tính.

## 7. Cách Chạy

Chạy test:

```powershell
& "C:\Users\TinhCute\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s tests
```

Nếu trên máy có `python` trong PATH:

```powershell
python -m unittest discover -s tests
```

Chạy local/simulated pipeline:

```powershell
python -m edge_assistant.main --config configs/pipeline.sim.toml --mode background --duration 20
python -m edge_assistant.main --config configs/pipeline.sim.toml --mode active --duration 20
```

Chạy local/simulated benchmark:

```powershell
python -m benchmarks.bench_pipeline --config configs/pipeline.sim.toml --mode background --duration 30 --out outputs/background.local.json
python -m benchmarks.bench_pipeline --config configs/pipeline.sim.toml --mode active --duration 30 --out outputs/active.local.json
```

Build Docker ARM64:

```powershell
docker buildx build --platform linux/arm64 -f docker/Dockerfile.pi-sim -t ai-edge-assistant:pi-sim --load .
```

Chạy Docker ARM64 benchmark:

```powershell
docker run --rm --platform linux/arm64 -v ${PWD}\outputs:/opt/edge-assistant/outputs ai-edge-assistant:pi-sim
```

Hoặc dùng script trên Linux/macOS/Pi:

```bash
./scripts/docker_run_benchmark.sh active 60
./scripts/docker_run_benchmark.sh background 60
```

Chạy Raspberry Pi native:

```bash
chmod +x scripts/rpi_install_native.sh scripts/rpi_run_native.sh
./scripts/rpi_install_native.sh
./scripts/rpi_run_native.sh configs/pipeline.rpi.toml
```

Lưu ý: `configs/pipeline.rpi.toml` đã dùng `audio.source = "microphone"` nhưng VAD/ASR/TTS
vẫn là `energy/mock/mock`. Muốn dùng microphone cần cài optional dependency:

```bash
python -m pip install -r requirements-pi.txt
```

Cài service systemd mẫu:

```bash
sudo cp deploy/systemd/ai-edge-assistant.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-edge-assistant.service
```

Cần sửa `WorkingDirectory` và `ExecStart` trong service nếu đường dẫn trên Pi khác
`/home/pi/ai-edge-assistant`.

Chạy real backend/hardware:

- Chưa có sẵn trong repo.
- Cần thay `EnergyVAD` trong `edge_assistant/vad.py`.
- Cần thay `MockASR` trong `edge_assistant/asr.py`.
- Cần thay `MockTTS` trong `edge_assistant/tts.py`.
- Cần thêm audio output/playback sau TTS nếu muốn phát cảnh báo ra loa.

## 8. Trạng Thái Hiện Tại

Đã có:

- Skeleton AI Edge assistant Always-on bằng Python 3.11.
- Config TOML cho simulated và Raspberry Pi microphone mode.
- Audio source simulated/WAV/microphone.
- Fixed-size ring buffer thread-safe.
- Producer-consumer pipeline với queue maxsize.
- VAD state machine: speech start/end, timeout, cooldown.
- Backpressure: drop oldest/drop newest.
- MockASR và MockTTS có busy-work latency để benchmark.
- Text-normalization code-switching Anh-Việt bằng regex/rules.
- Prosody urgent/neutral: speed, pitch, energy, style_id.
- CPU benchmark local.
- Dockerfile/compose ARM64 simulated.
- Script cài/chạy trên Pi và service systemd mẫu.
- Unit tests cho ring buffer và TTS normalizer/prosody.

Chưa có trong repo:

- Silero VAD hoặc WebRTC VAD adapter thật.
- SenseVoiceSmall adapter thật.
- Valtec-TTS hoặc VieNeu-TTS adapter thật.
- Audio output/playback ra loa thật.
- Wake word engine riêng.
- Intent/NLU/action layer sau ASR.
- Benchmark RAM slope tự động trong code.
- Benchmark trên Raspberry Pi 5 real hardware.
- Soak test nhiều giờ.
- Test với microphone và nhiều điều kiện noise xe thật.

Cần làm tiếp để thành bản hoàn chỉnh:

- Gắn WebRTC/Silero VAD trước, benchmark background CPU trên Pi.
- Gắn SenseVoiceSmall, đo active CPU/latency với câu lệnh thật.
- Gắn Valtec-TTS hoặc VieNeu-TTS, map prosody vào API thật của model.
- Thêm audio playback và chỉnh volume/latency output.
- Thêm RSS/RAM monitor và soak test 2-8 giờ.
- Thêm backpressure stress test với ASR/TTS chậm.
- Thêm tập câu cảnh báo EV thật để kiểm tra code-switching TTS.
- Chạy benchmark native Pi và nộp output `background.pi.json`, `active.pi.json`.
