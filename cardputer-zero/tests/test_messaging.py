"""Messaging: outgoing frames decode correctly, transmit gating, relays and limits."""

import base64
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from lora_tunnel_zero import config, mesh_tx
from lora_tunnel_zero.decode import DEFAULT_MESHTASTIC_KEY, PUBLIC_MESHCORE_KEY, decode_packet
from lora_tunnel_zero.demo import DemoRadio
from lora_tunnel_zero.engine import Engine
from lora_tunnel_zero.gnss import GPS
from lora_tunnel_zero.profiles import meshcore, meshtastic
from lora_tunnel_zero.ui import screens
from lora_tunnel_zero.ui.app import App
from lora_tunnel_zero.ui.display import PNGDisplay
from lora_tunnel_zero.ui.keys import ScriptedInput

NODE = 0x4C7A11D3


def cfg(**changes):
    base = dict(config.DEFAULTS, region="US", mode="meshtastic", backend="demo", dwell_seconds=5,
                tx_enabled=True, node_number=NODE, node_name="Rover", node_short="RVR")
    base.update(changes)
    return base


def wait_for(predicate, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class FrameTests(unittest.TestCase):
    def test_meshtastic_text_and_nodeinfo_round_trip(self):
        profile = meshtastic("US")
        frame = mesh_tx.meshtastic_text(NODE, 0x1234, "hello mesh", "LongFast", DEFAULT_MESHTASTIC_KEY, 3)
        decoded = decode_packet(frame, profile)
        self.assertEqual((decoded["decode_status"], decoded["text"]), ("decoded", "hello mesh"))
        self.assertEqual(decoded["source_id"], "!%08x" % NODE)
        self.assertEqual(decoded["destination_id"], "!ffffffff")
        self.assertEqual((decoded["hop_limit"], decoded["hop_start"]), (3, 3))
        self.assertEqual(decoded["channel_name"], "LongFast")
        info = decode_packet(mesh_tx.meshtastic_nodeinfo(NODE, 7, "Rover", "RVR", "LongFast",
                                                         DEFAULT_MESHTASTIC_KEY), profile)
        self.assertEqual((info["name"], info["short_name"], info["user_id"]), ("Rover", "RVR", "!%08x" % NODE))

    def test_private_meshtastic_channel_and_aes256(self):
        key = bytes(range(32))
        frame = mesh_tx.meshtastic_text(NODE, 99, "secret", "Ops", key)
        keys = [{"name": "Ops", "key": base64.b64encode(key).decode()}]
        self.assertEqual(decode_packet(frame, meshtastic("US"), meshtastic_keys=keys)["text"], "secret")
        self.assertEqual(decode_packet(frame, meshtastic("US"))["decode_status"], "encrypted")

    def test_meshcore_group_text_round_trip_and_hashtag(self):
        frame = mesh_tx.meshcore_group_text(PUBLIC_MESHCORE_KEY, "Rover", "hi all", timestamp=1700000000)
        decoded = decode_packet(frame, meshcore("US"))
        self.assertEqual(decoded["text"], "Rover: hi all")
        self.assertEqual(decoded["message_timestamp"], 1700000000)
        self.assertTrue(decoded["payload_authenticated"])
        secret = hashlib.sha256(b"#wardrive").digest()[:16]
        tagged = mesh_tx.meshcore_group_text(secret, "Rover", "tag")
        keys = [{"name": "#wardrive", "key": base64.b64encode(secret).decode()}]
        self.assertEqual(decode_packet(tagged, meshcore("US"), meshcore_keys=keys)["channel_name"], "#wardrive")

    def test_length_limits(self):
        with self.assertRaises(mesh_tx.SendError):
            mesh_tx.meshtastic_text(NODE, 1, "x" * 201, "LongFast", DEFAULT_MESHTASTIC_KEY)
        with self.assertRaises(mesh_tx.SendError):
            mesh_tx.meshcore_group_text(PUBLIC_MESHCORE_KEY, "Rover", "y" * 140)
        with self.assertRaises(mesh_tx.SendError):
            mesh_tx.meshtastic_text(NODE, 1, "", "LongFast", DEFAULT_MESHTASTIC_KEY)

    def test_airtime_matches_semtech_calculator(self):
        # LongFast (SF11, 250 kHz, CR4/5, 16-symbol preamble), 50 bytes: 20.25 + 58 symbols of 8.192 ms.
        self.assertAlmostEqual(mesh_tx.airtime(meshtastic("US"), 50), 0.641, places=3)
        # LongSlow (SF12, 125 kHz, CR4/8) uses low-data-rate optimisation: 24 payload symbols of 32.768 ms.
        self.assertAlmostEqual(mesh_tx.airtime(meshtastic("US", "LONG_SLOW"), 10), (20.25 + 24) * 0.032768, places=3)
        # MeshCore narrow SF7 62.5 kHz, 32-symbol preamble.
        self.assertGreater(mesh_tx.airtime(meshcore("US"), 50), mesh_tx.airtime(meshcore("US"), 10))

    def test_send_channels_follow_keys_and_defaults(self):
        c = cfg(meshcore_hashtags=["#wardrive"], meshtastic_keys=[{"name": "Ops", "key": "AQ=="}])
        self.assertEqual([n for n, _ in mesh_tx.send_channels(c, "meshtastic")], ["LongFast", "Ops"])
        self.assertEqual([n for n, _ in mesh_tx.send_channels(c, "meshcore")], ["Public", "#wardrive"])
        c["decode_public"] = False
        self.assertEqual([n for n, _ in mesh_tx.send_channels(c, "meshcore")], ["#wardrive"])

    def test_node_numbers_avoid_reserved_values(self):
        for _ in range(200):
            self.assertTrue(4 <= mesh_tx.new_node_number() < 0xFFFFFFFF)


class EngineSendTests(unittest.TestCase):
    def make(self, **changes):
        radios = []

        def factory(c, p):
            radios.append(DemoRadio(p, rate=0.01))
            return radios[-1]
        e = Engine(cfg(**changes), radio_factory=factory, gps=GPS(use_uart=False))
        return e, radios

    def test_transmit_off_and_not_capturing_are_refused(self):
        e, _ = self.make(tx_enabled=False)
        with self.assertRaises(mesh_tx.SendError):
            e.send("meshtastic", "LongFast", "hi")
        e.cfg["tx_enabled"] = True
        with self.assertRaisesRegex(mesh_tx.SendError, "Start the radio"):
            e.send("meshtastic", "LongFast", "hi")

    def test_send_is_sent_relayed_logged_and_not_counted_as_heard(self):
        e, radios = self.make()
        e.start(Path(tempfile.mkdtemp()))
        self.addCleanup(e.stop)
        self.assertTrue(radios[0].allow_tx)
        message = e.send("meshtastic", "LongFast", "testing 1 2")
        self.assertEqual(message["status"], "queued")
        self.assertTrue(wait_for(lambda: message["status"] == "relayed"))
        self.assertEqual(len(radios[0].sent), 2)       # NodeInfo first, then the text
        self.assertEqual(message["heard"], 1)
        self.assertEqual([m for m in e.messages if not m.get("outgoing")], [])
        self.assertNotIn(("meshtastic", "!%08x" % NODE), e.nodes)
        with self.assertRaisesRegex(mesh_tx.SendError, "Wait"):
            e.send("meshtastic", "LongFast", "too fast")
        e.stop()
        rows = [json.loads(line) for line in (e.directory / "observations.jsonl").read_text().splitlines()]
        tx = [r for r in rows if r.get("direction") == "tx"]
        self.assertEqual([r["tx_kind"] for r in tx], ["nodeinfo", "text"])
        self.assertEqual(json.loads((e.directory / "session.json").read_text())["counters"]["sent"], 1)

    def test_meshcore_send_retunes_and_returns(self):
        e, radios = self.make(mode="both")
        e.start(Path(tempfile.mkdtemp()))
        self.addCleanup(e.stop)
        active = e.active
        self.assertEqual(active.protocol, "meshtastic")
        message = e.send("meshcore", "Public", "from the cap")
        self.assertTrue(wait_for(lambda: message["status"] in ("sent", "relayed")))
        frame, profile_id, power = radios[0].sent[-1]
        self.assertTrue(profile_id.startswith("meshcore-US"))
        self.assertEqual(power, 17)
        self.assertEqual(radios[0].profile, active)
        self.assertEqual(decode_packet(frame, meshcore("US"))["text"], "Rover: from the cap")

    def test_power_capped_by_region_and_duty_cycle_enforced(self):
        e, radios = self.make(region="EU_868", tx_power_dbm=22, mode="meshcore")
        e.start(Path(tempfile.mkdtemp()))
        self.addCleanup(e.stop)
        e._airtime.append((time.monotonic(), 359.9))  # nearly all of the 10% hourly budget
        with self.assertRaisesRegex(mesh_tx.SendError, "airtime"):
            e.send("meshcore", "Public", "hi")
        e._airtime.clear()
        message = e.send("meshcore", "Public", "hi")
        self.assertTrue(wait_for(lambda: message["status"] in ("sent", "relayed")))
        self.assertEqual(mesh_tx.region_limits("UA_868"), (14, 1))
        self.assertEqual(mesh_tx.region_limits("nowhere"), (14, 1))

    def test_lorapipe_style_receiver_cannot_transmit(self):
        class ReceiveOnly(DemoRadio):
            transmit = None
        e = Engine(cfg(), radio_factory=lambda c, p: ReceiveOnly(p, rate=0.01), gps=GPS(use_uart=False))
        e.start(Path(tempfile.mkdtemp()))
        self.addCleanup(e.stop)
        del ReceiveOnly.transmit
        e.radio.__class__ = type("NoTx", (), {k: getattr(DemoRadio, k) for k in ("receive", "close", "tune", "open")})
        self.assertIn("can't transmit", e.can_transmit())


class ComposeUITests(unittest.TestCase):
    def make_app(self, **changes):
        e = Engine(cfg(**changes), radio_factory=lambda c, p: DemoRadio(p, rate=0.01), gps=GPS(use_uart=False))
        root = Path(tempfile.mkdtemp())
        app = App(PNGDisplay(root / "f.png"), ScriptedInput(), e, e.cfg, config_path=root / "c.json",
                  data_root=root, splash=False)
        self.addCleanup(app.recon.stop)
        self.addCleanup(e.stop)
        return app

    def press(self, app, *names):
        for name in names:
            app.screen.handle(ScriptedInput([name]).queue[0], app)

    def test_first_send_asks_to_turn_on_transmit_and_for_a_name(self):
        app = self.make_app(tx_enabled=False, node_number=0, node_name="")
        app.open("Messages")
        self.press(app, "ENTER")
        self.assertIsInstance(app.screen, screens.Confirm)
        self.assertIn("responsible", app.screen.detail)
        self.press(app, "Y")
        self.assertTrue(app.cfg["tx_enabled"])
        self.assertTrue(app.cfg["node_number"])
        self.assertIsInstance(app.screen, screens.TextInput)
        app.screen.value = "Kestrel"
        self.press(app, "ENTER")
        self.assertEqual(app.cfg["node_name"], "Kestrel")
        self.assertIsInstance(app.screen, screens.Compose)
        for ch in "hello":
            self.press(app, ch)
        self.press(app, "ENTER")                   # starts the radio, then queues
        self.assertEqual(app.engine.state, "capturing")
        self.assertIsInstance(app.screen, screens.Messages)
        outgoing = [m for m in app.engine.messages if m.get("outgoing")]
        self.assertEqual(outgoing[0]["text"], "hello")
        app.compose()

    def test_turning_transmit_off_is_immediate(self):
        app = self.make_app()
        app.pick_setting("tx_enabled")
        self.assertFalse(app.cfg["tx_enabled"])
        self.assertFalse(json.loads(app.config_path.read_text())["tx_enabled"])

    def test_compose_tab_cycles_channels_and_counts_bytes(self):
        app = self.make_app(mode="both", meshcore_hashtags=["#wardrive"])
        app.write_message(("meshcore", "#wardrive"))
        compose = app.screen
        self.assertEqual(compose.targets[compose.index], ("meshcore", "#wardrive"))
        self.press(app, "TAB")
        self.assertEqual(compose.targets[compose.index], ("meshtastic", "LongFast"))
        compose.value = "x" * 199
        self.press(app, "a", "b")
        self.assertEqual(len(compose.value), 200)
        app.compose()


if __name__ == "__main__":
    unittest.main()
