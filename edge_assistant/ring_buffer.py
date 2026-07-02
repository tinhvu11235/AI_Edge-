from __future__ import annotations

from threading import Lock


class FixedSizeRingBuffer:
    """Fixed-size byte ring buffer for raw PCM audio."""

    def __init__(self, capacity_bytes: int) -> None:
        if capacity_bytes <= 0:
            raise ValueError("capacity_bytes must be positive")
        self._buffer = bytearray(capacity_bytes)
        self._capacity = capacity_bytes
        self._write_pos = 0
        self._size = 0
        self._lock = Lock()

    @property
    def capacity_bytes(self) -> int:
        return self._capacity

    @property
    def size_bytes(self) -> int:
        with self._lock:
            return self._size

    def append(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            if len(data) >= self._capacity:
                self._buffer[:] = data[-self._capacity :]
                self._write_pos = 0
                self._size = self._capacity
                return

            first = min(len(data), self._capacity - self._write_pos)
            self._buffer[self._write_pos : self._write_pos + first] = data[:first]
            remaining = len(data) - first
            if remaining:
                self._buffer[:remaining] = data[first:]
            self._write_pos = (self._write_pos + len(data)) % self._capacity
            self._size = min(self._capacity, self._size + len(data))

    def clear(self) -> None:
        with self._lock:
            self._write_pos = 0
            self._size = 0

    def snapshot(self) -> bytes:
        """Return the current buffer contents in chronological order."""
        with self._lock:
            if self._size == 0:
                return b""
            start = (self._write_pos - self._size) % self._capacity
            if start < self._write_pos or self._size < self._capacity:
                return bytes(self._buffer[start : start + self._size])
            return bytes(self._buffer[start:] + self._buffer[: self._write_pos])
