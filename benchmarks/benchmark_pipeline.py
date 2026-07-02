from __future__ import annotations

import argparse
import json
import os
import statistics

from edge_voice_test.audio import generate_synthetic_pcm, read_wav_as_mono_float32
from edge_voice_test.backends import BackendConfig
from edge_voice_test.metrics import write_csv
from edge_voice_test.pipeline import VoicePipeline


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark the voice pipeline")
    p.add_argument("--asr-backend", choices=["simulated", "whisper-cpp"], default="simulated")
    p.add_argument("--tts-backend", choices=["simulated", "piper"], default="simulated")
    p.add_argument("--quant", choices=["FP16", "Q8", "Q5", "Q4"], default="Q5")
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--duration", type=float, default=5.0)
    p.add_argument("--loops", type=int, default=50)
    p.add_argument("--warm-up-loops", type=int, default=1)
    p.add_argument("--time-scale", type=float, default=0.02)
    p.add_argument("--wav", type=str, default="")
    p.add_argument("--leak-bytes-per-call", type=int, default=0)
    p.add_argument("--out", type=str, default="results/benchmark_pipeline.csv")
    p.add_argument("--redact-transcript", action="store_true")
    p.add_argument("--whisper-model", default="models/whisper/ggml-tiny.bin")
    p.add_argument("--whisper-cpp-bin", default=os.getenv("WHISPER_CPP_BIN", ""))
    p.add_argument("--piper-model", default="models/piper/vi_VN-vais1000-medium/vi_VN-vais1000-medium.onnx")
    p.add_argument("--piper-config", default="models/piper/vi_VN-vais1000-medium/vi_VN-vais1000-medium.onnx.json")
    p.add_argument("--piper-bin", default=os.getenv("PIPER_BIN", ""))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.loops < 1:
        raise ValueError("--loops must be >= 1")
    if args.warm_up_loops < 0:
        raise ValueError("--warm-up-loops must be >= 0")

    config = BackendConfig(
        quant=args.quant,
        num_threads=args.threads,
        time_scale=args.time_scale,
        leak_bytes_per_call=args.leak_bytes_per_call,
        asr_backend=args.asr_backend,
        tts_backend=args.tts_backend,
        whisper_model=args.whisper_model,
        whisper_cpp_bin=args.whisper_cpp_bin,
        piper_model=args.piper_model,
        piper_config=args.piper_config,
        piper_bin=args.piper_bin,
    )
    pipeline = VoicePipeline(config)
    warmups = [
        pipeline.warm_up().to_dict(redact_transcript=args.redact_transcript)
        for _ in range(args.warm_up_loops)
    ]

    if args.wav:
        pcm = read_wav_as_mono_float32(args.wav, target_sample_rate=config.sample_rate)
    else:
        pcm = generate_synthetic_pcm(args.duration, sample_rate=config.sample_rate)

    rows = []
    for i in range(args.loops):
        pipeline.start_recording()
        chunk_size = config.sample_rate // 2
        for start in range(0, len(pcm), chunk_size):
            pipeline.append_audio_chunk(pcm[start : start + chunk_size])
        result = pipeline.stop_and_process()
        row = result.to_dict(redact_transcript=args.redact_transcript)
        row["loop"] = i + 1
        asr_load_count, tts_load_count = pipeline.load_counts()
        row["asr_load_count"] = asr_load_count
        row["tts_load_count"] = tts_load_count
        rows.append(row)

    write_csv(rows, args.out)
    ram_first = rows[0]["ram_after_mb"]
    ram_last = rows[-1]["ram_after_mb"]
    ram_slope = (ram_last - ram_first) / max(args.loops - 1, 1)
    asr_load_count, tts_load_count = pipeline.load_counts()
    rtf_values = [r["rtf"] for r in rows]
    wall_rtf_values = [r["rtf_wall"] for r in rows]
    summary = {
        "asr_backend": args.asr_backend,
        "tts_backend": args.tts_backend,
        "quant": args.quant,
        "threads": args.threads,
        "loops": args.loops,
        "warm_up_loops": args.warm_up_loops,
        "audio_duration_sec": rows[0]["audio_duration_sec"],
        "mean_asr_time_sec": statistics.mean(r["asr_time_sec"] for r in rows),
        "mean_tts_time_sec": statistics.mean(r["tts_time_sec"] for r in rows),
        "mean_total_time_sec": statistics.mean(r["total_time_sec"] for r in rows),
        "mean_rtf": statistics.mean(rtf_values),
        "p95_rtf": sorted(rtf_values)[int(0.95 * (len(rows) - 1))],
        "mean_wall_rtf": statistics.mean(wall_rtf_values),
        "p95_wall_rtf": sorted(wall_rtf_values)[int(0.95 * (len(rows) - 1))],
        "ram_first_mb": ram_first,
        "ram_last_mb": ram_last,
        "ram_slope_mb_per_loop": ram_slope,
        "asr_load_count": asr_load_count,
        "tts_load_count": tts_load_count,
        "wer_delta_estimate": rows[0]["wer_delta_estimate"],
        "rtf_pass": statistics.mean(r["rtf"] for r in rows) < 0.3,
        "load_once_pass": asr_load_count == 1 and tts_load_count == 1,
        "memory_leak_pass_simple": ram_slope < 0.05,
        "warm_up": warmups,
        "csv": args.out,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
