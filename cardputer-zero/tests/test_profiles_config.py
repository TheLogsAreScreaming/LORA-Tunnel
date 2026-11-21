import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from lora_tunnel_zero import config, profiles

ORDER = ["LONG_TURBO", "LONG_FAST", "LONG_SLOW", "MEDIUM_FAST", "MEDIUM_SLOW",
         "SHORT_FAST", "SHORT_SLOW", "LONG_MODERATE", "SHORT_TURBO"]
# Kismet LoRaPipe channel reference (MHz), hop order above.
KISMET = {
    "US": [908.750, 906.875, 905.3125, 913.125, 914.875, 918.875, 920.625, 902.6875, 926.750],
    "ANZ": [921.750, 919.875, 918.3125, 926.125, 927.875, 918.875, 920.625, 915.6875, 926.750],
    "JP": [923.250, 923.375, 920.8125, 920.625, 921.375, 922.375, 923.125, 922.1875, 923.250],
    "KR": [922.750, 922.875, 920.3125, 920.125, 920.875, 921.875, 922.625, 921.6875, 922.750],
    "TW": [920.750, 923.875, 923.3125, 922.125, 924.875, 924.875, 922.625, 921.6875, 922.750],
    "SG_923": [917.750, 917.875, 924.3125, 922.125, 919.875, 917.875, 923.625, 923.6875, 917.750],
    "BR_902": [906.250, 903.875, 903.3125, 906.625, 907.375, 904.375, 905.125, 906.6875, 905.750],
}


class ProfileTests(unittest.TestCase):
    def test_default_slots_match_kismet_lorapipe(self):
        for region, expected in KISMET.items():
            got = [profiles.meshtastic(region, code).frequency_mhz for code in ORDER]
            for preset, a, b in zip(ORDER, got, expected):
                self.assertAlmostEqual(a, b, places=4, msg="%s %s" % (region, preset))

    def test_kismet_channel_names(self):
        self.assertEqual(profiles.meshtastic("US").id, "meshtastic-US-LONG_FAST")
        self.assertEqual(profiles.meshcore("US").id, "meshcore-US-NARROW")
        self.assertEqual(profiles.meshtastic("US", "LONG_FAST", 20).id, "meshtastic-US-LONG_FAST-S20")

    def test_eu868_has_no_turbo_and_explicit_slot_bounds(self):
        with self.assertRaises(ValueError):
            profiles.meshtastic("EU_868", "LONG_TURBO")
        with self.assertRaises(ValueError):
            profiles.meshtastic("US", "LONG_FAST", 105)

    def test_cap_band_excludes_out_of_range_profiles(self):
        socal = next(p for p in profiles.meshcore_profiles("US") if p.label == "Socal")
        self.assertFalse(socal.selectable())
        plan = profiles.scan_plan({"region": "US", "mode": "survey"})
        self.assertTrue(all(p.selectable() for p in plan))
        self.assertNotIn("meshtastic-US-SHORT_TURBO", [p.id for p in plan])  # 926.75 MHz

    def test_survey_drops_cr_only_duplicates(self):
        plan = profiles.scan_plan({"region": "EU_868", "mode": "survey"})
        keys = [(p.frequency_hz, p.bandwidth_hz, p.spreading_factor, p.sync_word) for p in plan]
        self.assertEqual(len(keys), len(set(keys)))

    def test_meshcore_preamble_and_sync(self):
        narrow = profiles.meshcore("US")
        self.assertEqual((narrow.sync_word, narrow.preamble_symbols), (0x12, 32))
        self.assertEqual(profiles.meshtastic("US").sync_word, 0x2B)

    def test_region_required(self):
        for region in ("", None, "UNSET", "US; rm"):
            with self.assertRaises(ValueError):
                profiles.scan_plan({"region": region})

    def test_validate_profile_rejects_out_of_band(self):
        bad = profiles.Profile("x", "x", "US", "meshtastic", 930000000, 250000, 11, 5, 0x2B, 16)
        with self.assertRaises(ValueError):
            profiles.validate_profile(bad)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "config.json"

    def test_defaults_and_roundtrip_with_private_mode(self):
        self.assertEqual(config.load(self.path)["region"], "")
        saved = config.save(dict(config.DEFAULTS, region="US", mode="survey"), self.path)
        self.assertEqual(saved["mode"], "survey")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(config.load(self.path)["region"], "US")

    def test_rejects_bad_values_without_echoing_them(self):
        for key, value in (("region", "Mars"), ("dwell_seconds", 2), ("slot", -1),
                           ("serial_device", "/etc/passwd"), ("meshtastic_keys", [{"name": "a", "key": "!!"}])):
            with self.assertRaises(config.ConfigError) as caught:
                config.validate(key, value)
            self.assertNotIn(str(value), str(caught.exception))

    def test_keys_and_hashtags(self):
        cfg = dict(config.DEFAULTS, meshtastic_keys=[{"name": "Ops", "key": "AQ=="}],
                   meshcore_hashtags=["#test"])
        config.save(cfg, self.path)
        mt, mc = config.decode_keys(config.load(self.path))
        self.assertEqual(mt[0]["name"], "Ops")
        self.assertEqual(mc[0]["name"], "#test")
        with self.assertRaises(config.ConfigError):
            config.validate("meshcore_keys", [{"name": "x", "key": "AQ=="}])  # MeshCore needs 16/32 bytes

    def test_world_readable_or_duplicate_files_rejected(self):
        self.path.write_text(json.dumps({"region": "US"}))
        os.chmod(self.path, 0o644)
        with self.assertRaises(config.ConfigError):
            config.load(self.path)
        self.path.write_text('{"region": "US", "region": "EU_868"}')
        os.chmod(self.path, 0o600)
        with self.assertRaises(config.ConfigError):
            config.load(self.path)


if __name__ == "__main__":
    unittest.main()
