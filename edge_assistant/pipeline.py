from __future__ import annotations

import collections
from dataclasses import dataclass, field
import logging
import queue
import statistics
import threading
import time

from .asr import create_asr
from .audio_source import create_audio_source
from .config import PipelineConfig
from .ring_buffer import FixedSizeRingBuffer
from .tts import create_tts
from .vad import create_vad


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioSegment:
    pcm16le: bytes
    sample_rate: int
    started_at: float
    ended_at: float
    reason: str
    seq_start: int
    seq_end: int


@dataclass
class PipelineStats:
    mode: str
    frames_seen: int = 0
    vad_speech_frames: int = 0
    segments_enqueued: int = 0
    segments_dropped: int = 0
    segments_processed: int = 0
    queue_max_observed: int = 0
    queue_near_full_events: int = 0
    vad_timeout_segments: int = 0
    cooldown_skipped_frames: int = 0
    producer_errors: collections.deque[str] = field(
        default_factory=lambda: collections.deque(maxlen=32)
    )
    consumer_errors: collections.deque[str] = field(
        default_factory=lambda: collections.deque(maxlen=32)
    )
    asr_ms: collections.deque[float] = field(
        default_factory=lambda: collections.deque(maxlen=512)
    )
    tts_ms: collections.deque[float] = field(
        default_factory=lambda: collections.deque(maxlen=512)
    )
    end_to_end_ms: collections.deque[float] = field(
        default_factory=lambda: collections.deque(maxlen=512)
    )

    def to_dict(self) -> dict:
        def avg(values: collections.deque[float]) -> float:
            return statistics.fmean(values) if values else 0.0

        return {
            "mode": self.mode,
            "frames_seen": self.frames_seen,
            "vad_speech_frames": self.vad_speech_frames,
            "segments_enqueued": self.segments_enqueued,
            "segments_dropped": self.segments_dropped,
            "segments_processed": self.segments_processed,
            "queue_max_observed": self.queue_max_observed,
            "queue_near_full_events": self.queue_near_full_events,
            "vad_timeout_segments": self.vad_timeout_segments,
            "cooldown_skipped_frames": self.cooldown_skipped_frames,
            "producer_errors": list(self.producer_errors),
            "consumer_errors": list(self.consumer_errors),
            "asr_avg_ms": avg(self.asr_ms),
            "tts_avg_ms": avg(self.tts_ms),
            "end_to_end_avg_ms": avg(self.end_to_end_ms),
            "end_to_end_max_ms": max(self.end_to_end_ms) if self.end_to_end_ms else 0.0,
            "latency_samples_retained": len(self.end_to_end_ms),
        }


