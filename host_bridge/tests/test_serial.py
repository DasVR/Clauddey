import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protocol import CDC_PACKET_SIZE, LineAssembler, pack_status
from serial_link import SerialTransport, chunk_cdc


class LineAssemblerTests(unittest.TestCase):
    def test_status_line_exceeds_one_cdc_packet(self):
        line = pack_status("cursor", "generating", "Generating code...")
        self.assertGreater(len(line), CDC_PACKET_SIZE)

    def test_spans_64_byte_packets(self):
        line = pack_status("cursor", "generating", "Generating code...")
        raw = line.encode("ascii")
        asm = LineAssembler()
        self.assertEqual(asm.feed(raw[:CDC_PACKET_SIZE]), [])
        self.assertEqual(asm.feed(raw[CDC_PACKET_SIZE:]), [line.strip()])

    def test_overflow_resyncs_on_newline(self):
        asm = LineAssembler(max_len=16)
        self.assertEqual(asm.feed(b"abcdefghijklmnopqr\n"), [])
        self.assertEqual(asm.feed(b"ok\n"), ["ok"])

    def test_reset_prevents_splicing_a_partial_frame(self):
        prefix = b'{"v":1,"agent":"cursor"'
        rest = b',"status":"idle","msg":"x"}\n'

        glued = LineAssembler()
        self.assertEqual(glued.feed(prefix), [])
        spliced = glued.feed(rest)
        self.assertEqual(len(spliced), 1)
        self.assertIn("cursor", spliced[0])

        isolated = LineAssembler()
        self.assertEqual(isolated.feed(prefix), [])
        isolated.reset()
        leftover = isolated.feed(rest)
        self.assertEqual(len(leftover), 1)
        self.assertNotIn("cursor", leftover[0])


class ChunkTests(unittest.TestCase):
    def test_chunk_cdc_splits_at_64(self):
        parts = list(chunk_cdc(b"x" * 70))
        self.assertEqual(len(parts), 2)
        self.assertEqual(len(parts[0]), 64)
        self.assertEqual(len(parts[1]), 6)


class FakePort:
    def __init__(self, fail_reads: int = 0) -> None:
        self.written = bytearray()
        self.closed = False
        self._fail_reads = fail_reads
        self._reads = 0
        self._lock = threading.Lock()

    def read(self, n: int) -> bytes:
        with self._lock:
            self._reads += 1
            if self._fail_reads and self._reads > self._fail_reads:
                raise OSError("device disconnected")
        time.sleep(0.01)
        return b""

    def write(self, data: bytes) -> int:
        if self.closed:
            raise OSError("closed")
        self.written.extend(data)
        return len(data)

    def flush(self) -> None:
        return

    def close(self) -> None:
        self.closed = True


class ReconnectTests(unittest.TestCase):
    def test_reconnect_replays_last_status(self):
        ports: list[FakePort] = []

        def opener(port: str, baud: int) -> FakePort:
            del port, baud
            if not ports:
                fake = FakePort(fail_reads=1)
            else:
                fake = FakePort(fail_reads=0)
            ports.append(fake)
            return fake

        transport = SerialTransport(
            port="auto",
            reconnect_s=0.05,
            opener=opener,
            port_finder=lambda: "/dev/fake",
        )
        payload = pack_status("cursor", "waiting", "Accept the diff?")
        transport.send_line(payload)

        deadline = time.time() + 3.0
        while time.time() < deadline:
            if len(ports) >= 2 and payload.encode("ascii") in bytes(ports[-1].written):
                break
            time.sleep(0.05)
        transport.close()

        self.assertGreaterEqual(len(ports), 2)
        self.assertIn(payload.encode("ascii"), bytes(ports[-1].written))
