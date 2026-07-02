# AI Edge 3 - Streaming Voice Pipeline siêu thấp độ trễ trên Raspberry Pi 5

## 1. Giới thiệu dự án

Dự án này là prototype/scaffold cho bài kiểm tra năng lực AI Edge số 3: thiết kế hệ thống giao tiếp giọng nói streaming offline cho robot hình người chạy trên Raspberry Pi 5. Mục tiêu chính là mô phỏng và kiểm chứng kiến trúc bất đồng bộ gồm Streaming ASR partial text, token/sentence splitter thời gian thực, Streaming TTS, jitter buffer và audio output native qua ALSA/PipeWire.

Pipeline tổng quát:

```text
Microphone stream
  -> Streaming ASR
  -> partial text callback
  -> token/sentence splitter
  -> TTS text queue
  -> Streaming TTS
  -> PCM chunk queue
  -> Jitter Buffer
  -> ALSA/PipeWire audio driver
```

Thiết bị đích và backend định hướng:

- Raspberry Pi 5, Broadcom BCM2712, 4 nhân Cortex-A76, RAM 4GB/8GB, Linux ARM64.
- ASR định hướng: Zipformer Multilingual cho streaming thật; Whisper-Tiny chỉ dùng như phương án chunk/sliding window nếu cần.
- TTS định hướng: Valtec-TTS streaming mode.
- Audio output: ALSA native trong source hiện có; PipeWire được nêu như hướng triển khai nếu cần routing/spatial audio.

KPI của đề bài:

- TTFT nhỏ hơn 500 ms từ khi kỹ sư dứt câu hoặc dứt mệnh đề đến khi loa robot bắt đầu phát phản hồi.
- Không có audio crackling, underrun, tiếng nổ lụp bụp hoặc ngắt quãng.
- Barge-in khẩn cấp như "Dừng lại, tắt động cơ ngay!" phản ứng dưới 200 ms.

Trạng thái quan trọng: repo hiện là simulated/prototype. Chưa có ASR model thật, chưa có Valtec-TTS thật, chưa có benchmark ALSA trên Raspberry Pi 5 trong repo. Các kết quả hiện có trong `benchmark_results/` là benchmark simulated với `--audio=null`.

## 2. Bài trả lời theo đề bài kiểm tra

### Phần 1: Thiết kế tổng quan Streaming Voice Pipeline

Pipeline thiết kế:

```text
Microphone stream -> Streaming ASR -> partial text callback
-> token/sentence splitter -> TTS text queue
-> Streaming TTS -> PCM chunk queue
-> Jitter Buffer -> ALSA/PipeWire audio driver
```

Không được đợi người dùng nói xong toàn bộ câu mới chạy TTS vì tổng latency sẽ bị cộng dồn: endpointing của VAD/ASR, final decoding, xử lý text, TTS first chunk và audio prebuffer. Với câu kiểm thử "Tăng moment xoắn cho cụm rotary actuator ở khớp gối lên 15 phần trăm, đồng thời check lại sensor vision giúp anh.", hệ thống có thể phản hồi sớm sau mệnh đề đầu thay vì chờ toàn bộ câu.

Cách giảm TTFT là cắt câu/mệnh đề sớm:

- ASR xuất partial text liên tục trong lúc người dùng đang nói.
- Splitter cắt tại dấu câu hoặc cụm có nghĩa khi segment đủ dài.
- TTS nhận segment nhỏ qua queue và bắt đầu sinh PCM chunk đầu tiên.
- Audio output phát từ jitter buffer mà không chờ ASR/TTS hoàn tất toàn bộ câu.

Trong `src/main.cpp`, pipeline được tách thành nhiều worker:

- `asr_simulator()` mô phỏng ASR partial callback và đẩy `TextJob` vào `text_queue`.
- `tts_worker()` lấy `TextJob`, mô phỏng TTS first chunk latency, sinh PCM chunk và đẩy vào `jitter_buffer`.
- `audio_worker()` prebuffer PCM, ghi ra `AudioSink`, đo TTFT và underrun.
- Barge-in chạy bằng thread riêng khi truyền `--barge-in-ms`.

ASR, TTS và Audio Output không block lẫn nhau. Các khối giao tiếp qua `BlockingQueue<T>` dùng `mutex`, `condition_variable`, `pop_for()`, `clear()` và `close()`. Đây là điểm cốt lõi để audio thread không bị kẹt bởi ASR/TTS và để ASR vẫn tiếp tục nhận partial khi audio đang phát.

### Phần 2: Multilingual Streaming ASR

Yêu cầu nhận diện câu trộn tiếng Việt và tiếng Anh kỹ thuật trong cùng một stream, ví dụ:

```text
Tăng moment xoắn cho cụm rotary actuator ở khớp gối lên 15 phần trăm,
đồng thời check lại sensor vision giúp anh.
```

Thiết kế đề xuất:

