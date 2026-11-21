"""Recon: classifier fixtures, BlueZ property rebuild, scan parsers, live table and alerts.

tools/check_recon_parity.py separately proves the classifier matches the firmware's C++.
"""

import json
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import Mock

from lora_tunnel_zero import config, recon
from lora_tunnel_zero.demo import DemoBle, DemoWifi
from lora_tunnel_zero.gnss import GPS
from lora_tunnel_zero.recon_scan import Recon, WifiScanner, parse_iw_scan, parse_nmcli
from lora_tunnel_zero.ui import recon_screens, screens
from lora_tunnel_zero.ui.app import App
from lora_tunnel_zero.ui.display import PNGDisplay
from lora_tunnel_zero.ui.keys import ScriptedInput
from lora_tunnel_zero.engine import Engine
from lora_tunnel_zero.demo import DemoRadio

PUBLIC = "10:20:30:40:50:60"


def ad(kind, data):
    return bytes((len(data) + 1, kind)) + bytes(data)


class ClassifierTests(unittest.TestCase):
    def test_vendor_prefixes_are_candidates_not_proof(self):
        alpr = recon.classify_wifi("00:04:7D:11:22:33", "")
        self.assertEqual((alpr["category"], alpr["confidence"]), ("alpr", recon.LOW))
        self.assertIn("candidate", alpr["label"])
        self.assertEqual(recon.classify_wifi("AC:9F:C3:11:22:33", "")["category"], "ring")
        self.assertIsNone(recon.classify_wifi("24:6F:28:11:22:33", "")["category"])

    def test_random_addresses_never_supply_vendor_evidence(self):
        flags = ad(1, [6])
        for kind in (1, 3):
            self.assertIsNone(recon.classify_ble("00:25:DF:01:02:03", kind, flags)["category"])
        self.assertEqual(recon.classify_ble("00:25:DF:01:02:03", 0, flags)["category"], "axon")
        self.assertIsNone(recon.classify_wifi("82:6B:F2:11:22:33", "")["category"])

    def test_signature_grades(self):
        strong = recon.classify_ble(PUBLIC, 0, ad(0xff, [0x4d, 3]) + ad(3, [0x81, 0xfc]))
        self.assertEqual((strong["category"], strong["confidence"]), ("axon", recon.STRONG))
        findmy = recon.classify_ble(PUBLIC, 1, ad(0xff, [0x4c, 0, 0x12, 0x19] + [0] * 25))
        self.assertEqual((findmy["category"], findmy["confidence"]), ("airtag", recon.MEDIUM))
        beacon = recon.classify_ble(PUBLIC, 0, ad(0xff, [0x4c, 0, 2, 0x15] + list(range(16)) + [0x12, 0x34, 0xab, 0xcd, 0xc5]))
        self.assertEqual(beacon["beacon"], {"uuid": bytes(range(16)).hex(), "major": 0x1234, "minor": 0xabcd,
                                            "measured_power": -59})
        self.assertEqual(recon.classify_wifi(PUBLIC, "Flock-12AB")["category"], "flock")
        self.assertIsNone(recon.classify_wifi(PUBLIC, "flock noir")["category"])  # the detector's own AP

    def test_malformed_framing_is_never_classified(self):
        self.assertFalse(recon.classify_ble(PUBLIC, 0, bytes((9, 0xff, 0x4d, 3)))["payload_valid"])
        self.assertIsNone(recon.classify_ble(PUBLIC, 0, b"")["category"])
        self.assertIsNone(recon.classify_ble(PUBLIC, 0, b"\x02\x01\x06" * 200)["category"])

    def test_remote_id_fields(self):
        basic = bytes((0x02, 0x12)) + b"1581F5FKD229400".ljust(20, b"\x00") + b"\x00" * 3
        location = struct.pack("<BBBBbiiHHHBBHB", 0x12, 0x20, 90, 40, 0, int(37.5 * 1e7), int(-122.25 * 1e7),
                               2200, 2200, 2100, 0, 0, 0, 0).ljust(25, b"\x00")
        pack = bytes((0xF2, 25, 2)) + basic + location
        result = recon.classify_ble(PUBLIC, 1, ad(0x16, [0xfa, 0xff, 0x0d, 3] + list(pack)))
        rid = result["remote_id"]
        self.assertEqual(result["category"], "drone")
        self.assertEqual(rid["id"], "1581F5FKD229400")
        self.assertAlmostEqual(rid["latitude"], 37.5)
        self.assertAlmostEqual(rid["altitude_m"], 100.0)
        self.assertAlmostEqual(rid["speed_mps"], 10.0)
        self.assertFalse(rid.get("has_operator", False))

    def test_bluez_properties_rebuild_matches_raw_advert(self):
        raw = ad(9, b"Galaxy SmartTag2") + ad(3, [0x5a, 0xfd]) + ad(0xff, [0xc8, 0x09, 1, 2])
        rebuilt = recon.advertisement_from_properties(
            name="Galaxy SmartTag2", uuids=["0000fd5a-0000-1000-8000-00805f9b34fb"],
            manufacturer={0x09c8: b"\x01\x02"})
        self.assertEqual(recon.classify_ble(PUBLIC, 1, rebuilt)["category"],
                         recon.classify_ble(PUBLIC, 1, raw)["category"])
        flock = recon.advertisement_from_properties(uuids=["e8ccbb38-9532-46a8-9fe5-1814df172e6f"])
        self.assertEqual(recon.classify_ble(PUBLIC, 1, flock)["category"], "flock")
        data = recon.advertisement_from_properties(service_data={"0000feaa-0000-1000-8000-00805f9b34fb":
                                                                 b"\x40" + bytes(20)})
        self.assertEqual(recon.classify_ble(PUBLIC, 1, data)["category"], "tracker")

    def test_vendor_table_matches_firmware_source(self):
        import subprocess, sys
        tool = Path(__file__).resolve().parents[1] / "tools" / "sync_recon_data.py"
        done = subprocess.run([sys.executable, str(tool), "--check"], capture_output=True, text=True)
        if "not found" in (done.stdout + done.stderr).lower():
            self.skipTest("firmware source not present")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


