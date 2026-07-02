from __future__ import annotations

from array import array
from dataclasses import dataclass
import math
import sys

from .config import VadConfig


@dataclass(frozen=True)
class VadResult:
    speech: bool
    rms: float


class EnergyVAD:
    """Small dependency-free VAD fallback.

    This is not meant to replace Silero/WebRTC in production. It exists so the
    thread, queue, ring buffer and benchmark path can run deterministically in
    Docker and CI before the real model is installed on Raspberry Pi.
    """

    def __init__(self, config: VadConfig) -> None:
        self.threshold = config.threshold

    def infer(self, pcm16le: bytes) -> VadResult:
        if not pcm16le:
            return VadResult(False, 0.0)
        samples = array("h")
        samples.frombytes(pcm16le)
        if sys.byteorder != "little":
            samples.byteswap()
        if not samples:
            return VadResult(False, 0.0)
        acc = 0
        for sample in samples:
            acc += int(sample) * int(sample)
        rms = math.sqrt(acc / len(samples))
        return VadResult(rms >= self.threshold, rms)


def create_vad(config: VadConfig) -> EnergyVAD:
    if config.backend != "energy":
        raise ValueError(
            f"Unsupported VAD backend '{config.backend}'. "
            "Install and wire Silero/WebRTC in edge_assistant/vad.py."
        )
    return EnergyVAD(config)