- Dùng một Streaming ASR đa ngôn ngữ cho toàn câu, không gọi API chuyển đổi ngôn ngữ thủ công.
- ASR phải xuất partial result khi người dùng đang nói để splitter có dữ liệu sớm.
- Không tách pipeline thành tiếng Việt rồi tiếng Anh vì chuyển ngôn ngữ thủ công dễ gây token dropping ở biên như `rotary actuator`, `sensor vision`, `CAN bus`.
- Giữ context ngắn gồm partial gần nhất, endpoint gần nhất và danh sách hotword kỹ thuật.

Ưu tiên Zipformer Multilingual nếu cần streaming thật sự, vì kiến trúc CTC/RNN-T/Transducer phù hợp partial decoding theo frame và endpointing ngắn. Nếu dùng Whisper-Tiny, cần ghi rõ đó là wrapper chunk/sliding window: chạy từng cửa sổ audio ngắn có overlap, giữ prompt/context ngắn và commit token theo timestamp ổn định. Whisper-Tiny kiểu này có thể dùng offline trên Pi 5 nhưng không tự nhiên bằng ASR streaming chuyên dụng.

Trong repo hiện tại chưa có ASR thật. `asr_simulator()` chỉ mô phỏng partial text từ chuỗi scenario có sẵn. Adapter ASR thật cần thay vào vị trí callback:

```cpp
void asr_streaming_callback(std::string partial_text) {
  for (auto segment : splitter.process_partial(partial_text)) {
    text_queue.push(TextJob{next_id(), current_epoch(), segment, Clock::now()});
  }
}
```

### Phần 3: Token/Sentence Splitting thời gian thực

`SentenceSplitter` nhận partial text từ ASR callback và chỉ emit phần text mới chưa xử lý. Mục tiêu là không đợi toàn bộ câu kết thúc nhưng vẫn tránh cắt quá vụn.

Thuật toán trong source hiện có:

1. Normalize partial bằng `collapse_spaces()`.
2. Giữ `emitted_pos_` làm vị trí text đã commit.
3. Giữ `emitted_segments_` để chống gửi trùng partial đã xử lý.
4. Nếu gặp hard boundary `, . ? ! ; :`, cắt segment nếu đạt `split_min_tokens`.
5. Nếu partial quá dài, cắt mềm khi số token đạt `split_max_tokens`.
6. Cắt mềm ưu tiên marker như "đồng thời", "sau đó", "rồi", "và", "and", "then".
7. `reconcile_partial_correction()` xử lý trường hợp ASR sửa hoặc truncate partial trước đó.
8. `flush()` phát phần còn lại khi ASR kết thúc.

Tham số hiện có:

- `--split-min-tokens`: mặc định 4, tương ứng ngưỡng tối thiểu 4-6 token trong đề bài.
- `--split-max-tokens`: mặc định 16, tương ứng ngưỡng tối đa 12-16 token trong đề bài.

Repo chưa có VAD timestamp hoặc silence detector thật. Vì vậy ngưỡng 300-500 ms im lặng ngắn mới nằm ở mức thiết kế, chưa được hiện thực trong code.

### Phần 4: Streaming TTS và Jitter Buffer

TTS nhận từng đoạn text nhỏ từ `text_queue`, không nhận cả câu dài. Trong source hiện tại, `tts_worker()` chưa gọi Valtec-TTS thật mà mô phỏng bằng:

- `tts_first_chunk_ms`: mặc định 80 ms.
- `tts_chunk_ms`: mặc định 40 ms audio mỗi chunk.
- `tts_inter_chunk_gap_ms`: mặc định 22 ms giữa các chunk.
- `generate_pcm_chunk()`: sinh sine PCM S16_LE để đo scheduling.

PCM chunk được đưa vào `jitter_buffer`, không ghi thẳng xuống loa. `audio_worker()` gom `local_prebuffer` đến khi đủ `jitter_ms` trước khi phát. Mặc định `jitter_ms=60`, nằm trong đề xuất prebuffer 40-80 ms.

Jitter Buffer là bắt buộc vì TTS streaming không đảm bảo inter-arrival đều tuyệt đối. Nếu TTS chậm vài chục ms mà audio driver đã cần period tiếp theo, ALSA/PipeWire có thể underrun và gây crackling. Buffer cần đủ nhỏ để không tăng TTFT quá mức:

- Prebuffer đề xuất: 40-80 ms.
- Target buffer đề xuất: 80-150 ms.
- Nếu buffer thấp: ưu tiên sinh TTS nhanh hơn hoặc chèn silence rất ngắn có fade để tránh pop.
- Nếu buffer đầy: không prebuffer thêm quá nhiều để tránh tăng latency.

### Phần 5: Audio Output Pipeline dùng ALSA hoặc PipeWire

Repo có module phát PCM raw qua `AudioSink`:

- `NullAudioSink`: mô phỏng thời gian phát, dùng cho benchmark không có audio hardware.
- `WavAudioSink`: ghi WAV để kiểm tra dữ liệu PCM.
- `AlsaAudioSink`: ghi trực tiếp ALSA khi build với `EDGEVOICE_WITH_ALSA=ON`.

Logic ALSA trong `AlsaAudioSink`:

