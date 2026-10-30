import unittest

from migen import *
from migen.sim import passive

from artiq.gateware.rtio.phy.spi_receiver import SPIReceiver


class Testbench(Module):
    def __init__(self):
        self.clock_domains.cd_write = ClockDomain()
        self.clock_domains.cd_read = ClockDomain()

        self.data = Signal()
        self.reset = Signal()
        self.submodules.dut = ClockDomainsRenamer({
            "write": "write",
            "read": "read"
        })(SPIReceiver(self.data, reset=self.reset))

    def enable_with_first_bit(self, value):
        # The serial clock is free-running in this simulation. Present the
        # first bit before arming so the next write-domain edge is edge 1.
        yield self.data.eq((value >> 31) & 1)
        yield self.dut.rtlink.o.data.eq(1)
        yield self.dut.rtlink.o.stb.eq(1)
        yield
        yield self.dut.rtlink.o.stb.eq(0)

    def disable(self):
        yield self.dut.rtlink.o.data.eq(0)
        yield self.dut.rtlink.o.stb.eq(1)
        yield
        yield self.dut.rtlink.o.stb.eq(0)
        yield

    def pulse_reset(self):
        yield self.reset.eq(1)
        yield
        yield self.reset.eq(0)
        yield

    def send_bits(self, value, first_bit=31, count=32):
        for bit in range(first_bit, first_bit - count, -1):
            yield self.data.eq((value >> bit) & 1)
            yield


class TestSPIReceiver(unittest.TestCase):
    def run_test(self, stimulus, expected):
        tb = Testbench()
        received = []

        @passive
        def monitor():
            while True:
                if (yield tb.dut.rtlink.i.stb):
                    received.append((yield tb.dut.rtlink.i.data))
                yield

        run_simulation(
            tb,
            {
                "write": stimulus(tb),
                "read": monitor()
            },
            clocks={"write": 40, "read": 8}
        )
        self.assertEqual(received, expected)

    def test_word_and_bit_order(self):
        def stimulus(tb):
            yield from tb.enable_with_first_bit(0xa5c39e71)
            yield from tb.send_bits(0xa5c39e71, first_bit=30, count=31)
            for _ in range(8):
                yield

        self.run_test(stimulus, [0xa5c39e71])

    def test_two_back_to_back_words(self):
        def stimulus(tb):
            yield from tb.enable_with_first_bit(0x00000001)
            yield from tb.send_bits(0x00000001, first_bit=30, count=31)
            yield from tb.send_bits(0x80000001)
            for _ in range(8):
                yield

        self.run_test(stimulus, [0x00000001, 0x80000001])

    def test_disabled_receiver_ignores_word(self):
        def stimulus(tb):
            yield from tb.send_bits(0xdeadbeef)
            yield from tb.enable_with_first_bit(0x12345678)
            yield from tb.send_bits(0x12345678, first_bit=30, count=31)
            for _ in range(8):
                yield

        self.run_test(stimulus, [0x12345678])

    def test_disable_discards_partial_word(self):
        def stimulus(tb):
            yield from tb.enable_with_first_bit(0xaaaaaaaa)
            yield from tb.send_bits(0xaaaaaaaa, first_bit=30, count=12)
            yield from tb.disable()
            yield from tb.enable_with_first_bit(0x80000001)
            yield from tb.send_bits(0x80000001, first_bit=30, count=31)
            for _ in range(8):
                yield

        self.run_test(stimulus, [0x80000001])

    def test_reset_discards_partial_word(self):
        def stimulus(tb):
            yield from tb.enable_with_first_bit(0xffffffff)
            yield from tb.send_bits(0xffffffff, first_bit=30, count=8)
            yield from tb.pulse_reset()
            yield from tb.enable_with_first_bit(0x12345678)
            yield from tb.send_bits(0x12345678, first_bit=30, count=31)
            for _ in range(8):
                yield

        self.run_test(stimulus, [0x12345678])


if __name__ == "__main__":
    unittest.main()
