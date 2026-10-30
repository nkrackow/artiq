core_addr = "10.42.1.100"

device_db = {
    "core": {
        "type": "local",
        "module": "artiq.coredevice.core",
        "class": "Core",
        "arguments": {
            "host": core_addr,
            "ref_period": 1e-9,
            "target": "rv32g",
        },
    },
    "spi_receiver0": {
        "type": "local",
        "module": "artiq.coredevice.spi_receiver",
        "class": "SPIReceiver",
        "arguments": {
            "channel": 8,
        },
    },
}