- `snd_pcm_open()` mở playback device.
- `snd_pcm_hw_params_set_access(... SND_PCM_ACCESS_RW_INTERLEAVED)`.
- `snd_pcm_hw_params_set_format(... SND_PCM_FORMAT_S16_LE)`.
- `snd_pcm_hw_params_set_channels()`.
- `snd_pcm_hw_params_set_rate_near()`.
- `snd_pcm_hw_params_set_period_size_near()`.
- `snd_pcm_hw_params_set_buffer_size_near()`.
- `snd_pcm_writei()` ghi PCM frames.
- Nếu xrun `-EPIPE`: gọi `snd_pcm_prepare()`.
- Nếu lỗi âm: gọi `snd_pcm_recover()`.
- Khi barge-in: `snd_pcm_drop()` rồi `snd_pcm_prepare()`.

Không nên lạm dụng thư viện phát audio cấp cao vì các lớp này thường có buffer ẩn, resampling ẩn hoặc scheduler riêng, làm khó kiểm soát TTFT và barge-in.

Ảnh hưởng tham số:

- `buffer_size` quá nhỏ: ít dữ liệu dự phòng, nhiều interrupt, CPU cao, dễ crackling/underrun.
- `buffer_size` quá lớn: tăng latency, TTFT và thời gian âm thanh cũ còn nằm trong driver.
- `period_size` nhỏ: phản ứng nhanh hơn nhưng interrupt dày hơn.
- `period_size` lớn: ổn định hơn nhưng tăng độ trễ phản ứng.

Benchmark Pi 5 cần sweep `period_ms`, `buffer_ms`, `jitter_ms`, đo `underruns`, `max_audio_gap_ms`, TTFT, CPU và thermal.

### Phần 6: Tránh hallucination/repetition trong Streaming ASR

ASR đa ngôn ngữ streaming dễ gặp lỗi lặp như "rotary rotary rotary", đặc biệt khi audio nhiễu, context quá dài hoặc model bị bias mạnh bởi hotword tiếng Anh.

Cấu hình decoding đề xuất:

- Bắt đầu bằng greedy search để giữ latency thấp.
- Nếu cần beam search, chỉ dùng beam size 2-3.
- Dùng repetition penalty hoặc no-repeat-ngram nhẹ nếu backend hỗ trợ.
- Với CTC/RNN-T, dùng blank penalty và endpointing phù hợp để không commit quá sớm hoặc quá muộn.
- Giới hạn context window để tránh model bị kẹt vòng lặp.
- Dùng hotword/context biasing nhỏ cho `rotary actuator`, `BMS`, `CAN bus`, `sensor vision`.

Không dùng beam quá lớn vì tăng CPU, RAM và decoding latency trên Cortex-A76. Beam lớn cũng làm partial result dao động nhiều hơn, khiến splitter khó quyết định commit và có thể đẩy TTFT vượt 500 ms.

Repo hiện chưa có ASR decoder thật nên các cấu hình trên chưa nằm trong code; đây là phần giải trình thiết kế cho adapter ASR thật.

### Phần 7: Chiến lược tối ưu ALSA period_size và buffer_size

Chiến lược khởi đầu trên Pi 5:

- `sample_rate`: 22050 Hz hoặc 24000 Hz tùy output của TTS.
- `period_ms`: 10-20 ms.
- `buffer_ms`: 3-4 periods, ví dụ 80-160 ms.
- `jitter_ms`: 40-80 ms.

Công thức:

```text
period_ms = period_size / sample_rate * 1000
buffer_ms = buffer_size / sample_rate * 1000
period_size = sample_rate * period_ms / 1000
buffer_size = sample_rate * buffer_ms / 1000
```

Với 24000 Hz:

- 20 ms period = 480 frames.
- 120 ms buffer = 2880 frames.
- 60 ms jitter = 1440 frames.

Benchmark tuning:

1. Bắt đầu `period_ms=20`, `buffer_ms=120`, `jitter_ms=60`.
2. Đo `underruns`, `max_audio_gap_ms`, `ttft_max_ms`, CPU usage và nhiệt độ.
3. Nếu crackling hoặc underrun: tăng nhẹ `buffer_ms` hoặc `jitter_ms`; chỉ tăng `period_ms` khi CPU bị interrupt pressure.
4. Nếu TTFT cao: giảm `jitter_ms`, sau đó giảm `buffer_ms`.
5. Mục tiêu là đủ an toàn cho audio nhưng không làm tổng phản hồi vượt 500 ms.

### Phần 8: Xử lý Barge-in dưới 200 ms

Khi robot đang nói mà kỹ sư hô "Dừng lại, tắt động cơ ngay!", pipeline cần xử lý theo fast path:

1. ASR/VAD vẫn nghe trong lúc TTS phát.
2. Barge-in detector phân loại đây là lệnh khẩn cấp.
3. Đặt `cancel_token` hoặc tăng `epoch`.
4. TTS worker dừng sinh chunk mới.
5. Xóa `text_queue` chưa xử lý.
6. Xóa PCM queue và Jitter Buffer.
7. Nếu dùng ALSA, gọi `snd_pcm_drop()` để cắt audio trong driver, sau đó `snd_pcm_prepare()`.
8. Ưu tiên xử lý lệnh khẩn cấp mới bằng epoch mới.

