"""LORA Tunnel for M5Stack CardputerZero: LoRa mesh wardriving and decoding."""

__version__ = "1.1.0"
APP_NAME = "LORA Tunnel"


class RadioError(RuntimeError):
    """A receive backend could not initialize, tune or read a packet."""
