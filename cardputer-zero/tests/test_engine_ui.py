import csv
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from lora_tunnel_zero import config
from lora_tunnel_zero.demo import DemoRadio
from lora_tunnel_zero.engine import Engine
from lora_tunnel_zero.export import export_session
from lora_tunnel_zero.gnss import GPS, nmea_fix
from lora_tunnel_zero.ui import screens
from lora_tunnel_zero.ui.app import App
from lora_tunnel_zero.ui.display import PNGDisplay, to_rgb565
from lora_tunnel_zero.ui.keys import EvdevInput, ScriptedInput


def cfg(**changes):
    base = dict(config.DEFAULTS, region="US", mode="both", backend="demo", dwell_seconds=5)
    base.update(changes)
    return base


def engine(**changes):
    gps = GPS(use_uart=False)
    return Engine(cfg(**changes), radio_factory=lambda c, p: DemoRadio(p, rate=25), gps=gps), gps


class EngineTests(unittest.TestCase):
    def test_capture_decodes_tracks_and_closes_session(self):
        e, gps = engine()
        gps.update({"class": "TPV", "mode": 3, "lat": 37.0, "lon": -122.0})
        root = Path(tempfile.mkdtemp())
        e.start(root)
        time.sleep(2.5)
        e.hop(1)
        time.sleep(1.5)
        e.stop()
        meta = json.loads((e.directory / "session.json").read_text())
        self.assertEqual(meta["status"], "closed")
        self.assertGreater(meta["counters"]["saved"], 5)
        self.assertEqual(meta["counters"]["saved"], meta["counters"]["received"])
        self.assertGreater(len(e.nodes), 2)
        self.assertTrue(any(n["protocol"] == "meshcore" for n in e.nodes.values()))
        db = sqlite3.connect(e.directory / "capture.sqlite3")
        rows = db.execute("SELECT count(*), count(latitude) FROM observations").fetchone()
        self.assertEqual(rows[0], meta["counters"]["saved"])
        self.assertEqual(rows[0], rows[1])  # every frame carries the receiver fix
        lines = (e.directory / "observations.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), rows[0])
        self.assertEqual((e.directory / "lora.pcap").read_bytes()[20:24], (270).to_bytes(4, "little"))

        files = export_session(e.directory)
        with files[0].open() as stream:
            nodes = list(csv.DictReader(stream))
        self.assertEqual(len(nodes), len(e.nodes))
        self.assertIn("<Placemark>", files[1].read_text())

    def test_radio_open_failure_leaves_interrupted_session(self):
        from lora_tunnel_zero import RadioError

        def broken(c, p):
            raise RadioError("Cap LoRa-1262 antenna switch not found on I2C1 at 0x43")
        e = Engine(cfg(), radio_factory=broken, gps=GPS(use_uart=False))
        with self.assertRaises(RadioError):
            e.start(Path(tempfile.mkdtemp()))
        self.assertEqual(e.state, "error")
        meta = json.loads((e.directory / "session.json").read_text())
        self.assertEqual(meta["status"], "interrupted")
        self.assertIn("antenna switch", meta["errors"][0])

    def test_storage_failure_stops_capture(self):
        e, _ = engine()
        e.start(Path(tempfile.mkdtemp()))
        with patch.object(e.store, "append", side_effect=OSError("disk")):
            time.sleep(1.2)
        e.stop()
        meta = json.loads((e.directory / "session.json").read_text())
        self.assertEqual(meta["status"], "interrupted")
        self.assertIn("Storage failed", meta["errors"][0])


class GnssTests(unittest.TestCase):
    def test_nmea_checksums_and_fix(self):
        rmc = b"$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n"
        report = nmea_fix(rmc)
        self.assertAlmostEqual(report["lat"], 48.1173, places=4)
        self.assertIsNone(nmea_fix(rmc.replace(b"*6A", b"*00")))

    def test_stale_fix_drops_coordinates(self):
        gps = GPS(use_uart=False)
        gps.update({"class": "TPV", "mode": 2, "lat": 1.0, "lon": 2.0}, now=100)
        self.assertTrue(gps.snapshot(now=105)["valid"])
        stale = gps.snapshot(now=120)
        self.assertFalse(stale["valid"])
        self.assertNotIn("latitude", stale)


class KeyTests(unittest.TestCase):
    def test_cardputer_arrow_aliases_and_text_mode(self):
        keys = EvdevInput(paths=[])
        self.assertEqual(keys.translate(39, 1).name, "UP")       # ;
        self.assertEqual(keys.translate(52, 1).name, "DOWN")     # .
        self.assertEqual(keys.translate(41, 1).name, "ESC")      # `
        keys.text_mode = True
        self.assertEqual(keys.translate(39, 1).char, ";")
        keys.translate(42, 1)                                     # shift down
        self.assertEqual(keys.translate(30, 1).char, "A")
        self.assertIsNone(keys.translate(30, 0))                  # releases ignored


class UITests(unittest.TestCase):
    def make_app(self, e=None):
        e = e or engine()[0]
        work = Path(tempfile.mkdtemp())
        return App(PNGDisplay(work / "f.png"), ScriptedInput(), e, e.cfg, config_path=work / "c.json",
                   data_root=work, splash=False)

    def test_every_screen_renders_empty_and_live(self):
        app = self.make_app()
        all_screens = [screens.Home(), screens.Wardrive(), screens.Nodes(), screens.Packets(), screens.Messages(),
                       screens.Sessions(), screens.Settings(), screens.About(), screens.KeyList("meshcore_keys")]
        for screen in all_screens:
            app.stack = [screens.Home(), screen]
            self.assertEqual(app.compose().size, (320, 170))
        app.toggle_capture()
        time.sleep(1.5)
        for screen in all_screens:
            app.stack = [screens.Home(), screen]
            app.compose()
        item = app.engine.recent[0]
        app.stack = [screens.Home(), screens.PacketDetail(item)]
        app.compose()
        node = app.engine.node_list()[0]
        app.stack = [screens.Home(), screens.NodeDetail(node["protocol"], node["id"])]
        app.compose()
        app.toggle_capture()
        self.assertEqual(app.engine.state, "idle")
        self.assertEqual(len(to_rgb565(app.compose())), 320 * 170 * 2)

    def test_navigation_settings_and_first_run_region(self):
        e, _ = engine(region="")
        e.cfg["region"] = ""
        app = self.make_app(e)
        app.cfg["region"] = ""
        app.step(0)
        self.assertIsInstance(app.screen, screens.Picker)    # region asked on first run
        app.screen.handle(ScriptedInput(["ENTER"]).queue[0], app)
        self.assertEqual(app.cfg["region"], "US")
        app.open("Settings")
        settings = app.screen
        settings.index = 1                                    # scan mode
        settings.handle(ScriptedInput(["ENTER"]).queue[0], app)
        self.assertIsInstance(app.screen, screens.Picker)
        app.screen.index = 3                                  # survey
        app.screen.handle(ScriptedInput(["ENTER"]).queue[0], app)
        self.assertEqual(app.cfg["mode"], "survey")
        self.assertEqual(json.loads(app.config_path.read_text())["mode"], "survey")

    def test_text_input_and_key_management(self):
        app = self.make_app()
        app.push(screens.KeyList("meshtastic_keys"))
        app.screen.handle(ScriptedInput(["A"]).queue[0], app)
        for ch in "Ops":
            app.screen.handle(ScriptedInput([ch]).queue[0], app)
        app.screen.handle(ScriptedInput(["ENTER"]).queue[0], app)
        entry = app.screen
        entry.value = "AQ=="
        entry.handle(ScriptedInput(["ENTER"]).queue[0], app)
        self.assertEqual(app.cfg["meshtastic_keys"], [{"name": "ops", "key": "AQ=="}])
        app.compose()


if __name__ == "__main__":
    unittest.main()