Trong source hiện có:

- `RunState::epoch` là atomic generation id.
- `flush_audio_pipeline()` tăng epoch, clear `text_queue`, clear `jitter_buffer`, set `flush_requested`.
- `tts_worker()` kiểm tra epoch trước mỗi PCM chunk.
- `audio_worker()` khi thấy `flush_requested` sẽ clear prebuffer, clear jitter buffer và gọi `sink->flush()`.
- `AlsaAudioSink::flush()` gọi `snd_pcm_drop()` và `snd_pcm_prepare()`.

Cách đảm bảo dưới 200 ms là không chờ TTS hoàn tất và không chờ audio buffer phát hết. Hệ thống dùng cancel flag/epoch và flush buffer ngay. Với chunk 20-40 ms, period 10-20 ms và driver flush trực tiếp, đường phản ứng có biên an toàn tốt; tuy nhiên repo hiện mới chứng minh trên null sink simulated, chưa chứng minh trên ALSA thật.

### Phần 9: Pseudo-code Python cho ASR, splitter, TTS, jitter buffer và audio output

```python
import queue
import threading
import time


class CancelToken:
    def __init__(self):
        self._lock = threading.Lock()
        self._epoch = 0
        self.flush_requested = threading.Event()

    def epoch(self):
        with self._lock:
            return self._epoch

    def cancel(self):
        with self._lock:
            self._epoch += 1
        self.flush_requested.set()


class RealtimeSplitter:
    def __init__(self, min_tokens=4, max_tokens=16):
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens
        self.last_emitted_pos = 0
        self.last_partial = ""
        self.emitted_segments = set()

    def process_partial(self, partial_text):
        text = " ".join(partial_text.strip().split())

        # ASR có thể sửa partial cũ; phần đã emit không phát lại.
        if len(text) < self.last_emitted_pos:
            self.last_emitted_pos = len(text)

        pending = text[self.last_emitted_pos:]
        out = []

        boundary = self._first_boundary(pending)
        if boundary is not None:
            segment = pending[: boundary + 1].strip()
            if len(segment.split()) >= self.min_tokens:
                self._emit(segment, out)
                self.last_emitted_pos += boundary + 1
                self.last_partial = text
                return out

        tokens = pending.split()
        if len(tokens) >= self.max_tokens:
            segment = " ".join(self._cut_at_clause_marker(tokens))
            self._emit(segment, out)
            self.last_emitted_pos += len(segment)

        self.last_partial = text
        return out

    def flush(self):
        out = []
        self._emit(self.last_partial[self.last_emitted_pos :].strip(), out)
        return out

    def _emit(self, segment, out):
        normalized = " ".join(segment.split())
        if normalized and normalized not in self.emitted_segments:
            self.emitted_segments.add(normalized)
            out.append(normalized)

    def _first_boundary(self, text):
        positions = [text.find(ch) for ch in [",", ".", "?", "!", ";", ":"]]
        positions = [p for p in positions if p >= 0]
        return min(positions) if positions else None

    def _cut_at_clause_marker(self, tokens):
        markers = {"đồng", "sau", "rồi", "và", "and", "then"}
        for i in range(min(len(tokens), self.max_tokens) - 1, self.min_tokens - 1, -1):
            if tokens[i].lower() in markers:
                return tokens[: i + 1]
        return tokens[: self.max_tokens]


class AudioDevice:
    def open(self, sample_rate, channels, fmt, period_size, buffer_size):
        # ALSA thật: snd_pcm_open + hw_params + snd_pcm_prepare.
        pass

    def write_pcm(self, pcm_chunk):
        # ALSA thật: snd_pcm_writei(handle, frames).
        return True

    def flush(self):
        # ALSA thật: snd_pcm_drop(handle); snd_pcm_prepare(handle).
        pass


text_queue = queue.Queue()
pcm_audio_queue = queue.Queue()
jitter_buffer = queue.Queue()
cancel_token = CancelToken()
splitter = RealtimeSplitter(min_tokens=4, max_tokens=16)


def asr_streaming_callback(partial_text):
    current_epoch = cancel_token.epoch()
    for segment in splitter.process_partial(partial_text):
        text_queue.put({
            "epoch": current_epoch,
            "text": segment,
            "boundary_time": time.monotonic(),
        })


def tts_audio_stream_worker(valtec_tts):
    while True:
        job = text_queue.get()
        if job is None:
            return
        if job["epoch"] != cancel_token.epoch():
            continue

        for pcm_chunk in valtec_tts.stream(job["text"]):
            if job["epoch"] != cancel_token.epoch():
                break
            pcm_audio_queue.put({
                "epoch": job["epoch"],
                "pcm": pcm_chunk,
                "boundary_time": job["boundary_time"],
            })


def jitter_worker(target_ms=120):
    buffered_ms = 0
    while True:
        item = pcm_audio_queue.get()
        if item is None:
            jitter_buffer.put(None)
            return
        if item["epoch"] != cancel_token.epoch():
            continue

        jitter_buffer.put(item)
        buffered_ms += item["pcm"].duration_ms
        if buffered_ms > target_ms:
            time.sleep(0.005)


def audio_output_worker(audio_device):
    audio_device.open(
        sample_rate=24000,
        channels=1,
        fmt="S16_LE",
        period_size=480,
        buffer_size=2880,
    )

    while True:
        if cancel_token.flush_requested.is_set():
            flush_audio_pipeline(audio_device)
            cancel_token.flush_requested.clear()

        try:
            item = jitter_buffer.get(timeout=0.02)
        except queue.Empty:
            log_underrun("jitter buffer empty")
            continue

        if item is None:
            return
        if item["epoch"] != cancel_token.epoch():
            continue

        ok = audio_device.write_pcm(item["pcm"])
        if not ok:
            log_underrun("audio write failed or ALSA xrun")


def flush_audio_pipeline(audio_device):
    clear_queue(text_queue)
    clear_queue(pcm_audio_queue)
    clear_queue(jitter_buffer)
    audio_device.flush()


def on_barge_in_urgent_command(command_text):
    cancel_token.cancel()
    dispatch_safety_command(command_text)


def clear_queue(q):
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return


def log_underrun(reason):
    print({"event": "underrun", "reason": reason, "ts": time.monotonic()})
```

