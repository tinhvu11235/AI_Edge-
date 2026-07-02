from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time

from .config import AsrConfig


@dataclass(frozen=True)
class AsrResult:
    text: str
    inference_ms: float


class MockASR:
    """ASR adapter placeholder for SenseVoiceSmall."""

    def __init__(self, config: AsrConfig) -> None:
        self.work_ms = config.work_ms

    def transcribe(self, pcm16le: bytes, sample_rate: int) -> AsrResult:
        start = time.perf_counter()
        _busy_work(self.work_ms, pcm16le[:256])
        digest = hashlib.sha1(pcm16le[:2048]).hexdigest()
        if int(digest[0], 16) % 2:
            text = "He thong dang kiem tra BMS, phat hien loi Overcurrent tren duong nguon 24V"
        else:
            text = "Ma loi CAN bus communication timeout"
        return AsrResult(text=text, inference_ms=(time.perf_counter() - start) * 1000.0)


def create_asr(config: AsrConfig) -> MockASR:
    if config.backend != "mock":
        raise ValueError(
            f"Unsupported ASR backend '{config.backend}'. "
            "Wire SenseVoiceSmall adapter in edge_assistant/asr.py."
        )
    return MockASR(config)


def _busy_work(duration_ms: int, seed: bytes) -> int:
    if duration_ms <= 0:
        return 0
    end = time.perf_counter() + duration_ms / 1000.0
    state = int.from_bytes(hashlib.sha1(seed or b"x").digest()[:8], "little")
    while time.perf_counter() < end:
        state = (state * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF
    return state