class ParserTests(unittest.TestCase):
    IW = """BSS 00:04:7d:11:22:33(on wlan0)
\tfreq: 2437
\tsignal: -61.00 dBm
\tcapability: ESS Privacy (0x0411)
\tSSID: Cam\\x20Net
\tDS Parameter set: channel 6
\tRSN:\t * Version: 1
BSS aa:bb:cc:dd:ee:ff(on wlan0) -- associated
\tfreq: 5180
\tsignal: -48.00 dBm
\tSSID:
"""

    def test_iw_scan_dump(self):
        nets = parse_iw_scan(self.IW)
        self.assertEqual(nets[0], {"bssid": "00:04:7D:11:22:33", "ssid": "Cam Net", "rssi": -61.0, "channel": 6,
                                   "frequency": 2437, "security": "WPA2/3"})
        self.assertEqual((nets[1]["channel"], nets[1]["ssid"], nets[1]["security"]), (36, "", "open"))

    def test_nmcli_terse_with_escaped_colons(self):
        nets = parse_nmcli("AA\\:BB\\:CC\\:DD\\:EE\\:FF:My\\:Net:11:2462 MHz:80:WPA2\n")
        self.assertEqual(nets[0]["bssid"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(nets[0]["ssid"], "My:Net")
        self.assertEqual((nets[0]["channel"], nets[0]["rssi"], nets[0]["frequency"]), (11, -60.0, 2462))

    def test_wifi_scanner_prefers_iw_and_falls_back(self):
        runner = Mock(side_effect=lambda args, **kw: Mock(returncode=0, stdout=self.IW if args[0] == "iw" else ""))
        scanner = WifiScanner("wlan0", runner=runner)
        import shutil
        original = shutil.which
        try:
            shutil.which = lambda name: "/usr/bin/" + name
            self.assertEqual(len(scanner.scan()), 2)
            self.assertEqual(scanner.method, "iw")
        finally:
            shutil.which = original


class FakeSound:
    def __init__(self):
        self.plays = 0

    def play(self):
        self.plays += 1
        return True


class ReconEngineTests(unittest.TestCase):
    def make(self, **changes):
        cfg = dict(config.DEFAULTS, **changes)
        gps = GPS(use_uart=False)
        sound = FakeSound()
        r = Recon(cfg, gps, wifi=DemoWifi(), ble=DemoBle(), sound=sound)
        return r, gps, sound

    def test_live_run_logs_alerts_and_summarises(self):
        r, gps, sound = self.make()
        gps.update({"class": "TPV", "mode": 3, "lat": 37.0, "lon": -122.0})
        root = Path(tempfile.mkdtemp())
        r.start(root)
        time.sleep(2.5)
        r.stop()
        meta = json.loads((r.directory / "session.json").read_text())
        self.assertEqual((meta["kind"], meta["status"]), ("recon", "closed"))
        self.assertGreater(meta["classified"], 5)
        self.assertGreaterEqual(meta["by_category"].get("drone", 0), 1)
        lines = [json.loads(x) for x in (r.directory / "recon.jsonl").read_text().splitlines()]
        self.assertTrue(any(x["alert"] for x in lines))
        self.assertTrue(all(x["receiver_gps"]["valid"] for x in lines))
        self.assertTrue(any(x.get("advertisement_hex") for x in lines))
        self.assertGreater(sound.plays, 0)
        listed = r.device_list()
        self.assertTrue(all(d["category"] for d in listed))
        self.assertGreater(len(r.device_list(show_all=True)), len(listed))
        self.assertEqual(listed[0]["confidence"], recon.STRONG)

    def test_thresholds_and_categories_filter(self):
        r, _, sound = self.make(recon_display_min="high", recon_alert_min="high", recon_categories=["drone"],
                                recon_sound=False)
        r.directory = None
        for device in r.ble.devices:
            r.observe("ble", {"address": device[0], "address_type": device[1], "raw_ad": device[2], "rssi": -60})
        shown = r.device_list()
        self.assertEqual([d["category"] for d in shown], ["drone"])
        self.assertEqual(len(r.alerts), 1)
        self.assertEqual(sound.plays, 0)

    def test_alerts_repeat_only_after_quiet_period(self):
        r, _, _ = self.make()
        item = {"address": "00:25:DF:01:02:03", "address_type": 0,
                "raw_ad": ad(0xff, [0x4d, 3]) + ad(3, [0x81, 0xfc]), "rssi": -60}
        now = 1_000_000.0
        for offset in (0, 10, 100):
            r.observe("ble", item, now=now + offset)
        self.assertEqual(len(r.alerts), 1)
        r.observe("ble", item, now=now + 400)
        self.assertEqual(len(r.alerts), 2)

    def test_following_needs_time_and_distance(self):
        r, gps, _ = self.make(recon_alert_min="high")
        tracker = {"address": "5A:3C:11:9D:20:7F", "address_type": 1,
                   "raw_ad": ad(0xff, [0x4c, 0, 0x12, 0x19] + [0] * 25), "rssi": -70}
        start = 2_000_000.0
        for minute in range(12):
            gps.update({"class": "TPV", "mode": 3, "lat": 37.0, "lon": -122.0})  # parked
            r.observe("ble", tracker, now=start + minute * 60)
        device = r.devices[("ble", tracker["address"])]
        self.assertFalse(device["follow"])
        self.assertEqual(len(r.alerts), 0)       # medium grade, alerts set to high
        for minute in range(12, 24):
            gps.update({"class": "TPV", "mode": 3, "lat": 37.0 + (minute - 11) * 0.001, "lon": -122.0})
            r.observe("ble", tracker, now=start + minute * 60)
        self.assertTrue(device["follow"])
        self.assertTrue(r.alerts[0]["follow"])
        self.assertEqual(r.summary()["following"], 1)

    def test_scanner_failure_is_reported_not_fatal(self):
        r, _, _ = self.make()
        r.wifi = Mock(scan=Mock(side_effect=RuntimeError("boom")), name="Wi-Fi")
        r.start(Path(tempfile.mkdtemp()))
        time.sleep(1.5)
        r.stop()
        self.assertIn("wifi", r.errors)
        self.assertGreater(r.counters["ble_scans"], 0)


class ReconUITests(unittest.TestCase):
    def test_recon_screens_render_and_alert_banner(self):
        e = Engine(dict(config.DEFAULTS, region="US", backend="demo"),
                   radio_factory=lambda c, p: DemoRadio(p), gps=GPS(use_uart=False))
        root = Path(tempfile.mkdtemp())
        r = Recon(e.cfg, e.gps, wifi=DemoWifi(), ble=DemoBle(), sound=FakeSound())
        app = App(PNGDisplay(root / "f.png"), ScriptedInput(), e, e.cfg, config_path=root / "c.json",
                  data_root=root, splash=False, recon=r)
        app.open("Recon")
        app.compose()
        app.screen.handle(ScriptedInput(["SPACE"]).queue[0], app)
        self.addCleanup(r.stop)
        self.assertEqual(r.state, "running")
        time.sleep(1.5)
        app.compose()
        self.assertEqual(r.unseen_alerts, 0)       # seeing the Recon list clears the banner
        app.screen.handle(ScriptedInput(["ENTER"]).queue[0], app)
        self.assertIsInstance(app.screen, recon_screens.ReconDetail)
        app.compose()
        app.screen.handle(ScriptedInput(["F"]).queue[0], app)
        self.assertIsInstance(app.screen, recon_screens.Finder)
        app.compose()
        app.open("Wardrive")
        r.unseen_alerts = 1
        r.alerts[0]["time"] = time.time()
        app.compose()
        app.open("Settings")
        settings = app.screen
        names = [item[0] for item in settings.items(app)]
        settings.index = names.index("recon_categories")
        settings.handle(ScriptedInput(["ENTER"]).queue[0], app)
        self.assertIsInstance(app.screen, recon_screens.Categories)
        app.screen.handle(ScriptedInput(["ENTER"]).queue[0], app)    # toggle the first category off
        self.assertNotIn(recon.CATEGORIES[0], app.cfg["recon_categories"])
        self.assertNotIn(recon.CATEGORIES[0], r.cfg["recon_categories"])
        app.compose()
        app.open("Help")
        app.compose()
        self.assertIsInstance(app.stack[1], screens.Help)


class BleRefusalTests(unittest.TestCase):
    def test_reasons_say_how_to_fix(self):
        from lora_tunnel_zero.recon_scan import ble_refusal
        self.assertIn("rfkill unblock", ble_refusal("org.bluez.Error.Blocked"))
        self.assertIn("rfkill unblock", ble_refusal("org.bluez.Error.Failed", "Failed due to rfkill"))
        self.assertIn("reboot", ble_refusal("org.freedesktop.DBus.Error.AccessDenied"))
        self.assertIn("rfkill unblock", ble_refusal("org.bluez.Error.NotReady"))
        self.assertIn("(Weird)", ble_refusal("org.bluez.Error.Weird"))


if __name__ == "__main__":
    unittest.main()
