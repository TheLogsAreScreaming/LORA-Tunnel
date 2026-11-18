"""Public mesh configuration shape; radio/board arithmetic is tested natively."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/config-v1.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)
BASE = {"schema": 1, "lora": {"enabled": True, "region": "US"}}
KEY_128 = "000102030405060708090a0b0c0d0e0f"
KEY_256 = KEY_128 + "101112131415161718191a1b1c1d1e1f"


class MeshConfigSchemaTests(unittest.TestCase):
    def config(self, **radio):
        document = deepcopy(BASE)
        document["lora"].update(radio)
        return document

    def test_named_presets_and_custom_zero_slot(self):
        for preset in (
            "LONG_FAST", "LONG_TURBO", "LONG_MODERATE", "LONG_SLOW",
            "MEDIUM_FAST", "MEDIUM_SLOW", "SHORT_FAST", "SHORT_SLOW", "SHORT_TURBO", "CUSTOM",
        ):
            with self.subTest(preset=preset):
                VALIDATOR.validate(self.config(meshtastic_preset=preset, meshtastic_slot=0))
        VALIDATOR.validate(self.config(meshtastic_preset="LONG_TURBO", meshtastic_slot=14))
        for fields in (
            {"meshtastic_preset": "LongTurbo"}, {"meshtastic_preset": None},
            {"meshtastic_preset": "CUSTOM", "meshtastic_slot": 14},
            {"meshtastic_slot": -1}, {"meshtastic_slot": 65536},
            {"meshtastic_slot": "14"}, {"meshtastic_slot": True}, {"meshtastic_slot": 1.5},
        ):
            with self.subTest(fields=fields):
                self.assertFalse(VALIDATOR.is_valid(self.config(**fields)))

    def test_meshcore_requires_expanded_nonempty_key(self):
        for value in (KEY_128, KEY_256, KEY_256.upper()):
            VALIDATOR.validate(self.config(meshcore_keys=[{"name": "Test group", "key_hex": value}]))
        for value in ("", "AQ==", "0", "g" * 32, KEY_128 + "\x00", 123, None):
            with self.subTest(value=value):
                self.assertFalse(VALIDATOR.is_valid(self.config(meshcore_keys=[{"name": "Test", "key_hex": value}])))
        # Plaintext remains an explicit option for Meshtastic only.
        VALIDATOR.validate(self.config(meshtastic_keys=[{"name": "Test", "key_hex": ""}]))

    def test_group_key_list_bounds_labels_and_types(self):
        entry = {"name": "Test group", "key_hex": KEY_128}
        VALIDATOR.validate(self.config(meshcore_keys=[entry] * 4))
        for entries in ([entry] * 5, {}, None, [False], [{"name": "Test"}]):
            with self.subTest(entries=entries):
                self.assertFalse(VALIDATOR.is_valid(self.config(meshcore_keys=entries)))
        for name in ("", "a" * 40, "A\x00B", 5):
            with self.subTest(name=name):
                self.assertFalse(VALIDATOR.is_valid(self.config(meshcore_keys=[{"name": name, "key_hex": KEY_128}])))
        # Labels are descriptive; renaming them does not alter key validity.
        VALIDATOR.validate(self.config(meshcore_keys=[{"name": "New label", "key_hex": KEY_128}]))

    def test_old_custom_file_and_disabled_fresh_example_remain_valid(self):
        VALIDATOR.validate(self.config(frequency_mhz=912.125, bandwidth_khz=125,
                                       spreading_factor=9, coding_rate_denominator=7,
                                       preamble_symbols=24))
        example = json.loads((ROOT / "sdcard/lora-tunnel/config.example.json").read_text(encoding="utf-8"))
        VALIDATOR.validate(example)
        self.assertFalse(example["lora"]["enabled"])
        self.assertEqual(example["lora"]["region"], "UNSET")
        self.assertEqual(example["lora"]["meshtastic_keys"], [])
        self.assertEqual(example["lora"]["meshcore_keys"], [])


if __name__ == "__main__":
    unittest.main()
