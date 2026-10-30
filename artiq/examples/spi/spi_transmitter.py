from artiq.experiment import *


class SPITransmitter(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.setattr_device("ttl4")
        self.setattr_device("ttl5")
        self.setattr_argument(
            "bit_order",
            EnumerationValue(["msb_first", "lsb_first"], "lsb_first"))
        self.lsb_first = self.bit_order == "lsb_first"

    @kernel
    def send_bit(self, value):
        if value:
            self.ttl5.on()
        else:
            self.ttl5.off()
        delay(100 * ns)
        self.ttl4.on()
        delay(100 * ns)
        self.ttl4.off()

    @kernel
    def send_word(self, word):
        if self.lsb_first:
            for bit in range(32):
                self.send_bit(word & (1 << bit))
        else:
            for bit in range(31, -1, -1):
                self.send_bit(word & (1 << bit))

        self.ttl5.off()

    @kernel
    def run(self):
        self.core.reset()
        self.core.break_realtime()
        
        self.ttl4.output()
        self.ttl5.output()
        delay(1 * us)
        self.ttl4.off()
        self.ttl5.off()
        delay(1 * us)

        while True:
            for character in range(32, 127):
                self.send_word(character)
                delay(100 * ms)