### Phần 10: Trả lời 3 câu hỏi giải trình

#### 1. Tránh hallucination/repetition trong ASR đa ngôn ngữ streaming

Nên chọn greedy search làm baseline vì latency thấp và phù hợp KPI TTFT. Nếu môi trường nhiễu hoặc thuật ngữ tiếng Anh khó, dùng beam search nhỏ 2-3. Không dùng beam lớn vì tăng decoding time, CPU/RAM và làm partial result dao động.

Penalty nên đặt nhẹ: repetition penalty hoặc no-repeat-ngram 2/3 chỉ để chặn lặp bất thường như "rotary rotary rotary". Với CTC/RNN-T, ưu tiên blank penalty và endpointing hợp lý. Hotword bias cho `rotary actuator`, `sensor vision`, `CAN bus`, `BMS` phải nhỏ để không hallucinate thuật ngữ khi người dùng không nói.

#### 2. Tối ưu ALSA Driver

`period_size` quyết định độ dày interrupt/audio callback. Period nhỏ giảm latency nhưng tăng interrupt pressure; period lớn ổn định hơn nhưng phản ứng chậm. `buffer_size` quyết định lượng audio dự phòng trong driver. Buffer nhỏ dễ underrun/crackling; buffer lớn tăng latency, TTFT và làm barge-in khó cắt nếu không flush driver.

Công thức:

```text
period_ms = period_size / sample_rate * 1000
buffer_ms = buffer_size / sample_rate * 1000
```

Benchmark trên Pi 5 nên bắt đầu 24000 Hz, period 20 ms, buffer 120 ms, jitter 60 ms. Nếu crackling, tăng buffer/jitter nhẹ. Nếu TTFT cao, giảm jitter trước, sau đó giảm buffer. Chỉ giảm period xuống 10 ms khi CPU còn dư và underrun vẫn bằng 0.

#### 3. Xử lý Interrupt/Barge-in dưới 200 ms

Khi robot đang nói, ASR/VAD vẫn chạy để phát hiện người chen ngang. Khi có lệnh khẩn cấp, hệ thống tăng `epoch` hoặc đặt `cancel_token`, xóa text queue, dừng TTS ở chunk boundary gần nhất, xóa PCM queue/jitter buffer, gọi `snd_pcm_drop()`/`snd_pcm_prepare()` nếu dùng ALSA, rồi xử lý lệnh mới với priority cao.

Điểm quan trọng là không chờ TTS hoàn tất và không chờ audio buffer phát hết. Đường interrupt phải là fast path riêng, không đi qua queue phản hồi bình thường.

## 3. Pipeline giả lập hoặc pipeline test

Repo hiện có pipeline giả lập trong `src/main.cpp`.

Input giả lập:

- Scenario mặc định `mixed_vi_en`: câu tiếng Việt pha tiếng Anh kỹ thuật.
- Scenario `barge_in`: câu phản hồi dài để mô phỏng robot đang nói khi bị ngắt.
- Có thể truyền `--text=...` để override input.

ASR giả lập:

- `make_partials()` chia input thành partial text theo `--asr-words-per-partial`.
- `asr_simulator()` sleep `--asr-partial-ms` giữa các partial.
- Partial đi qua `SentenceSplitter` rồi vào `text_queue`.

TTS giả lập:

- `tts_worker()` sleep `--tts-first-chunk-ms` trước chunk đầu.
- `generate_pcm_chunk()` sinh sine wave PCM S16_LE.
- PCM chunk có duration `--tts-chunk-ms`, số chunk mỗi segment là `--tts-chunks-per-segment`.

