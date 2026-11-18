"""Messaging configuration and public-package privacy checks; no device access."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/config-v1.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)
KEY_128 = "000102030405060708090a0b0c0d0e0f"
KEY_256 = KEY_128 + "101112131415161718191a1b1c1d1e1f"
BASE = {"schema": 1, "lora": {"enabled": False, "region": "UNSET"}, "credentials": {}}


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class MessagingSchemaTests(unittest.TestCase):
    def config(self, **fields):
        value = deepcopy(BASE)
        value["messaging"] = fields
        return value

    def test_legacy_defaults_and_public_example(self):
        VALIDATOR.check_schema(SCHEMA)
        VALIDATOR.validate(BASE)
        VALIDATOR.validate(self.config())
        example = json.loads((ROOT / "sdcard/lora-tunnel/config.example.json").read_text(encoding="utf-8"))
        VALIDATOR.validate(example)
        self.assertEqual(example["messaging"], {"name": "LORA Tunnel", "meshtastic_channel": "",
                         "meshtastic_key_hex": "", "meshcore_key_hex": "", "hop_limit": 3})
        self.assertFalse(example["lora"]["enabled"])
        self.assertEqual(example["lora"]["region"], "UNSET")

    def test_printable_name_and_channel_byte_limits(self):
        for name in ("LORA Tunnel", "N" * 31, "Fixture! @#[]_"):
            VALIDATOR.validate(self.config(name=name))
        for name in ("", "N" * 32, "A:B", "A\x00B", "A\n", "A\r", "A\t", "Caf\u00e9", 0, None):
            with self.subTest(name=name):
                self.assertFalse(VALIDATOR.is_valid(self.config(name=name)))
        for name in ("", "LongTurbo", "C" * 39):
            VALIDATOR.validate(self.config(meshtastic_channel=name))
        for name in ("C" * 40, "C\x00B", "C\n", "\u2603", False, None):
            with self.subTest(channel=name):
                self.assertFalse(VALIDATOR.is_valid(self.config(meshtastic_channel=name)))

    def test_keys_accept_public_reset_or_expanded_hex_only(self):
        for field in ("meshtastic_key_hex", "meshcore_key_hex"):
            for value in ("", KEY_128, KEY_256, KEY_256.upper()):
                VALIDATOR.validate(self.config(**{field: value}))
            for value in ("AQ==", "0", "f" * 31, "f" * 33, "f" * 65, "g" * 32,
                          KEY_128 + "\n", KEY_128 + "\x00", 123, None, []):
                with self.subTest(field=field, value=value):
                    self.assertFalse(VALIDATOR.is_valid(self.config(**{field: value})))
        self.assertTrue(SCHEMA["$defs"]["messaging_key"]["writeOnly"])

    def test_hops_and_saved_transmit_flags(self):
        for hops in range(8):
            VALIDATOR.validate(self.config(hop_limit=hops))
        for hops in (-1, 8, 1.5, "3", True, None):
            self.assertFalse(VALIDATOR.is_valid(self.config(hop_limit=hops)))
        # Firmware separately ignores these imported flags. The schema rejects
        # attempts to use a config file as a transmit-permission mechanism.
        VALIDATOR.validate(self.config(enabled=False, tx_enabled=False))
        self.assertFalse(VALIDATOR.is_valid(self.config(enabled=True)))
        self.assertFalse(VALIDATOR.is_valid(self.config(tx_enabled=True)))
        for value in (None, [], "enabled"):
            document = deepcopy(BASE)
            document["messaging"] = value
            self.assertFalse(VALIDATOR.is_valid(document))
        VALIDATOR.validate(self.config(future_metadata={"preserved": True}))


class MessagingPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = module("package_source")
        cls.web = module("build_web")

    def archive(self, path, config, extra=None):
        entries = {"include/version.h": b'#define TUNNEL_VERSION "0.5.0"\n',
                   "sdcard/lora-tunnel/config.example.json": json.dumps(config).encode(),
                   "sdcard/lora-tunnel/detection_rules.json": b'{"schema":1,"rules":[]}'}
        entries.update(extra or {})
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in entries.items():
                archive.writestr("LORA-Tunnel/" + name, data)
            archive.writestr("LORA-Tunnel/SOURCE-SHA256.json", json.dumps(
                {name: hashlib.sha256(data).hexdigest() for name, data in entries.items()}))

    def collect_fixture(self, root, config):
        folder = root / "sdcard/lora-tunnel"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.example.json").write_text(json.dumps(config), encoding="utf-8")
        (folder / "detection_rules.json").write_text('{"schema":1,"rules":[]}', encoding="utf-8")
        with patch.object(self.source, "FOLDERS", ()), patch.object(self.source, "FILES", (
            "sdcard/lora-tunnel/config.example.json", "sdcard/lora-tunnel/detection_rules.json")):
            return self.source.collect_paths(root)

    def test_legacy_and_blank_messaging_packages_stay_accepted(self):
        for config in (BASE, dict(BASE, messaging={"meshtastic_key_hex": "", "meshcore_key_hex": ""})):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.assertEqual(len(self.collect_fixture(root, config)), 2)
                self.archive(root / "source.zip", config)
                self.assertIn("include/version.h", self.web.read_source(root / "source.zip", "0.5.0"))

    def test_both_packaging_paths_reject_nonempty_or_malformed_keys_privately(self):
        for field in ("meshtastic_key_hex", "meshcore_key_hex"):
            for value in (KEY_128, KEY_256, "DO-NOT-DISCLOSE-FIXTURE", None, False, []):
                with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as directory:
                    config = dict(BASE, messaging={field: value})
                    root = Path(directory)
                    with self.assertRaisesRegex(ValueError, "messaging keys must be empty") as caught:
                        self.collect_fixture(root, config)
                    self.assertNotIn(str(value), str(caught.exception))
                    self.archive(root / "source.zip", config)
                    with self.assertRaisesRegex(ValueError, "messaging keys must be empty") as caught:
                        self.web.read_source(root / "source.zip", "0.5.0")
                    self.assertNotIn(str(value), str(caught.exception))

    def test_malformed_and_unknown_messaging_fields_fail_closed(self):
        for value in (None, [], "DO-NOT-DISCLOSE-FIXTURE", {"private_seed": "DO-NOT-DISCLOSE-FIXTURE"}, {"tx_enabled": True}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as caught:
                    self.source.validate_public_messaging(dict(BASE, messaging=value))
                self.assertNotIn("DO-NOT-DISCLOSE-FIXTURE", str(caught.exception))

    def test_vendored_crypto_source_requires_retained_license_and_provenance(self):
        prefix = "lib/meshdecode/src/meshcore_ed25519/"
        for absent in ("license.txt", "README.md"):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "source.zip"
                extra = {prefix + name: b"synthetic fixture" for name in ("key_exchange.c", "license.txt", "README.md") if name != absent}
                self.archive(path, BASE, extra)
                with self.assertRaisesRegex(ValueError, "license and provenance"):
                    self.web.read_source(path, "0.5.0")
        names = {path.relative_to(ROOT).as_posix() for path in self.source.collect_paths(ROOT)}
        self.assertTrue({prefix + "key_exchange.c", prefix + "license.txt", prefix + "README.md", "docs/MESSAGING.md"} <= names)


if __name__ == "__main__":
    unittest.main()