class AlwaysOnPipeline:
    def __init__(self, config: PipelineConfig, mode: str = "active") -> None:
        self.config = config
        self.mode = mode
        ring_bytes = int(config.audio.ring_buffer_seconds * config.audio.sample_rate * 2)
        self.ring_buffer = FixedSizeRingBuffer(ring_bytes)
        self.audio_queue: queue.Queue[AudioSegment | None] = queue.Queue(
            maxsize=config.queue.max_segments
        )
        self.stats = PipelineStats(mode=mode)
        self._stop = threading.Event()
        self._vad = create_vad(config.vad)
        self._source = create_audio_source(config.audio, mode)
        self._asr = create_asr(config.asr)
        self._tts = create_tts(config.tts)

    def run(self, duration_s: float) -> PipelineStats:
        producer = threading.Thread(
            target=self.producer_audio_vad_thread,
            args=(duration_s,),
            name="producer-audio-vad",
        )
        consumer = threading.Thread(target=self.consumer_asr_thread, name="consumer-asr-tts")
        producer.start()
        consumer.start()
        producer.join()
        self._stop.set()
        self._enqueue_sentinel()
        consumer.join(timeout=5.0)
        return self.stats

    def producer_audio_vad_thread(self, duration_s: float) -> None:
        utterance_buffer: FixedSizeRingBuffer | None = None
        in_speech = False
        speech_ms = 0
        silence_ms = 0
        utterance_ms = 0
        segment_start_time = 0.0
        segment_start_seq = 0
        last_frame_time = time.time()
        last_frame_seq = 0
        cooldown_until = 0.0
        try:
            for frame in self._source.frames(duration_s):
                last_frame_time = frame.timestamp
                last_frame_seq = frame.seq
                self.stats.frames_seen += 1
                self.ring_buffer.append(frame.pcm16le)
                if frame.timestamp < cooldown_until:
                    self.stats.cooldown_skipped_frames += 1
                    speech_ms = 0
                    silence_ms = 0
                    continue

                vad = self._vad.infer(frame.pcm16le)
                if vad.speech:
                    self.stats.vad_speech_frames += 1
                    speech_ms += self.config.audio.frame_ms
                    silence_ms = 0
                else:
                    silence_ms += self.config.audio.frame_ms
                    if not in_speech:
                        speech_ms = 0

                started_now = False
                if not in_speech and speech_ms >= self.config.vad.speech_start_ms:
                    in_speech = True
                    started_now = True
                    utterance_ms = 0
                    pre_roll_frames = max(
                        1, self.ring_buffer.size_bytes // self.config.audio.frame_bytes
                    )
                    segment_start_time = frame.timestamp - (
                        pre_roll_frames * self.config.audio.frame_ms / 1000.0
                    )
                    segment_start_seq = max(0, frame.seq - pre_roll_frames + 1)
                    utterance_buffer = FixedSizeRingBuffer(self._max_segment_bytes())
                    utterance_buffer.append(self.ring_buffer.snapshot())

                if in_speech and utterance_buffer is not None:
                    if not started_now:
                        utterance_buffer.append(frame.pcm16le)
                    utterance_ms += self.config.audio.frame_ms

                if in_speech and silence_ms >= self.config.vad.speech_end_ms:
                    self._emit_segment(
                        utterance_buffer,
                        segment_start_time,
                        frame.timestamp,
                        "vad_silence",
                        segment_start_seq,
                        frame.seq,
                    )
                    in_speech = False
                    if utterance_buffer is not None:
                        utterance_buffer.clear()
                    utterance_buffer = None
                    cooldown_until = frame.timestamp + self.config.vad.cooldown_ms / 1000.0
                    speech_ms = 0
                    silence_ms = 0
                    utterance_ms = 0

                if in_speech and utterance_ms >= self.config.vad.max_utterance_ms:
                    self._emit_segment(
                        utterance_buffer,
                        segment_start_time,
                        frame.timestamp,
                        "vad_timeout",
                        segment_start_seq,
                        frame.seq,
                    )
                    in_speech = False
                    if utterance_buffer is not None:
                        utterance_buffer.clear()
                    utterance_buffer = None
                    cooldown_until = frame.timestamp + self.config.vad.cooldown_ms / 1000.0
                    speech_ms = 0
                    silence_ms = 0
                    utterance_ms = 0
        except Exception as exc:  # pragma: no cover - defensive telemetry path
            self.stats.producer_errors.append(repr(exc))

        if utterance_buffer is not None and utterance_buffer.size_bytes:
            self._emit_segment(
                utterance_buffer,
                segment_start_time,
                last_frame_time,
                "producer_stop",
                segment_start_seq,
                last_frame_seq,
            )
            utterance_buffer.clear()

    def consumer_asr_thread(self) -> None:
        while not self._stop.is_set() or not self.audio_queue.empty():
            try:
                segment = self.audio_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if segment is None:
                self.audio_queue.task_done()
                break
            try:
                asr = self._asr.transcribe(segment.pcm16le, segment.sample_rate)
                urgent = "loi" in asr.text.lower() or "timeout" in asr.text.lower()
                tts = self._tts.synthesize(asr.text, urgent=urgent)
                self.stats.asr_ms.append(asr.inference_ms)
                self.stats.tts_ms.append(tts.inference_ms)
                self.stats.end_to_end_ms.append((time.time() - segment.ended_at) * 1000.0)
                self.stats.segments_processed += 1
            except Exception as exc:  # pragma: no cover - defensive telemetry path
                self.stats.consumer_errors.append(repr(exc))
            finally:
                self.audio_queue.task_done()

    def _emit_segment(
        self,
        audio: FixedSizeRingBuffer | None,
        started_at: float,
        ended_at: float,
        reason: str,
        seq_start: int,
        seq_end: int,
    ) -> None:
        if audio is None:
            return
        pcm16le = audio.snapshot()
        if not pcm16le:
            return
        if reason == "vad_timeout":
            self.stats.vad_timeout_segments += 1
        segment = AudioSegment(
            pcm16le=pcm16le,
            sample_rate=self.config.audio.sample_rate,
            started_at=started_at,
            ended_at=ended_at,
            reason=reason,
            seq_start=seq_start,
            seq_end=seq_end,
        )
        self._put_segment(segment)

    def _put_segment(self, segment: AudioSegment) -> None:
        timeout = self.config.queue.put_timeout_ms / 1000.0
        try:
            self.audio_queue.put(segment, timeout=timeout)
            self.stats.segments_enqueued += 1
        except queue.Full:
            policy = self.config.queue.backpressure_policy
            if policy == "drop_oldest":
                try:
                    dropped = self.audio_queue.get_nowait()
                    if dropped is not None:
                        self.stats.segments_dropped += 1
                    self.audio_queue.task_done()
                except queue.Empty:
                    pass
                try:
                    self.audio_queue.put_nowait(segment)
                    self.stats.segments_enqueued += 1
                except queue.Full:
                    self.stats.segments_dropped += 1
            elif policy == "drop_newest":
                self.stats.segments_dropped += 1
            else:
                self.stats.segments_dropped += 1
        self._record_queue_depth()

    def _enqueue_sentinel(self) -> None:
        try:
            self.audio_queue.put_nowait(None)
        except queue.Full:
            try:
                dropped = self.audio_queue.get_nowait()
                if dropped is not None:
                    self.stats.segments_dropped += 1
                self.audio_queue.task_done()
            except queue.Empty:
                pass
            self.audio_queue.put_nowait(None)

    def _max_segment_bytes(self) -> int:
        bytes_per_ms = self.config.audio.sample_rate * 2 / 1000.0
        active_bytes = int(self.config.vad.max_utterance_ms * bytes_per_ms)
        return self.ring_buffer.capacity_bytes + active_bytes

    def _record_queue_depth(self) -> None:
        depth = self.audio_queue.qsize()
        self.stats.queue_max_observed = max(self.stats.queue_max_observed, depth)
        max_segments = self.config.queue.max_segments
        if max_segments <= 0:
            return
        warn_at = max_segments * self.config.queue.warn_at_percent
        if depth >= warn_at:
            self.stats.queue_near_full_events += 1
            LOGGER.warning("audio_queue near full: depth=%s max=%s", depth, max_segments)
