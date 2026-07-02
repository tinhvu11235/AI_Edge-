from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

from .base import BackendConfig


class WhisperCppASRBackend:
    """Whisper.cpp CLI backend for Raspberry Pi deployment.

    whisper.cpp's CLI consumes an audio file, so this bridge writes a short WAV
    into tmpfs (/dev/shm when available) and removes it immediately after
    inference. The pipeline API still accepts raw PCM in memory.
    """

    backend_name = "whisper-cpp"
    load_count = 0

    def __init__(self, config: BackendConfig):
        type(self).load_count += 1
        self.config = config
        self.model_path = config.whisper_model_for_quant()
        if not self.model_path.exists():
            raise FileNotFoundError(f"Whisper model not found: {self.model_path}")
        self.binary = self._resolve_binary(config.whisper_cpp_bin)
        self.model_loaded = True

    @property
    def wer_delta(self) -> float | None:
        return None

    def transcribe_pcm(self, pcm: np.ndarray) -> tuple[str, float]:
        if not self.model_loaded:
            raise RuntimeError("ASR model is not loaded")
        if pcm.ndim != 1:
            raise ValueError("ASR expects mono PCM with shape (num_samples,)")

        start = time.perf_counter()
        tmp_dir = Path("/dev/shm") if Path("/dev/shm").exists() else Path(tempfile.gettempdir())
        with tempfile.NamedTemporaryFile(suffix=".wav", dir=tmp_dir, delete=True) as f:
            self._write_wav(Path(f.name), pcm)
            cmd = [
                self.binary,
                "-m",
                str(self.model_path),
                "-f",
                f.name,
                "-t",
                str(max(1, int(self.config.num_threads))),
                "-l",
                self.config.language,
                "-nt",
                "-np",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        elapsed = time.perf_counter() - start
        if proc.returncode != 0:
            stderr = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(f"whisper.cpp failed with exit {proc.returncode}: {stderr}")
        return self._clean_transcript(proc.stdout), elapsed

    def _write_wav(self, path: Path, pcm: np.ndarray) -> None:
        pcm_f32 = pcm.astype(np.float32, copy=False)
        pcm_i16 = np.clip(pcm_f32, -1.0, 1.0)
        pcm_i16 = (pcm_i16 * 32767.0).astype(np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.config.sample_rate)
            wf.writeframes(pcm_i16.tobytes())

    def _resolve_binary(self, configured: str) -> str:
        candidates = []
        if configured:
            candidates.append(configured)
        candidates.extend(
            [
                "whisper-cli",
                "main",
                "whisper",
                str(Path("/opt/whisper.cpp/build/bin/whisper-cli")),
                str(Path("/opt/whisper.cpp/build/bin/main")),
                str(Path("third_party/whisper.cpp/build/bin/whisper-cli")),
                str(Path("third_party/whisper.cpp/build/bin/main")),
            ]
        )
        for candidate in candidates:
            path = Path(candidate)
            if path.exists():
                return str(path)
            found = shutil.which(candidate)
            if found:
                return found
        raise FileNotFoundError(
            "whisper.cpp binary not found. Set --whisper-cpp-bin or run scripts/build_whisper_cpp.sh."
        )

    def _clean_transcript(self, text: str) -> str:
        lines = []
        for line in text.splitlines():
            line = re.sub(r"^\s*\[[^\]]+\]\s*", "", line).strip()
            if line and not line.startswith("whisper_"):
                lines.append(line)
        return " ".join(lines).strip()
