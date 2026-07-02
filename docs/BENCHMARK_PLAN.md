# Benchmark Plan

## KPI cần đo

1. TTFT: từ lúc splitter phát hiện biên mệnh đề đến lúc audio worker bắt đầu phát PCM chunk đầu.
2. Audio stability: số underrun/xrun, `max_audio_gap_ms`, và nghe kiểm tra crackling.
3. Barge-in reaction: từ lúc có tín hiệu ngắt đến lúc TTS bị hủy và audio buffer được flush.
4. CPU/RAM/thermal trên Pi 5 khi chạy liên tục.

## Bộ test chính

### Test A - Pipeline latency

```bash
./edge_voice_pipeline --audio=alsa --iterations=50 --out=benchmark_results/pi_latency.jsonl
```

Pass:

- `ttft_max_ms < 500`
- `underruns = 0`
- `max_audio_gap_ms < 20` sau khi đã ổn định buffer
- `segments` không bị trùng nội dung khi ASR partial lặp hoặc sửa lại

### Test B - Buffer sweep

Chạy ma trận audio:

| period_ms | buffer_ms | jitter_ms |
| --- | --- | --- |
| 10 | 80 | 40 |
| 20 | 120 | 60 |
| 20 | 160 | 80 |
| 30 | 180 | 90 |

Chiến lược chọn:

- Nếu underrun > 0: tăng `buffer_ms` hoặc `jitter_ms`.
- Nếu TTFT sát 500 ms: giảm `jitter_ms`, sau đó giảm `buffer_ms`.
- Điểm khởi đầu hợp lý cho Pi 5: `period_ms=20`, `buffer_ms=120`, `jitter_ms=60`.

Chạy thêm ma trận splitter:

| split_min_tokens | split_max_tokens | mục tiêu |
| --- | --- | --- |
| 4 | 12 | TTFT thấp, chấp nhận segment ngắn hơn |
| 4 | 16 | cấu hình cân bằng mặc định |
| 6 | 16 | giảm nguy cơ cắt vụn |

Chọn cấu hình sao cho `ttft_max_ms < 500`, segment nghe tự nhiên và không có duplicate partial.

### Test C - Barge-in

```bash
./edge_voice_pipeline \
  --audio=alsa \
  --scenario=barge_in \
  --barge-in-ms=450 \
  --iterations=30 \
  --out=benchmark_results/pi_barge.jsonl
```

Pass:

- `barge_in_reaction_ms < 200`
- `underruns = 0` sau flush/recover.
- Không còn âm thanh cũ tiếp tục phát sau lệnh ngắt.

### Test D - Soak test

```bash
ITERATIONS=500 ./scripts/pi_build_run.sh
```

Theo dõi song song:

```bash
pidstat -rud -p $(pidof edge_voice_pipeline) 1
vcgencmd measure_temp
```

Pass:

- Không crash.
- Không tăng RAM liên tục.
- Nhiệt độ không làm throttle kéo dài.

## Cách đọc JSONL

Mỗi dòng là một iteration:

```json
{"ttft_avg_ms":182.4,"ttft_max_ms":210.8,"underruns":0,"barge_in_reaction_ms":37.2}
```

Nên báo cáo p50, p95, p99 và worst-case. Worst-case quan trọng hơn trung bình vì đề bài yêu cầu cảm giác tương tác không có độ trễ nhận thức.

Tổng hợp nhanh:

```bash
python3 scripts/summarize_benchmark.py benchmark_results/*.jsonl
```

## Benchmark khi thay model thật

Giữ nguyên 4 test trên và chỉ thay adapter:

- ASR adapter: đo thêm partial stability, token drop, repetition rate.
- TTS adapter: đo thêm first PCM chunk latency và chunk inter-arrival jitter.
- Audio sink: giữ nguyên để so sánh công bằng giữa stub và model thật.
- Splitter: đo thêm duplicate segment count và số lần ASR correction trước committed boundary.

## ASR decoding checklist

- Ưu tiên greedy hoặc small beam cho streaming để giữ latency.
- Dùng repetition penalty/no-repeat ngram ở mức nhẹ nếu model hỗ trợ.
- Giới hạn max token per partial và reset context khi phát hiện vòng lặp.
- Với code-switching, không ép language ID thủ công từng đoạn; dùng multilingual model và giữ partial text thô.
- Log token timestamp/confidence để phát hiện token dropping ở biên Việt-Anh.