Audio giả lập:

- `--audio=null`: không phát loa, chỉ sleep tương ứng duration PCM để mô phỏng playback timing.
- `--audio=wav`: ghi WAV output.
- `--audio=alsa`: ghi ALSA thật nếu build có ALSA và host có audio device.

Simulated test chứng minh được:

- Thread/queue scheduling của pipeline.
- Cơ chế split partial text thành segment.
- TTS chunk streaming vào jitter buffer.
- TTFT từ lúc segment boundary đến lúc audio worker bắt đầu phát chunk đầu.
- Barge-in path: tăng epoch, clear queue, flush audio sink.

Simulated benchmark không thay thế benchmark thật trên Raspberry Pi 5. Nó không đo latency thật của microphone, ASR model, Valtec-TTS, ALSA device thật, spatial audio stack, CPU thermal hoặc crackling nghe thực tế.

## 4. Code map

| File/thư mục | Vai trò |
| --- | --- |
| `src/main.cpp` | Entry point và toàn bộ core pipeline hiện tại: options, queues, splitter, ASR simulator, TTS simulator, jitter/audio worker, ALSA/WAV/null sinks, metrics, barge-in. |
| `CMakeLists.txt` | Build C++17 binary `edge_voice_pipeline`, link Threads và ALSA nếu `EDGEVOICE_WITH_ALSA=ON`. |
| `config/benchmark_scenarios.json` | Mô tả scenario `mixed_vi_en`, `barge_in` và KPI mục tiêu. File này là tài liệu cấu hình, binary hiện không parse trực tiếp file này. |
| `config/pi5_audio_alsa.env` | Giá trị env gợi ý cho Pi 5: ALSA device, period/buffer/jitter, split token, iterations, barge-in ms. |
| `benchmark_results/benchmark.jsonl` | Kết quả benchmark simulated/null sink cho scenario mixed. |
| `benchmark_results/benchmark_barge.jsonl` | Kết quả benchmark simulated/null sink cho scenario barge-in. |
| `scripts/summarize_benchmark.py` | Script tổng hợp JSONL thành p50/p95/p99/worst TTFT, barge-in và underrun. |
| `scripts/run_benchmark.sh` | Chạy benchmark mixed và barge-in trong container hoặc môi trường có binary. |
| `scripts/docker_build.ps1`, `scripts/docker_run.ps1` | Build/run Docker ARM64 từ Windows PowerShell. |
| `scripts/docker_build.sh`, `scripts/docker_run.sh` | Build/run Docker ARM64 từ Linux/macOS shell. |
| `scripts/pi_setup.sh` | Cài dependency native trên Raspberry Pi OS và thêm user vào group audio nếu có. |
| `scripts/pi_build_run.sh` | Build native trên Pi 5 bằng CMake/Ninja và chạy ALSA benchmark. |
| `docker/Dockerfile.pi5` | Multi-stage Docker build Debian Bookworm ARM64, cài CMake/Ninja/libasound2-dev, build binary và runtime image. |
| `docker/compose.yml` | Service `edge-voice-null` và `edge-voice-alsa`; ALSA service mount `/dev/snd`. |
| `docs/ARCHITECTURE.md` | Tóm tắt kiến trúc worker, queue, jitter buffer, barge-in. |
| `docs/BENCHMARK_PLAN.md` | Kế hoạch benchmark latency, buffer sweep, barge-in, soak test. |
| `docs/DEPLOYMENT_PLAN.md` | Kế hoạch chạy Docker, Docker có ALSA, native Pi 5, tích hợp model thật. |
| `docs/PI_NATIVE_PIPELINE.md` | Hướng dẫn build/chạy native, kiểm tra ALSA và công thức period/buffer. |
| `assignment_ai_edge_3.docx` | File đề/bài kiểm tra đính kèm trong repo; không tham gia build/runtime. |

Mapping theo khối yêu cầu:

- Entry point: `main()` trong `src/main.cpp`.
- Streaming pipeline/core logic: `run_once()`, `BlockingQueue<T>`, `RunState`.
- ASR streaming adapter: chưa có adapter thật; hiện là `asr_simulator()`.
- Token/sentence splitter: `SentenceSplitter`.
- TTS streaming adapter: chưa có Valtec-TTS thật; hiện là `tts_worker()` + `generate_pcm_chunk()`.
- Jitter buffer/audio output: `BlockingQueue<PcmChunk>` dùng như jitter buffer, `audio_worker()`, `AudioSink`.
- Barge-in/cancel logic: `flush_audio_pipeline()`, `RunState::epoch`, `RunState::flush_requested`.
- Benchmark: metric trong `Metrics`, JSONL output qua `append_line()`, summary script.
- Tests: chưa có thư mục/file unit test trong repo.
- Scripts build/run: thư mục `scripts/` và `docker/`.

## 5. Đã test gì

### Unit test

Chưa có unit test trong repo. Chưa có test riêng cho `SentenceSplitter`, `BlockingQueue`, ALSA sink hoặc barge-in race condition.

