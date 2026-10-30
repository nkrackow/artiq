from migen import *
from migen.genlib.fifo import AsyncFIFO

from artiq.gateware.rtio import rtlink


class ClockedSPIReceiver(Module):
    """Kasli/EEM wrapper providing the external and RTIO-side clock domains."""

    def __init__(self, clock, data):
        self.clock_domains.cd_spi_receiver = ClockDomain(reset_less=True)
        self.clock_domains.cd_spi_receiver_rio = ClockDomain(reset_less=True)
        self.specials += Instance(
            "BUFG", i_I=clock, o_O=self.cd_spi_receiver.clk)
        self.comb += self.cd_spi_receiver_rio.clk.eq(ClockSignal("rio"))

        core = ClockDomainsRenamer({
            "write": "spi_receiver",
            "read": "spi_receiver_rio"
        })(SPIReceiver(data, reset=ResetSignal("rio")))
        self.submodules.core = core
        self.rtlink = core.rtlink


class SPIReceiver(Module):
    """Minimal receive-only SPI receiver.

    The external interface consists of a clock for the ``write`` domain and
    the scalar ``data`` input. Data is sampled MSB-first on rising clock edges.
    Every 32 samples form one RTIO input event. Completed words cross into the
    ``read`` domain through a two-entry asynchronous FIFO.

    RTIO output data bit 0 enables reception. Disabling ignores clock edges;
    every transition from disabled to enabled starts a new word. The enable
    and arm generation are intentionally sampled directly by the external
    clock domain. They must be stable before the first serial clock edge.

    The two clock domains are supplied by the enclosing design and are named
    ``write`` and ``read`` so they can be renamed at instantiation.

    :param data: Serial data input.
    :param reset: Synchronous reset indication in the read clock domain.
    """

    def __init__(self, data, reset=0):
        self.rtlink = rtlink.Interface(
            rtlink.OInterface(1, enable_replace=False),
            rtlink.IInterface(32))

        # # #

        enabled = Signal()
        # This state deliberately survives an RTIO-domain reset. Otherwise a
        # reset while the external clock is stopped could make a later arm
        # command indistinguishable from the previous one in the write domain.
        arm_generation = Signal(8, reset_less=True)
        self.sync.read += [
            If(reset,
                enabled.eq(0)
            ).Elif(self.rtlink.o.stb,
                If(self.rtlink.o.data[0],
                    If(~enabled,
                        arm_generation.eq(arm_generation + 1)
                    ),
                    enabled.eq(1)
                ).Else(
                    enabled.eq(0)
                )
            )
        ]

        fifo = AsyncFIFO(width=32, depth=2)
        self.submodules.fifo = fifo

        shift_register = Signal(32)
        bit_count = Signal(5)
        seen_generation = Signal.like(arm_generation)
        next_word = Signal(32)
        self.comb += next_word.eq(Cat(data, shift_register[:31]))

        write_word = Signal()
        self.comb += [
            write_word.eq(
                enabled &
                (seen_generation == arm_generation) &
                (bit_count == 31)
            ),
            fifo.din.eq(next_word),
            fifo.we.eq(write_word & fifo.writable)
        ]

        self.sync.write += [
            If(enabled,
                If(seen_generation != arm_generation,
                    # Capture the first bit on the first edge after arming.
                    seen_generation.eq(arm_generation),
                    shift_register.eq(next_word),
                    bit_count.eq(1)
                ).Else(
                    shift_register.eq(next_word),
                    If(bit_count == 31,
                        bit_count.eq(0)
                    ).Else(
                        bit_count.eq(bit_count + 1)
                    )
                )
            )
        ]

        # The RTIO input collector has no backpressure. Drain one FIFO entry
        # per read-domain cycle; while disabled or reset this also discards any
        # word that raced with a control transition.
        self.comb += [
            self.rtlink.i.stb.eq(fifo.readable & enabled & ~reset),
            self.rtlink.i.data.eq(fifo.dout),
            fifo.re.eq(fifo.readable)
        ]
