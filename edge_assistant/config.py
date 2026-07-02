from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class AudioConfig:
    source: str = "simulated"
    device: str = "default"
    sample_rate: int = 16000
    frame_ms: int = 20
    ring_buffer_seconds: float = 3.0
    simulated_profile: str = "mixed"

    @property
    def frame_bytes(self) -> int:
        return int(self.sample_rate * self.frame_ms / 1000) * 2


@dataclass(frozen=True)
class VadConfig:
    backend: str = "energy"
    threshold: int = 950
    speech_start_ms: int = 80
    speech_end_ms: int = 450
    max_utterance_ms: int = 6000
    cooldown_ms: int = 250


@dataclass(frozen=True)
class QueueConfig:
    max_segments: int = 8
    put_timeout_ms: int = 5
    backpressure_policy: str = "drop_oldest"
    warn_at_percent: float = 0.75


@dataclass(frozen=True)
class AsrConfig:
    backend: str = "mock"
    work_ms: int = 18


@dataclass(frozen=True)
class TtsConfig:
    backend: str = "mock"
    work_ms: int = 12
    default_speed: float = 1.0
    urgent_speed: float = 1.18
    default_pitch: float = 1.0
    urgent_pitch: float = 1.08
    default_energy: float = 1.0
    urgent_energy: float = 1.12
    default_style: str = "neutral"
    urgent_style: str = "alert"


@dataclass(frozen=True)
class BenchmarkConfig:
    background_cpu_limit_percent: float = 40.0
    active_cpu_limit_percent: float = 70.0
    sample_interval_ms: int = 250


@dataclass(frozen=True)
class PipelineConfig:
    audio: AudioConfig = AudioConfig()
    vad: VadConfig = VadConfig()
    queue: QueueConfig = QueueConfig()
    asr: AsrConfig = AsrConfig()
    tts: TtsConfig = TtsConfig()
    benchmark: BenchmarkConfig = BenchmarkConfig()


def _section(data: dict, name: str) -> dict:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"Config section [{name}] must be a table")
    return value


def load_config(path: str | Path) -> PipelineConfig:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return PipelineConfig(
        audio=AudioConfig(**_section(raw, "audio")),
        vad=VadConfig(**_section(raw, "vad")),
        queue=QueueConfig(**_section(raw, "queue")),
        asr=AsrConfig(**_section(raw, "asr")),
        tts=TtsConfig(**_section(raw, "tts")),
        benchmark=BenchmarkConfig(**_section(raw, "benchmark")),
    )
