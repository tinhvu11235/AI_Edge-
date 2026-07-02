from __future__ import annotations

import hashlib
import math
import time

import numpy as np

from .base import BackendConfig


class SimulatedASRBackend:
    """Deterministic fake ASR backend for unit tests and fast CI."""

    backend_name = "simulated"
    load_count = 0

    _BASE_RTF = {
        "FP16": 0.72,
        "Q8": 0.45,
        "Q5": 0.36,
        "Q4": 0.30,
    }

    _THREAD_SPEEDUP = {
        1: 1.00,
        2: 2.25,
        3: 2.35,
        4: 1.85,
    }

    _WER_DELTA = {
        "FP16": 0.00,
        "Q8": 0.004,
        "Q5": 0.012,
        "Q4": 0.026,
    }

    def __init__(self, config: BackendConfig):
        type(self).load_count += 1
        self.config = config
        self.model_loaded = True
        time.sleep(0.05 * config.time_scale)

    @property
    def wer_delta(self) -> float | None:
        return self._WER_DELTA[self.config.quant]

    def transcribe_pcm(self, pcm: np.ndarray) -> tuple[str, float]:
        if not self.model_loaded:
            raise RuntimeError("ASR model is not loaded")
        if not isinstance(pcm, np.ndarray):
            raise TypeError("ASR expects raw PCM numpy.ndarray")
        if pcm.ndim != 1:
            raise ValueError("ASR expects mono PCM with shape (num_samples,)")
        if pcm.dtype not in (np.float32, np.float64, np.int16):
            raise TypeError("PCM dtype must be float32, float64, or int16")

        duration_sec = len(pcm) / float(self.config.sample_rate)
        simulated_time = self._infer_time(duration_sec)
        time.sleep(simulated_time * self.config.time_scale)

        digest = hashlib.sha1(np.ascontiguousarray(pcm).view(np.uint8)).hexdigest()[:8]
        text = f"xin chao robot ma {digest}"
        return text, simulated_time

    def _infer_time(self, duration_sec: float) -> float:
        threads = max(1, min(int(self.config.num_threads), 4))
        speedup = self._THREAD_SPEEDUP[threads]
        rtf = self._BASE_RTF[self.config.quant] / speedup
        overhead = 0.055
        return overhead + duration_sec * rtf


class SimulatedTTSBackend:
    """Deterministic fake Piper-like TTS backend returning PCM bytes."""

    backend_name = "simulated"
    load_count = 0

    def __init__(self, config: BackendConfig):
        type(self).load_count += 1
        self.config = config
        self.model_loaded = True
        self._leak_bucket: list[bytes] = []
        time.sleep(0.05 * config.time_scale)

    def synthesize_to_pcm_bytes(self, text: str) -> tuple[bytes, float]:
        if not self.model_loaded:
            raise RuntimeError("TTS model is not loaded")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("TTS expects non-empty text")

        estimated_audio_sec = max(0.7, min(4.0, 0.055 * len(text)))
        simulated_time = 0.025 + estimated_audio_sec * 0.065
        time.sleep(simulated_time * self.config.time_scale)

        sr = self.config.sample_rate
        samples = int(estimated_audio_sec * sr)
        t = np.arange(samples, dtype=np.float32) / sr
        wave = 0.15 * np.sin(2.0 * math.pi * 220.0 * t)
        pcm_i16 = np.clip(wave * 32767, -32768, 32767).astype(np.int16)
        audio_bytes = pcm_i16.tobytes()

        if self.config.leak_bytes_per_call > 0:
            self._leak_bucket.append(b"x" * int(self.config.leak_bytes_per_call))

        return audio_bytes, simulated_time
