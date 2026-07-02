from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def generate_synthetic_pcm(duration_sec: float, sample_rate: int = 16000, freq: float = 440.0) -> np.ndarray:
    """Generate mono float32 PCM in RAM. No file I/O."""
    n = int(duration_sec * sample_rate)
    t = np.arange(n, dtype=np.float32) / sample_rate
    # Speech-like signal: sine + envelope + tiny noise, deterministic.
    envelope = np.minimum(1.0, np.maximum(0.0, np.sin(np.pi * np.arange(n, dtype=np.float32) / max(n, 1))))
    pcm = 0.12 * envelope * np.sin(2 * np.pi * freq * t)
    pcm += 0.005 * np.sin(2 * np.pi * 73.0 * t)
    return pcm.astype(np.float32)


def read_wav_as_mono_float32(path: str | Path, target_sample_rate: int = 16000) -> np.ndarray:
    """Minimal WAV reader for 16-bit PCM mono/stereo files.

    This avoids external dependencies. For serious resampling, use soxr/librosa/scipy,
    but keep this benchmark lightweight.
    """
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sr = wf.getframerate()
        sampwidth = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())
    if sampwidth != 2:
        raise ValueError("Only 16-bit PCM WAV is supported by this lightweight reader")
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if sr != target_sample_rate:
        # Simple linear interpolation resampling for testing correctness only.
        old_x = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
        new_len = int(len(audio) * target_sample_rate / sr)
        new_x = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
        audio = np.interp(new_x, old_x, audio).astype(np.float32)
    return audio.astype(np.float32)
