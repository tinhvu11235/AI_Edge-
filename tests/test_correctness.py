from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from edge_voice_test.audio import generate_synthetic_pcm
from edge_voice_test.backends import BackendConfig, SimulatedASRBackend, SimulatedTTSBackend
from edge_voice_test.pipeline import VoicePipeline


def test_model_load_once_and_rtf_pass():
    SimulatedASRBackend.load_count = 0
    SimulatedTTSBackend.load_count = 0
    pipeline = VoicePipeline(BackendConfig(quant="Q5", num_threads=2, time_scale=0.0))
    pcm = generate_synthetic_pcm(5.0)
    for _ in range(5):
        result = pipeline.process_pcm(pcm)
        assert result.rtf < 0.3
    assert SimulatedASRBackend.load_count == 1
    assert SimulatedTTSBackend.load_count == 1


def test_push_to_talk_flow_raw_pcm():
    pipeline = VoicePipeline(BackendConfig(quant="Q5", num_threads=2, time_scale=0.0))
    pcm = generate_synthetic_pcm(3.0)
    pipeline.start_recording()
    pipeline.append_audio_chunk(pcm[:16000])
    pipeline.append_audio_chunk(pcm[16000:])
    result = pipeline.stop_and_process()
    assert result.audio_duration_sec == 3.0
    assert result.transcript.startswith("xin chao robot")
    assert result.tts_pcm_bytes > 0


def test_warm_up_runs_without_changing_load_count():
    SimulatedASRBackend.load_count = 0
    SimulatedTTSBackend.load_count = 0
    pipeline = VoicePipeline(BackendConfig(quant="Q5", num_threads=2, time_scale=0.0))
    warmup = pipeline.warm_up(duration_sec=0.1)
    assert warmup.audio_duration_sec == 0.1
    assert warmup.tts_pcm_bytes > 0
    assert SimulatedASRBackend.load_count == 1
    assert SimulatedTTSBackend.load_count == 1


def test_rejects_non_mono_pcm():
    pipeline = VoicePipeline(BackendConfig(quant="Q5", num_threads=2, time_scale=0.0))
    with pytest.raises(ValueError):
        pipeline.process_pcm(np.zeros((2, 16000), dtype=np.float32))


def test_no_temp_wav_created(tmp_path: Path):
    before = set(Path(".").glob("*.wav")) | set(Path(".").glob("temp*.wav"))
    pipeline = VoicePipeline(BackendConfig(quant="Q5", num_threads=2, time_scale=0.0))
    result = pipeline.process_pcm(generate_synthetic_pcm(1.0))
    after = set(Path(".").glob("*.wav")) | set(Path(".").glob("temp*.wav"))
    assert before == after
    assert result.tts_pcm_bytes > 0
