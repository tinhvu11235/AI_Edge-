from __future__ import annotations

from dataclasses import dataclass, field
import os
import statistics
import threading
import time


@dataclass
class CpuSummary:
    samples: list[float] = field(default_factory=list)

    @property
    def avg_percent(self) -> float:
        return statistics.fmean(self.samples) if self.samples else 0.0

    @property
    def max_percent(self) -> float:
        return max(self.samples) if self.samples else 0.0


class ProcessCpuMonitor:
    """Measure process CPU as percent of total machine capacity."""

    def __init__(self, interval_s: float = 0.25) -> None:
        self.interval_s = interval_s
        self.summary = CpuSummary()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="cpu-monitor", daemon=True)

    def __enter__(self) -> "ProcessCpuMonitor":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        cpu_count = max(1, os.cpu_count() or 1)
        last_wall = time.perf_counter()
        last_cpu = time.process_time()
        while not self._stop.wait(self.interval_s):
            now_wall = time.perf_counter()
            now_cpu = time.process_time()
            wall_delta = now_wall - last_wall
            cpu_delta = now_cpu - last_cpu
            if wall_delta > 0:
                self.summary.samples.append((cpu_delta / wall_delta) * 100.0 / cpu_count)
            last_wall = now_wall
            last_cpu = now_cpu
