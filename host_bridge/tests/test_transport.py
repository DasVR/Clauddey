import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protocol import CDC_PACKET_SIZE, LineAssembler, pack_status
from transport import StdoutTransport
from transport_usb import chunk_cdc


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


class StdoutTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_records_sent_lines(self):
        transport = StdoutTransport()
        await transport.connect()
        await transport.write(pack_status("cursor", "idle", "").encode("ascii"))
        self.assertEqual(len(transport.sent), 1)
        self.assertIn('"agent":"cursor"', transport.sent[0])

    async def test_inject_rx_is_readable(self):
        transport = StdoutTransport()
        await transport.connect()
        transport.inject_rx('{"v":1,"cmd":"ok","agent":"cursor","mode":"interactive"}')
        line = await transport.readline()
        self.assertIn(b'"cmd":"ok"', line)

    async def test_close_unblocks_readline(self):
        transport = StdoutTransport()
        await transport.connect()
        transport.close()
        self.assertEqual(await transport.readline(), b"")
        self.assertTrue(transport.is_closing)


class ReconnectTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_with_retry_backs_off_then_succeeds(self):
        from bridge import connect_with_retry

        attempts = {"n": 0}

        class FlakyTransport(StdoutTransport):
            async def connect(self) -> bool:
                attempts["n"] += 1
                return attempts["n"] >= 3

        transport = FlakyTransport()
        await connect_with_retry(transport)
        self.assertEqual(attempts["n"], 3)
