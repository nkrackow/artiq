import io
import unittest

from jsonschema import ValidationError

from artiq.coredevice import jsondesc
from artiq.frontend.artiq_ddb_template import PeripheralManager


class TestSPISlaveDDB(unittest.TestCase):
    def peripheral(self):
        return {
            "type": "dio",
            "ports": [0],
            "bank_direction_low": "input",
            "bank_direction_high": "input",
            "edge_counter": False,
            "spi_slave": {
                "name": "spi_slave",
                "data": 3
            }
        }

    def description(self):
        return {
            "target": "kasli",
            "variant": "spi_slave_test",
            "hw_rev": "v2.0",
            "base": "standalone",
            "peripherals": [self.peripheral()]
        }

    def test_schema_and_device_db(self):
        description = self.description()
        jsondesc.validator.validate(description)

        output = io.StringIO()
        manager = PeripheralManager(output, description)
        channels = manager.process_dio(0x20, description["peripherals"][0])

        self.assertEqual(channels, 9)
        generated = output.getvalue()
        self.assertIn('device_db["spi_slave0"]', generated)
        self.assertIn('"module": "artiq.coredevice.spi_slave"', generated)
        self.assertIn('"channel": 0x000028', generated)

    def test_clock_channel_cannot_be_selected_as_data(self):
        description = self.description()
        description["peripherals"][0]["spi_slave"]["data"] = 0
        with self.assertRaises(ValidationError):
            jsondesc.validator.validate(description)


if __name__ == "__main__":
    unittest.main()
