from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import numpy as np

Quant = Literal["FP16", "Q8", "Q5", "Q4"]
ASRBackendName = Literal["simulated", "whisper-cpp"]
TTSBackendName = Literal["simulated", "piper"]


@dataclass(frozen=True)
class BackendConfig:
    quant: Quant = "Q5"
    num_threads: int = 2
    time_scale: float = 0.02
    sample_rate: int = 16000
    leak_bytes_per_call: int = 0
    asr_backend: ASRBackendName = "simulated"
    tts_backend: TTSBackendName = "simulated"
    models_dir: str = "models"
    whisper_model: str = "models/whisper/ggml-tiny.bin"
    whisper_cpp_bin: str = ""
    piper_model: str = "models/piper/vi_VN-vais1000-medium/vi_VN-vais1000-medium.onnx"
    piper_config: str = "models/piper/vi_VN-vais1000-medium/vi_VN-vais1000-medium.onnx.json"
    piper_bin: str = ""
    language: str = "vi"

    def resolved_path(self, value: str) -> Path:
        return Path(value) if Path(value).is_absolute() else Path(value)

    def whisper_model_for_quant(self) -> Path:
        base = self.resolved_path(self.whisper_model)
        if self.quant == "FP16":
            return base
        suffix_by_quant = {
            "Q8": "q8_0",
            "Q5": "q5_0",
            "Q4": "q4_0",
        }
        suffix = suffix_by_quant.get(self.quant)
        if not suffix:
            return base
        candidate = base.with_name(f"{base.stem}-{suffix}{base.suffix}")
        return candidate if candidate.exists() else base


class ASRBackend(Protocol):
    backend_name: str

    @property
    def wer_delta(self) -> float | None:
        ...

    def transcribe_pcm(self, pcm: np.ndarray) -> tuple[str, float]:
        ...


class TTSBackend(Protocol):
    backend_name: str

    def synthesize_to_pcm_bytes(self, text: str) -> tuple[bytes, float]:
        ...


def create_asr_backend(config: BackendConfig) -> ASRBackend:
    if config.asr_backend == "simulated":
        from .simulated import SimulatedASRBackend

        return SimulatedASRBackend(config)
    if config.asr_backend == "whisper-cpp":
        from .whisper_cpp import WhisperCppASRBackend

        return WhisperCppASRBackend(config)
    raise ValueError(f"Unsupported ASR backend: {config.asr_backend}")


def create_tts_backend(config: BackendConfig) -> TTSBackend:
    if config.tts_backend == "simulated":
        from .simulated import SimulatedTTSBackend

        return SimulatedTTSBackend(config)
    if config.tts_backend == "piper":
        from .piper import PiperTTSBackend

        return PiperTTSBackend(config)
    raise ValueError(f"Unsupported TTS backend: {config.tts_backend}")
