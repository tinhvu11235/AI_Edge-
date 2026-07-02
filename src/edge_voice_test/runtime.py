from __future__ import annotations

import argparse
import json
import os

from .audio import generate_synthetic_pcm, read_wav_as_mono_float32
from .backends import BackendConfig
from .pipeline import VoicePipeline


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the voice pipeline runtime smoke test")
    p.add_argument("--asr-backend", choices=["simulated", "whisper-cpp"], default="simulated")
    p.add_argument("--tts-backend", choices=["simulated", "piper"], default="simulated")
    p.add_argument("--quant", choices=["FP16", "Q8", "Q5", "Q4"], default="Q5")
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--duration", type=float, default=2.0)
    p.add_argument("--loops", type=int, default=1)
    p.add_argument("--wav", default="")
    p.add_argument("--whisper-model", default="models/whisper/ggml-tiny.bin")
    p.add_argument("--whisper-cpp-bin", default=os.getenv("WHISPER_CPP_BIN", ""))
    p.add_argument("--piper-model", default="models/piper/vi_VN-vais1000-medium/vi_VN-vais1000-medium.onnx")
    p.add_argument("--piper-config", default="models/piper/vi_VN-vais1000-medium/vi_VN-vais1000-medium.onnx.json")
    p.add_argument("--piper-bin", default=os.getenv("PIPER_BIN", ""))
    p.add_argument("--skip-warm-up", action="store_true")
    p.add_argument("--redact-transcript", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    config = BackendConfig(
        quant=args.quant,
        num_threads=args.threads,
        time_scale=0.0 if args.asr_backend != "simulated" or args.tts_backend != "simulated" else 0.02,
        asr_backend=args.asr_backend,
        tts_backend=args.tts_backend,
        whisper_model=args.whisper_model,
        whisper_cpp_bin=args.whisper_cpp_bin,
        piper_model=args.piper_model,
        piper_config=args.piper_config,
        piper_bin=args.piper_bin,
    )
    pipeline = VoicePipeline(config)
    warmup = None
    if not args.skip_warm_up:
        warmup = pipeline.warm_up()

    if args.wav:
        pcm = read_wav_as_mono_float32(args.wav, target_sample_rate=config.sample_rate)
    else:
        pcm = generate_synthetic_pcm(args.duration, sample_rate=config.sample_rate)

    result = None
    for _ in range(args.loops):
        pipeline.start_recording()
        chunk_size = config.sample_rate // 2
        for start in range(0, len(pcm), chunk_size):
            pipeline.append_audio_chunk(pcm[start : start + chunk_size])
        result = pipeline.stop_and_process()

    asr_load_count, tts_load_count = pipeline.load_counts()
    payload = result.to_dict(redact_transcript=args.redact_transcript) if result else {}
    payload["runtime_ok"] = True
    payload["asr_load_count"] = asr_load_count
    payload["tts_load_count"] = tts_load_count
    payload["warm_up"] = warmup.to_dict(redact_transcript=args.redact_transcript) if warmup else None
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
