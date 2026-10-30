from artiq.experiment import *


class SPITransmitter(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.setattr_device("ttl4")
        self.setattr_device("ttl5")

    @kernel
    def send_word(self, word):
        # The receiver expects one 32-bit, mode-0, MSB-first transaction.
        for bit in range(31, -1, -1):
            if word & (1 << bit):
                self.ttl5.on()
            else:
                self.ttl5.off()
            delay(500 * ns)
            self.ttl4.on()
            delay(500 * ns)
            self.ttl4.off()

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