### Runtime smoke test

Repo có kết quả runtime smoke/benchmark simulated trong:

- `benchmark_results/benchmark.jsonl`
- `benchmark_results/benchmark_barge.jsonl`

Các file này chứng minh binary đã từng chạy với `--audio=null`, sinh JSONL metric và không báo lỗi trong các iteration được lưu.

Lưu ý: các JSONL hiện có được tạo trước lần chỉnh source/README gần nhất. Chúng vẫn là bằng chứng benchmark simulated đã chạy, nhưng cần chạy lại để xác nhận chính xác binary hiện tại sau khi thêm metric `split_min_tokens`/`split_max_tokens`.

### Benchmark đã đo gì

Các JSONL hiện có đo:

- `ttft_min_ms`, `ttft_avg_ms`, `ttft_max_ms`
- `underruns`
- `max_audio_gap_ms`
- `barge_in_reaction_ms` với scenario barge-in
- `segments`, `pcm_chunks`, `total_ms`

Kết quả nổi bật hiện tại từ `python scripts/summarize_benchmark.py benchmark_results/*.jsonl`:

| File | Loại | Count | TTFT p95 | TTFT worst | Barge worst | Underruns |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `benchmark_results/benchmark.jsonl` | simulated/null mixed | 10 | 197.316 ms | 198.859 ms | không áp dụng | 0 |
| `benchmark_results/benchmark_barge.jsonl` | simulated/null barge-in | 5 | 99.516 ms | 100.688 ms | 27.661 ms | 0 |

### Những phần chưa test xong

- Chưa có benchmark trên Raspberry Pi 5 thật trong repo.
- Chưa có benchmark ALSA thật với loa/mic.
- Chưa có test nghe crackling thực tế.
- Chưa có ASR partial latency thật.
- Chưa có TTS first chunk latency thật từ Valtec-TTS.
- Chưa có CPU/RAM/thermal soak test thật.
- Chưa có metric dropped/duplicated text chunks trong JSONL hiện tại.
- Chưa có CI hoặc unit test tự động.

## 6. Benchmark

### Cách chạy benchmark simulated/null

Sau khi build Docker image:

```powershell
.\scripts\docker_build.ps1
.\scripts\docker_run.ps1
```

Hoặc trên Linux:

```bash
./scripts/docker_build.sh
./scripts/docker_run.sh
```

Nếu đã có binary:

```bash
./edge_voice_pipeline --audio=null --iterations=20 --out=benchmark_results/benchmark.jsonl
./edge_voice_pipeline --audio=null --scenario=barge_in --barge-in-ms=450 --iterations=10 --out=benchmark_results/benchmark_barge.jsonl
```

Tổng hợp:

```bash
python3 scripts/summarize_benchmark.py benchmark_results/*.jsonl
```

### Cách chạy benchmark ALSA/Pi 5

```bash
chmod +x scripts/*.sh
./scripts/pi_setup.sh
ALSA_DEVICE=hw:0,0 PERIOD_MS=20 BUFFER_MS=120 JITTER_MS=60 ./scripts/pi_build_run.sh
```

Kết quả native dự kiến ghi vào:

```text
benchmark_results/pi_native_alsa.jsonl
```

### Metric cần ghi nhận

| Metric | Ý nghĩa | Trạng thái trong repo |
| --- | --- | --- |
| TTFT | Từ lúc splitter commit segment đến lúc audio worker phát chunk đầu | Có: `ttft_*_ms` |
| partial ASR latency | Từ audio frame/mic đến ASR partial | Chưa có, vì ASR đang simulated text |
| splitter latency | Thời gian xử lý partial thành segment | Chưa đo riêng |
| TTS first chunk latency | Từ text segment đến PCM chunk đầu | Mô phỏng bằng `tts_first_chunk_ms`, chưa đo TTS thật |
| jitter buffer underrun count | Số lần audio worker timeout/xrun | Có: `underruns` |
| audio write latency | Thời gian `snd_pcm_writei`/audio write | Chưa đo riêng |
| CPU usage | Tải CPU khi chạy pipeline | Chưa ghi vào JSONL |
| RAM slope | Tăng RAM theo thời gian soak test | Chưa ghi vào JSONL |
| barge-in reaction time | Từ request ngắt đến lúc audio flush | Có: `barge_in_reaction_ms` |
| dropped/duplicated text chunks | Số segment mất/trùng do ASR partial | Chưa ghi metric riêng; splitter có cơ chế chống duplicate |

Benchmark hiện có là simulated/emulated với `--audio=null`, không phải real hardware. Benchmark real hardware cần chạy trên Raspberry Pi 5 với `--audio=alsa` và nghe kiểm tra crackling.

## 7. Cách chạy

### Local/simulated

Repo không có binary prebuilt. Cần build bằng CMake hoặc Docker.

