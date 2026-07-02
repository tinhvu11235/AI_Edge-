from __future__ import annotations

from dataclasses import dataclass
import re
import time

from .asr import _busy_work
from .config import TtsConfig


_ACRONYM_MAP = {
    "BMS": "bi em et",
    "CAN": "can",
    "VAD": "vi ay di",
    "ASR": "ay es ar",
    "TTS": "ti ti es",
    "CPU": "xi pi yu",
    "RAM": "ram",
}

_PHRASE_MAP = {
    "CAN bus": "can bot",
}

_TECH_TERM_MAP = {
    "Overcurrent": "au vo co ran",
    "communication": "com mu ni cay shon",
    "timeout": "thai ao",
    "bus": "bot",
}

_DIGIT_WORDS = {
    0: "khong",
    1: "mot",
    2: "hai",
    3: "ba",
    4: "bon",
    5: "nam",
    6: "sau",
    7: "bay",
    8: "tam",
    9: "chin",
}


@dataclass(frozen=True)
class Prosody:
    speed: float
    pitch: float
    energy: float
    style_id: str


@dataclass(frozen=True)
class TtsResult:
    normalized_text: str
    audio_bytes: bytes
    inference_ms: float
    prosody: Prosody


class TextNormalizer:
    """Rule-based code-switch normalization for small TTS models."""

    def normalize(self, text: str) -> str:
        text = self._normalize_voltage(text)
        text = self._normalize_percent(text)
        for src, dst in _PHRASE_MAP.items():
            text = re.sub(rf"\b{re.escape(src)}\b", dst, text, flags=re.IGNORECASE)
        for src, dst in _ACRONYM_MAP.items():
            text = re.sub(rf"\b{re.escape(src)}\b", dst, text)
        for src, dst in _TECH_TERM_MAP.items():
            text = re.sub(rf"\b{re.escape(src)}\b", dst, text, flags=re.IGNORECASE)
        return text

    def _normalize_voltage(self, text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            value = int(match.group(1))
            spoken = _number_to_vietnamese(value)
            return f"{spoken} von"

        return re.sub(r"\b(\d+)\s*V\b", replace, text, flags=re.IGNORECASE)

    def _normalize_percent(self, text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            value = int(match.group(1))
            return f"{_number_to_vietnamese(value)} phan tram"

        return re.sub(r"\b(\d+)\s*%", replace, text)


class MockTTS:
    """TTS adapter placeholder for Valtec-TTS or VieNeu-TTS v2-Turbo."""

    def __init__(self, config: TtsConfig) -> None:
        self.config = config
        self.normalizer = TextNormalizer()

    def synthesize(self, text: str, urgent: bool = False) -> TtsResult:
        start = time.perf_counter()
        normalized = self.normalizer.normalize(text)
        prosody = Prosody(
            speed=self.config.urgent_speed if urgent else self.config.default_speed,
            pitch=self.config.urgent_pitch if urgent else self.config.default_pitch,
            energy=self.config.urgent_energy if urgent else self.config.default_energy,
            style_id=self.config.urgent_style if urgent else self.config.default_style,
        )
        _busy_work(self.config.work_ms, normalized.encode("utf-8"))
        payload = (
            f"MOCK_WAV speed={prosody.speed:.2f} pitch={prosody.pitch:.2f} "
            f"energy={prosody.energy:.2f} style={prosody.style_id} {normalized}"
        )
        return TtsResult(
            normalized_text=normalized,
            audio_bytes=payload.encode("utf-8"),
            inference_ms=(time.perf_counter() - start) * 1000.0,
            prosody=prosody,
        )


def create_tts(config: TtsConfig) -> MockTTS:
    if config.backend != "mock":
        raise ValueError(
            f"Unsupported TTS backend '{config.backend}'. "
            "Wire Valtec-TTS or VieNeu-TTS adapter in edge_assistant/tts.py."
        )
    return MockTTS(config)


def _number_to_vietnamese(value: int) -> str:
    if value < 0:
        return f"am {_number_to_vietnamese(abs(value))}"
    if value < 10:
        return _DIGIT_WORDS[value]
    if value < 100:
        tens = value // 10
        ones = value % 10
        if tens == 1:
            base = "muoi"
        else:
            base = f"{_DIGIT_WORDS[tens]} muoi"
        if ones == 0:
            return base
        if ones == 5:
            tail = "lam"
        else:
            tail = _DIGIT_WORDS[ones]
        return f"{base} {tail}"
    return str(value)
