from artiq.experiment import *


class SPIReceiverExperiment(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.setattr_device("spi_receiver0")

    @rpc(flags={"async"})
    def print_char(self, value):
        print(chr(value & 0xff), end="", flush=True)

    @kernel
    def run(self):
        self.core.reset()
        self.core.break_realtime()

        self.spi_receiver0.enable()
        delay(1 * ms)
        self.core.wait_until_mu(now_mu())

        while True:
            value = self.spi_receiver0.read()
            self.print_char(value)