Nếu có CMake/Ninja và không cần ALSA:

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DEDGEVOICE_WITH_ALSA=OFF
cmake --build build --target edge_voice_pipeline
./build/edge_voice_pipeline --audio=null --iterations=5
```

Nếu build có ALSA trên Linux:

```bash
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DEDGEVOICE_WITH_ALSA=ON
cmake --build build --target edge_voice_pipeline
./build/edge_voice_pipeline --audio=alsa --alsa-device=default --iterations=20
```

### Docker

Windows PowerShell:

```powershell
.\scripts\docker_build.ps1
.\scripts\docker_run.ps1
```

Linux/macOS shell:

```bash
./scripts/docker_build.sh
./scripts/docker_run.sh
```

Docker Compose với null sink:

```bash
docker compose -f docker/compose.yml run --rm edge-voice-null
```

Docker Compose với ALSA trên Linux host có `/dev/snd`:

```bash
docker compose -f docker/compose.yml run --rm edge-voice-alsa
```

### Raspberry Pi 5 native

```bash
chmod +x scripts/*.sh
./scripts/pi_setup.sh
./scripts/pi_build_run.sh
```

Tùy chỉnh:

```bash
ALSA_DEVICE=hw:0,0 \
PERIOD_MS=20 \
BUFFER_MS=120 \
JITTER_MS=60 \
SPLIT_MIN_TOKENS=4 \
SPLIT_MAX_TOKENS=16 \
ITERATIONS=50 \
./scripts/pi_build_run.sh
```

### Real backend/hardware

Chưa có trong repo. Để chạy real backend cần:

- Thay `asr_simulator()` bằng adapter Zipformer Multilingual hoặc Whisper-Tiny streaming wrapper.
- Thay `generate_pcm_chunk()` bằng Valtec-TTS streaming chunk generator.
- Giữ output PCM S16_LE cùng sample rate/channels với ALSA config.
- Giữ `text_queue`, `jitter_buffer`, `audio_worker()` và `flush_audio_pipeline()` để benchmark trước/sau công bằng.

### Test

Chưa có unit test. Smoke/benchmark hiện chạy bằng binary và JSONL:

```bash
./edge_voice_pipeline --audio=null --iterations=5 --out=benchmark_results/benchmark.jsonl
./edge_voice_pipeline --audio=null --scenario=barge_in --barge-in-ms=450 --iterations=5 --out=benchmark_results/benchmark_barge.jsonl
python3 scripts/summarize_benchmark.py benchmark_results/*.jsonl
```

## 8. Trạng thái hiện tại

### Đã có

- C++17 prototype pipeline một file trong `src/main.cpp`.
- Thread-safe `BlockingQueue<T>`.
- `SentenceSplitter` có `split_min_tokens`, `split_max_tokens`, hard boundary, soft boundary và chống duplicate segment.
- ASR partial simulator cho scenario mixed Vietnamese-English.
- TTS simulator sinh PCM sine chunk.
- Jitter/prebuffer trong `audio_worker()`.
- Audio sink `null`, `wav`, `alsa`.
- ALSA path có `snd_pcm_writei`, recover xrun, `snd_pcm_drop`/`prepare` khi flush.
- Barge-in simulated bằng epoch/cancel và clear queue.
- JSONL metrics cho TTFT, underrun, max audio gap, barge-in reaction.
- Docker ARM64 build/runtime.
- Script native Pi 5 build/run.
- Benchmark simulated/null đã có trong `benchmark_results/`.

### Chưa có

- Chưa có ASR model thật.
- Chưa có Valtec-TTS thật.
- Chưa có microphone capture/VAD thật.
- Chưa có echo cancellation/ducking để nghe barge-in khi robot đang nói.
- Chưa có spatial audio pipeline thật.
- Chưa có PipeWire implementation trong code.
- Chưa có unit test tự động.
- Chưa có CI.
- Chưa có benchmark Raspberry Pi 5/ALSA thật trong repo.
- Chưa có đo CPU/RAM/thermal trong JSONL.
- Chưa có metric partial ASR latency, splitter latency riêng, audio write latency riêng, dropped/duplicated chunks.

### Cần làm tiếp để thành bản hoàn chỉnh

1. Tách `src/main.cpp` thành module rõ hơn: ASR adapter, splitter, TTS adapter, jitter buffer, audio sink, metrics.
2. Thêm unit test cho `SentenceSplitter`, `BlockingQueue`, duplicate partial và partial correction.
3. Tích hợp Zipformer Multilingual streaming hoặc Whisper-Tiny sliding window.
4. Tích hợp Valtec-TTS streaming, đo first PCM chunk latency thật.
5. Thêm microphone/VAD/echo suppression cho barge-in thật.
6. Chạy benchmark native trên Raspberry Pi 5 với `--audio=alsa`.
7. Sweep period/buffer/jitter trên Pi 5 và ghi `pi_native_alsa.jsonl`.
8. Bổ sung CPU/RAM/thermal monitoring và soak test 500+ iterations.
9. Thêm metric dropped/duplicated text chunks và ASR repetition rate.
10. Nếu cần spatial audio routing, thêm PipeWire backend hoặc bridge sang hệ spatial audio đang dùng.
