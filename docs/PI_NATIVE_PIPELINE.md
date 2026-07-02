# Raspberry Pi Native Pipeline

## Build

```bash
./scripts/pi_setup.sh
./scripts/pi_build_run.sh
```

Binary nằm tại:

```bash
build-pi/edge_voice_pipeline
```

## Kiểm tra ALSA

```bash
aplay -L
speaker-test -t sine -f 1000 -c 1
```

Chạy với thiết bị cụ thể:

```bash
./build-pi/edge_voice_pipeline \
  --audio=alsa \
  --alsa-device=hw:0,0 \
  --iterations=20 \
  --period-ms=20 \
  --buffer-ms=120 \
  --jitter-ms=60 \
  --split-min-tokens=4 \
  --split-max-tokens=16 \
  --out=benchmark_results/pi_native_alsa.jsonl
```

## Công thức dò period/buffer

Với sample rate 24 kHz:

- `period_frames = sample_rate * period_ms / 1000`
- `buffer_frames = sample_rate * buffer_ms / 1000`
- `jitter_frames = sample_rate * jitter_ms / 1000`

Ví dụ:

- period 20 ms -> 480 frames.
- buffer 120 ms -> 2880 frames.
- jitter 60 ms -> 1440 frames.

Giảm latency theo thứ tự:

1. Giảm jitter từ 80 xuống 60, rồi 40 ms.
2. Giảm buffer từ 160 xuống 120, rồi 80 ms.
3. Chỉ giảm period xuống 10 ms nếu CPU vẫn dư và không phát sinh interrupt pressure.

## Tích hợp ASR/TTS thật

Giữ nguyên các contract sau:

- ASR gọi callback bằng partial text càng sớm càng tốt.
- Splitter chỉ phát segment chưa từng phát.
- TTS trả PCM chunk nhỏ, đều, không gom cả câu.
- Audio sink chỉ nhận PCM S16_LE đã thống nhất sample rate/channels.

Pseudo-code nối model thật:

```cpp
void asr_streaming_callback(std::string partial_text) {
  for (auto segment : splitter.process_partial(partial_text)) {
    text_queue.push(TextJob{next_id(), current_epoch(), segment, Clock::now()});
  }
}

void tts_audio_stream_worker() {
  while (text_queue.pop(job)) {
    for (auto pcm_chunk : valtec_tts.stream(job.text)) {
      if (job.epoch != current_epoch()) break;
      jitter_buffer.push(pcm_chunk);
    }
  }
}
```

## Barge-in native

Khi ASR phát hiện lệnh ngắt:

1. Tăng `epoch`.
2. Clear text queue để không đọc tiếp phản hồi cũ.
3. Hủy TTS worker ở chunk boundary gần nhất.
4. Clear jitter buffer.
5. Gọi `snd_pcm_drop`, sau đó `snd_pcm_prepare`.
6. Bắt đầu xử lý command khẩn cấp bằng epoch mới.
