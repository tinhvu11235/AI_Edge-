from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .base import BackendConfig


class PiperTTSBackend:
    """Piper CLI backend.

    Piper writes audio to a file path. The backend uses tmpfs (/dev/shm when
    available), reads the bytes back, and deletes the file with the temp handle.
    """

    backend_name = "piper"
    load_count = 0

    def __init__(self, config: BackendConfig):
        type(self).load_count += 1
        self.config = config
        self.model_path = config.resolved_path(config.piper_model)
        self.config_path = config.resolved_path(config.piper_config)
        if not self.model_path.exists():
            raise FileNotFoundError(f"Piper model not found: {self.model_path}")
        if not self.config_path.exists():
            raise FileNotFoundError(f"Piper config not found: {self.config_path}")
        self.binary = self._resolve_binary(config.piper_bin)
        self.model_loaded = True

    def synthesize_to_pcm_bytes(self, text: str) -> tuple[bytes, float]:
        if not self.model_loaded:
            raise RuntimeError("TTS model is not loaded")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("TTS expects non-empty text")

        tmp_dir = Path("/dev/shm") if Path("/dev/shm").exists() else Path(tempfile.gettempdir())
        start = time.perf_counter()
        with tempfile.NamedTemporaryFile(suffix=".wav", dir=tmp_dir, delete=True) as f:
            cmd = [
                self.binary,
                "--model",
                str(self.model_path),
                "--config",
                str(self.config_path),
                "--output_file",
                f.name,
            ]
            proc = subprocess.run(cmd, input=text, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                stderr = proc.stderr.strip() or proc.stdout.strip()
                raise RuntimeError(f"piper failed with exit {proc.returncode}: {stderr}")
            f.seek(0)
            audio_bytes = f.read()
        return audio_bytes, time.perf_counter() - start

    def _resolve_binary(self, configured: str) -> str:
        candidates = [configured] if configured else []
        candidates.append("piper")
        for candidate in candidates:
            path = Path(candidate)
            if path.exists():
                return str(path)
            found = shutil.which(candidate)
            if found:
                return found
        raise FileNotFoundError("piper binary not found. Install piper or set --piper-bin.")
