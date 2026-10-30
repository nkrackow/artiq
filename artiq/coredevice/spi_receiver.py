"""Driver for the receive-only DIO SPI receiver PHY."""

from numpy import int64

from artiq.language.core import kernel
from artiq.language.types import TBool, TInt32, TInt64, TTuple
from artiq.coredevice.rtio import (
    rtio_input_data, rtio_input_timestamped_data, rtio_output)


class SPIReceiver:
    """Receive 32-bit SPI words as RTIO input events.

    The gateware samples data MSB-first on rising edges of a mode-0 SPI clock.
    There is no chip-select signal; each group of 32 edges is one word.

    Reception is disabled after reset. After enabling, the external sender
    must allow the enable signal to settle before presenting the first clock
    edge, and must start at the first bit of a new word.

    :param channel: RTIO channel assigned to the SPI receiver PHY.
    """

    kernel_invariants = {"core", "channel", "target"}

    def __init__(self, dmgr, channel, core_device="core"):
        self.core = dmgr.get(core_device)
        self.channel = channel
        self.target = channel << 8

    @staticmethod
    def get_rtio_channels(channel, **kwargs):
        return [(channel, None)]

    @kernel
    def set_enabled(self, enabled: TBool):
        """Enable or disable reception at the current timeline position.

        Disabling discards partial words. A subsequent enable establishes a
        new 32-bit word boundary.
        """
        rtio_output(self.target, 1 if enabled else 0)

    @kernel
    def enable(self):
        """Enable reception. See :meth:`set_enabled`."""
        self.set_enabled(True)

    @kernel
    def disable(self):
        """Disable reception and discard any partial word."""
        self.set_enabled(False)

    @kernel
    def read(self) -> TInt32:
        """Block until a word is available and return its raw signed value."""
        return rtio_input_data(self.channel)

    @kernel
    def read_timestamped(
            self, timeout_mu=int64(-1)) -> TTuple([TInt64, TInt32]):
        """Return the RTIO timestamp and raw signed word.

        If ``timeout_mu`` elapses, the returned timestamp is ``-1`` and the
        data value is zero. The timestamp records arrival after clock-domain
        crossing, not the exact time of the 32nd serial clock edge.
        """
        return rtio_input_timestamped_data(timeout_mu, self.channel)
