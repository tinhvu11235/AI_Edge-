from __future__ import annotations

from array import array
from dataclasses import dataclass
import math
import random
import time
import wave

from .config import AudioConfig


@dataclass(frozen=True)
class AudioFrame:
    pcm16le: bytes
    timestamp: float
    seq: int


class SimulatedAudioSource:
    """Generate car-noise and speech-like PCM frames for repeatable benchmarks."""

    def __init__(self, config: AudioConfig, mode: str) -> None:
        self.config = config
        self.mode = mode
        self._seq = 0
        self._phase = 0.0
        self._rng = random.Random(42)

    def frames(self, duration_s: float):
        frame_samples = int(self.config.sample_rate * self.config.frame_ms / 1000)
        frame_period = self.config.frame_ms / 1000.0
        start = time.perf_counter()
        next_deadline = start
        while time.perf_counter() - start < duration_s:
            elapsed = time.perf_counter() - start
            speech = self._speech_active(elapsed)
            yield AudioFrame(self._make_frame(frame_samples, speech), time.time(), self._seq)
            self._seq += 1
            next_deadline += frame_period
            sleep_s = next_deadline - time.perf_counter()
            if sleep_s > 0:
                time.sleep(sleep_s)

    def _speech_active(self, elapsed: float) -> bool:
        if self.mode == "background":
            return False
        cycle = elapsed % 5.0
        return 0.9 <= cycle <= 2.6

    def _make_frame(self, samples: int, speech: bool) -> bytes:
        pcm = array("h")
        noise_amp = 260 if not speech else 520
        tone_amp = 0 if not speech else 2600
        freq = 180.0 if speech else 45.0
        for _ in range(samples):
            self._phase += 2.0 * math.pi * freq / self.config.sample_rate
            noise = self._rng.randint(-noise_amp, noise_amp)
            value = int(math.sin(self._phase) * tone_amp + noise)
            value = max(-32768, min(32767, value))
            pcm.append(value)
        return pcm.tobytes()


class WaveAudioSource:
    def __init__(self, config: AudioConfig, path: str) -> None:
        self.config = config
        self.path = path

    def frames(self, duration_s: float):
        frame_bytes = self.config.frame_bytes
        start = time.perf_counter()
        seq = 0
        with wave.open(self.path, "rb") as wav:
            if wav.getsampwidth() != 2 or wav.getframerate() != self.config.sample_rate:
                raise ValueError("WAV must be mono/stereo PCM16 at configured sample_rate")
            channels = wav.getnchannels()
            while time.perf_counter() - start < duration_s:
                raw = wav.readframes(frame_bytes // 2 // channels)
                if not raw:
                    break
                if channels == 2:
                    raw = _stereo_to_mono(raw)
                yield AudioFrame(raw, time.time(), seq)
                seq += 1


class MicrophoneAudioSource:
    def __init__(self, config: AudioConfig) -> None:
        self.config = config

    def frames(self, duration_s: float):
        try:
            import sounddevice as sd  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Microphone source requires sounddevice. "
                "Run scripts/rpi_install_native.sh or set audio.source='simulated'."
            ) from exc

        frame_samples = int(self.config.sample_rate * self.config.frame_ms / 1000)
        start = time.perf_counter()
        seq = 0
        with sd.RawInputStream(
            samplerate=self.config.sample_rate,
            blocksize=frame_samples,
            dtype="int16",
            channels=1,
            device=None if self.config.device == "default" else self.config.device,
        ) as stream:
            while time.perf_counter() - start < duration_s:
                data, overflowed = stream.read(frame_samples)
                if overflowed:
                    continue
                yield AudioFrame(bytes(data), time.time(), seq)
                seq += 1


def create_audio_source(config: AudioConfig, mode: str):
    if config.source == "simulated":
        return SimulatedAudioSource(config, mode)
    if config.source == "microphone":
        return MicrophoneAudioSource(config)
    if config.source.startswith("wav:"):
        return WaveAudioSource(config, config.source[4:])
    raise ValueError(f"Unsupported audio.source '{config.source}'")


def _stereo_to_mono(raw: bytes) -> bytes:
    samples = array("h")
    samples.frombytes(raw)
    mono = array("h")
    for idx in range(0, len(samples), 2):
        mono.append(int((samples[idx] + samples[idx + 1]) / 2))
    return mono.tobytes()
