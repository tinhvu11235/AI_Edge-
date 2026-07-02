import unittest

from edge_assistant.ring_buffer import FixedSizeRingBuffer


class RingBufferTest(unittest.TestCase):
    def test_keeps_only_latest_bytes(self):
        rb = FixedSizeRingBuffer(5)
        rb.append(b"abc")
        rb.append(b"def")
        self.assertEqual(rb.snapshot(), b"bcdef")

    def test_large_write_replaces_buffer(self):
        rb = FixedSizeRingBuffer(4)
        rb.append(b"012345")
        self.assertEqual(rb.snapshot(), b"2345")

    def test_clear_resets_snapshot(self):
        rb = FixedSizeRingBuffer(4)
        rb.append(b"abcd")
        rb.clear()
        self.assertEqual(rb.snapshot(), b"")
        self.assertEqual(rb.size_bytes, 0)


if __name__ == "__main__":
    unittest.main()
