from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
import psutil

from .backends import ASRBackend, BackendConfig, TTSBackend, create_asr_backend, create_tts_backend


@dataclass
class InferenceResult:
    audio_duration_sec: float
    asr_time_sec: float
    tts_time_sec: float
    total_time_sec: float
    rtf: float
    wall_time_sec: float
    rtf_wall: float
    ram_before_mb: float
    ram_after_mb: float
    ram_delta_mb: float
    transcript: str
    tts_pcm_bytes: int
    quant: str
    num_threads: int
    asr_backend: str
    tts_backend: str
    wer_delta_estimate: float | None
    passed_rtf: bool

    def to_dict(self, redact_transcript: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if redact_transcript:
            data["transcript"] = "<redacted>"
        # Backward-compatible aliases for the original simulated benchmark CSV.
        data["asr_time_sec_sim"] = self.asr_time_sec
        data["tts_time_sec_sim"] = self.tts_time_sec
        data["total_time_sec_sim"] = self.total_time_sec
        data["rtf_sim"] = self.rtf
        data["passed_rtf_sim"] = self.passed_rtf
        return data


@dataclass
class WarmupResult:
    audio_duration_sec: float
    wall_time_sec: float
    ram_before_mb: float
    ram_after_mb: float
    ram_delta_mb: float
    transcript: str
    tts_pcm_bytes: int

    def to_dict(self, redact_transcript: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if redact_transcript:
            data["transcript"] = "<redacted>"
        return data


class VoicePipeline:
    """Push-to-talk pipeline.

    Important properties for the AI Edge test:
    - ASR/TTS are loaded exactly once in __init__.
    - start_recording/append_audio_chunk/stop_and_process implement PTT flow.
    - The pipeline accepts raw PCM in memory. CLI-only real backends may still
      use /dev/shm temp files internally because their tools consume files.
    """

    def __init__(
        self,
        config: BackendConfig,
        asr_backend: ASRBackend | None = None,
        tts_backend: TTSBackend | None = None,
    ):
        self.config = config
        self.asr = asr_backend if asr_backend is not None else create_asr_backend(config)
        self.tts = tts_backend if tts_backend is not None else create_tts_backend(config)
        self._buffer: list[np.ndarray] = []
        self._recording = False
        self.process = psutil.Process(os.getpid())

    def warm_up(self, duration_sec: float = 0.25, text: str = "xin chao") -> WarmupResult:
        """Run one tiny ASR/TTS pass before benchmarking user-visible latency."""
        samples = max(1, int(duration_sec * self.config.sample_rate))
        pcm = np.zeros(samples, dtype=np.float32)
        audio_duration_sec = len(pcm) / float(self.config.sample_rate)
        ram_before = self._rss_mb()
        start = time.perf_counter()

        transcript, _ = self.asr.transcribe_pcm(pcm)
        tts_bytes, _ = self.tts.synthesize_to_pcm_bytes(text or transcript or "xin chao")

        wall = time.perf_counter() - start
        ram_after = self._rss_mb()
        return WarmupResult(
            audio_duration_sec=audio_duration_sec,
            wall_time_sec=wall,
            ram_before_mb=ram_before,
            ram_after_mb=ram_after,
            ram_delta_mb=ram_after - ram_before,
            transcript=transcript,
            tts_pcm_bytes=len(tts_bytes),
        )

    def start_recording(self) -> None:
        self._buffer.clear()
        self._recording = True

    def append_audio_chunk(self, pcm_chunk: np.ndarray) -> None:
        if not self._recording:
            raise RuntimeError("append_audio_chunk() called before start_recording()")
        self._buffer.append(self._normalize_pcm(pcm_chunk))

    def stop_and_process(self) -> InferenceResult:
        if not self._recording:
            raise RuntimeError("stop_and_process() called before start_recording()")
        self._recording = False
        if not self._buffer:
            raise ValueError("No audio chunks recorded")
        try:
            pcm = np.concatenate(self._buffer)
            return self.process_pcm(pcm)
        finally:
            self._buffer.clear()

    def process_pcm(self, pcm: np.ndarray) -> InferenceResult:
        pcm = self._normalize_pcm(pcm)
        audio_duration_sec = len(pcm) / float(self.config.sample_rate)
        ram_before = self._rss_mb()
        start = time.perf_counter()

        transcript, asr_time = self.asr.transcribe_pcm(pcm)
        tts_bytes, tts_time = self.tts.synthesize_to_pcm_bytes(transcript)

        wall = time.perf_counter() - start
        ram_after = self._rss_mb()
        total = asr_time + tts_time
        rtf = total / max(audio_duration_sec, 1e-9)
        rtf_wall = wall / max(audio_duration_sec, 1e-9)

        return InferenceResult(
            audio_duration_sec=audio_duration_sec,
            asr_time_sec=asr_time,
            tts_time_sec=tts_time,
            total_time_sec=total,
            rtf=rtf,
            wall_time_sec=wall,
            rtf_wall=rtf_wall,
            ram_before_mb=ram_before,
            ram_after_mb=ram_after,
            ram_delta_mb=ram_after - ram_before,
            transcript=transcript,
            tts_pcm_bytes=len(tts_bytes),
            quant=self.config.quant,
            num_threads=self.config.num_threads,
            asr_backend=getattr(self.asr, "backend_name", type(self.asr).__name__),
            tts_backend=getattr(self.tts, "backend_name", type(self.tts).__name__),
            wer_delta_estimate=self.asr.wer_delta,
            passed_rtf=rtf < 0.3,
        )

    def load_counts(self) -> tuple[int | None, int | None]:
        asr_count = getattr(type(self.asr), "load_count", None)
        tts_count = getattr(type(self.tts), "load_count", None)
        return asr_count, tts_count

    def save_tts_bytes_for_other_process(self, tts_bytes: bytes, filename: str = "tts_output.pcm") -> Path:
        """Use /dev/shm if available, otherwise system tmp directory.

        /dev/shm is tmpfs/RAM on Linux, avoiding MicroSD wear.
        """
        base = Path("/dev/shm") if Path("/dev/shm").exists() else Path(tempfile.gettempdir())
        out = base / filename
        out.write_bytes(tts_bytes)
        return out

    def _normalize_pcm(self, pcm: np.ndarray) -> np.ndarray:
        if not isinstance(pcm, np.ndarray):
            raise TypeError("Expected numpy.ndarray raw PCM")
        if pcm.ndim != 1:
            raise ValueError("Expected mono PCM with shape (num_samples,)")
        if len(pcm) == 0:
            raise ValueError("PCM chunk is empty")
        return np.ascontiguousarray(pcm, dtype=np.float32)

    def _rss_mb(self) -> float:
        return self.process.memory_info().rss / 1024.0 / 1024.0
