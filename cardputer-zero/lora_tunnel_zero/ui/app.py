"""Navigation, chrome (status bar and key hints) and the main loop."""

from pathlib import Path
import shutil
import time

from PIL import Image

from .. import RadioError, config as configuration, mesh_tx, profiles
from ..export import export_recon, export_session
from ..recon_scan import Recon
from ..store import list_sessions
from ..updates import UpdateChecker
from . import icons, recon_screens, screens
from .gfx import (AMBER, BG, CYAN, FAINT, FOOTER_H, GREEN, H, LINE, MUTED, RED, STATUS_H, SURFACE, TEXT, W,
                  Canvas, clock, font, image)


def make_recon(cfg, gps):
    if cfg.get("backend") == "demo":
        from ..demo import DemoBle, DemoWifi
        return Recon(cfg, gps, wifi=DemoWifi(), ble=DemoBle())
    return Recon(cfg, gps)


class App:
    def __init__(self, display, keyboard, engine, cfg, config_path=None, data_root=None, splash=True, recon=None,
                 updates=None, check_updates_on_start=False):
        self.display, self.keyboard, self.engine = display, keyboard, engine
        self.cfg = dict(cfg)
        self.recon = recon or make_recon(self.cfg, engine.gps)
        self.config_path = config_path
        self._data_root = data_root
        self.stack = [screens.Home()]
        if splash:
            self.stack.append(screens.Splash())
        self.running = True
        self.toast_text, self.toast_color, self.toast_until = "", GREEN, 0.0
        self._sessions, self._sessions_at = [], 0.0
        self.dirty = True
        self._first_run_checked = False
        self.updates = updates or UpdateChecker()
        self._check_updates_on_start = check_updates_on_start

    # -- navigation ------------------------------------------------------
    @property
    def screen(self):
        return self.stack[-1]

    def push(self, screen):
        self.stack.append(screen)
        self.dirty = True

    def pop(self):
        if len(self.stack) > 1:
            self.stack.pop()
        self.dirty = True

    def open(self, name):
        factory = {"Wardrive": screens.Wardrive, "Nodes": screens.Nodes, "Messages": screens.Messages,
                   "Packets": screens.Packets, "Sessions": screens.Sessions, "Settings": screens.Settings,
                   "Recon": recon_screens.Recon, "Help": screens.Help}
        # Jumping between top-level screens replaces rather than deepens the stack.
        while len(self.stack) > 1 and not isinstance(self.stack[-1], screens.Modal):
            self.stack.pop()
        self.push(factory[name]())

    def quit(self):
        self.running = False

    def toast(self, text, color=GREEN, seconds=2.5):
        self.toast_text, self.toast_color, self.toast_until = text, color, time.monotonic() + seconds
        self.dirty = True

    def confirm(self, title, detail, action, callback):
        self.push(screens.Confirm(title, detail, action, callback))

    # -- data ------------------------------------------------------------
    def data_root(self):
        return self._data_root or configuration.data_dir(self.cfg)

    def sessions_root(self):
        return self.data_root() / "sessions"

    def session_cache(self, refresh=False):
        if refresh or time.monotonic() - self._sessions_at > 5:
            self._sessions = list_sessions(self.sessions_root())
            self._sessions_at = time.monotonic()
        return self._sessions

    def save_config(self, **changes):
        candidate = dict(self.cfg, **changes)
        try:
            self.cfg = configuration.save(candidate, self.config_path)
        except configuration.ConfigError as exc:
            self.toast(str(exc), AMBER)
            return False
        self.engine.cfg = dict(self.cfg)
        self.engine._mt_keys, self.engine._mc_keys = configuration.decode_keys(self.cfg)
        self.recon.cfg = dict(self.cfg)
        radio = self.engine.radio
        if radio is not None and hasattr(radio, "allow_tx"):
            radio.allow_tx = bool(self.cfg.get("tx_enabled"))
        return True

    # -- actions ---------------------------------------------------------
    def toggle_recon(self):
        r = self.recon
        if r.state == "running":
            r.stop()
            self.session_cache(refresh=True)
            self.toast("Recon saved  ·  %d devices, %d flagged" % (len(r.devices), sum(
                1 for d in r.devices.values() if d.get("category"))))
            return
        try:
            r.cfg = dict(self.cfg)
            r.start(self.sessions_root())
        except (OSError, RuntimeError, ValueError) as exc:
            self.toast(str(exc) or type(exc).__name__, RED, 4)
            return
        if not isinstance(self.screen, recon_screens.Recon):
            self.open("Recon")
        self.toast("Recon started", GREEN)

    # -- messaging -------------------------------------------------------
    def send_targets(self):
        mode = self.cfg.get("mode", "meshtastic")
        protocols = ["meshtastic"] if mode == "meshtastic" else ["meshcore"] if mode == "meshcore" \
            else ["meshtastic", "meshcore"]
        targets = []
        for protocol in protocols:
            targets += [(protocol, name) for name, _ in mesh_tx.send_channels(self.cfg, protocol)]
        return targets

    def write_message(self, target=None):
        if not self.cfg.get("tx_enabled"):
            self.offer_transmit(lambda: self.write_message(target))
            return
        targets = self.send_targets()
        if not targets:
            self.toast("Add a channel key or turn on default channels first", AMBER, 4)
            return
        self.push(screens.Compose(targets, target))

    def offer_transmit(self, then=None):
        region = self.cfg.get("region")
        if not region:
            self.pick_region()
            return
        cap, duty = mesh_tx.region_limits(region)
        power = min(self.cfg.get("tx_power_dbm", 17), cap)
        detail = ("LORA Tunnel will transmit your messages at %d dBm in %s%s. You're responsible for "
                  "following local radio rules." % (power, profiles.REGIONS[region].label,
                                                     ", %d%% duty cycle" % duty if duty < 100 else ""))

        def enable():
            changes = {"tx_enabled": True}
            if not self.cfg.get("node_number"):
                changes["node_number"] = mesh_tx.new_node_number()
            if self.save_config(**changes):
                self.toast("Transmit on")
                if not self.cfg.get("node_name"):
                    default = self.engine.identity()[1]

                    def named(value):
                        self.save_config(node_name=value[:32])
                        if then:
                            then()
                    self.push(screens.TextInput("Your name on the mesh", named, initial=default))
                elif then:
                    then()
        self.confirm("Turn on transmit?", detail, "Turn on", enable)

    def send_message(self, protocol, channel, text):
        e = self.engine
        if e.state != "capturing":
            self.toggle_capture(show=False)
            if e.state != "capturing":
                return False
        try:
            e.send(protocol, channel, text)
        except mesh_tx.SendError as exc:
            self.toast(str(exc), AMBER, 4)
            return False
        self.toast("Sending on %s" % channel)
        return True

    def toggle_capture(self, show=True):
        e = self.engine
        if e.state == "capturing":
            e.stop()
            extra = ""
            if getattr(self, "_recon_with_capture", False) and self.recon is not None and \
                    self.recon.state == "running":
                summary = self.recon.summary()
                self.recon.stop()
                extra = "  ·  %d Wi-Fi, %d BLE" % (summary["wifi_total"], summary["ble_total"])
            self._recon_with_capture = False
            self.session_cache(refresh=True)
            self.toast("Session saved  ·  %d packets%s" % (e.counters.get("saved", 0), extra) if not e.error
                       else e.error, GREEN if not e.error else AMBER)
            return
        if not self.cfg.get("region"):
            self.pick_region(then_start=True)
            return
        try:
            e.cfg = dict(self.cfg)
            e.start(self.sessions_root())
        except (RadioError, ValueError, RuntimeError, OSError) as exc:
            e.state = "error"
            e.error = str(exc) or type(exc).__name__
            self.toast(e.error, RED, 4)
            return
        label = "Capture started"
        if self.cfg.get("wardrive_wifi_ble", True) and self.recon is not None and self.recon.state != "running":
            try:
                self.recon.cfg = dict(self.cfg)
                self.recon.start(self.sessions_root())
                self._recon_with_capture = True
                label = "Wardriving LoRa + Wi-Fi + BLE"
            except (OSError, RuntimeError, ValueError):
                self._recon_with_capture = False
        if show and not isinstance(self.screen, screens.Wardrive):
            self.open("Wardrive")
        self.toast(label, GREEN)

    def pick_region(self, then_start=False):
        options = [(code, region.label, code) for code, region in profiles.REGIONS.items()
                   if self._region_usable(code)]

        def chosen(code):
            if self.save_config(region=code) and then_start:
                self.toggle_capture()
        self.push(screens.Picker("LoRa region", options, self.cfg.get("region"), chosen))

    @staticmethod
    def _region_usable(code):
        try:
            return bool(profiles.scan_plan({"region": code, "mode": "survey"}))
        except ValueError:
            return False

    def pick_setting(self, name):
        cfg = self.cfg
        if name == "region":
            return self.pick_region()
        if name == "mode":
            options = [(m, profiles.MODE_LABELS[m], "") for m in profiles.MODES]
        elif name == "preset":
            options = []
            for code, preset in profiles.PRESETS.items():
                try:
                    p = profiles.meshtastic(cfg.get("region") or "US", code)
                    ok = p.selectable()
                except ValueError:
                    continue
                options.append((code, preset.name, "%.3f" % p.frequency_mhz if ok else "out of band"))
        elif name == "slot":
            preset = profiles.PRESETS[cfg.get("preset", "LONG_FAST")]
            region = profiles.REGIONS.get(cfg.get("region") or "US")
            count = profiles.slot_count(region, preset)
            options = [(0, "Default for preset", "")]
            for slot in range(1, count + 1):
                p = profiles.meshtastic(region.code, preset.code, slot)
                if p.selectable():
                    options.append((slot, "Slot %d" % slot, "%.4f MHz" % p.frequency_mhz))
        elif name == "meshcore_profile":
            options = [("AUTO", "Automatic", "")]
            for p in profiles.meshcore_profiles(cfg.get("region") or "US"):
                options.append((p.id.split("-", 1)[1], p.label,
                                "%.3f SF%d" % (p.frequency_mhz, p.spreading_factor) if p.selectable() else "out of band"))
        elif name in ("dwell_seconds", "survey_dwell_seconds"):
            options = [(v, "%d seconds" % v, "") for v in (5, 10, 15, 30, 45, 60, 120, 300)]
        elif name == "backend":
            options = [("cap", "Cap LoRa-1262", "built-in"), ("lorapipe", "LoRaPipe serial", "USB"),
                       ("demo", "Demo", "synthetic")]
        elif name == "decode_public":
            return self.save_config(decode_public=not cfg.get("decode_public", True))
        elif name == "tx_enabled":
            if cfg.get("tx_enabled"):
                self.save_config(tx_enabled=False)
                return self.toast("Transmit off  ·  receive only")
            return self.offer_transmit()
        elif name in ("wardrive_wifi_ble", "wigle_random_ble"):
            default = name == "wardrive_wifi_ble"
            if self.recon is not None and self.recon.state == "running" and name == "wigle_random_ble":
                return self.toast("Stop scanning to change the WiGLE log", AMBER)
            return self.save_config(**{name: not cfg.get(name, default)})
        elif name == "update_check_start":
            return self.save_config(update_check_start=not cfg.get(name, True))
        elif name in ("recon_wifi", "recon_ble", "recon_sound"):
            if self.recon.state == "running" and name != "recon_sound":
                return self.toast("Stop Recon to change scanners", AMBER)
            return self.save_config(**{name: not cfg.get(name, True)})
        elif name in ("node_name", "node_short"):
            if not cfg.get("node_number"):
                self.save_config(node_number=mesh_tx.new_node_number())
            number, current_name, current_short = self.engine.identity()
            title = "Your name on the mesh" if name == "node_name" else "Short name (up to 4)"
            return self.push(screens.TextInput(title, lambda v: self.save_config(**{name: v.strip()}),
                                               initial=current_name if name == "node_name" else current_short))
        elif name == "tx_power_dbm":
            cap = mesh_tx.region_limits(cfg.get("region"))[0]
            options = [(v, "%d dBm" % v, "%.0f mW%s" % (10 ** (v / 10), "" if v <= cap else " · capped"))
                       for v in (2, 5, 10, 14, 17, 20, 22)]
        elif name == "hop_limit":
            options = [(v, "%d hops" % v, "default" if v == 3 else "") for v in range(1, 8)]
        elif name in ("recon_display_min", "recon_alert_min"):
            options = [("low", "Weak indicators", "names, shared vendors"),
                       ("medium", "Medium evidence", "specific vendor/service"),
                       ("high", "Strong signatures", "only")]
        elif name == "serial_device":
            return self.push(screens.TextInput("Serial device", lambda v: self.save_config(serial_device=v),
                                               initial=cfg.get("serial_device") or "/dev/ttyACM0"))
        else:
            return
        self.push(screens.Picker(name_title(name), options, cfg.get(name),
                                 lambda value: self.save_config(**{name: value})))

    def add_key(self, field, name, key):
        keys = list(self.cfg.get(field, [])) + [{"name": name, "key": key.strip()}]
        if self.save_config(**{field: keys}):
            self.toast("Key added for %s" % name)

    def add_hashtag(self, tag):
        tag = tag.strip()
        tags = list(self.cfg.get("meshcore_hashtags", [])) + [tag if tag.startswith("#") else "#" + tag]
        if self.save_config(meshcore_hashtags=tags):
            self.toast("Hashtag channel added")

    def remove_key(self, field, kind, entry):
        if kind == "hashtag":
            self.save_config(meshcore_hashtags=[t for t in self.cfg.get("meshcore_hashtags", []) if t != entry])
        else:
            self.save_config(**{field: [k for k in self.cfg.get(field, []) if k != entry]})

    def export(self, path):
        try:
            if (Path(path) / "recon.jsonl").is_file() and not (Path(path) / "capture.sqlite3").is_file():
                files = export_recon(path)
            else:
                files = export_session(path)
        except (OSError, ValueError) as exc:
            self.toast("Export failed: %s" % exc, RED)
            return
        self.toast("Exported %d files to export/" % len(files))

    def delete_session(self, path):
        try:
            shutil.rmtree(path)
        except OSError:
            self.toast("Could not delete the session", RED)
            return
        self.session_cache(refresh=True)
        self.pop()
        self.toast("Session deleted")

    # -- drawing ---------------------------------------------------------
    def compose(self):
        c = Canvas()
        base = self.stack[-1]
        modal = isinstance(base, screens.Modal)
        under = next(s for s in reversed(self.stack) if not isinstance(s, screens.Modal))
        chrome = getattr(under, "chrome", True)
        if chrome:
            self.status_bar(c, under)
        under.render(c, self)
        if not isinstance(under, recon_screens.Recon) and not modal:
            recon_screens.alert_banner(c, self)
        if modal:
            shade = Image.new("RGBA", (W, H), (0, 0, 0, 170))
            c.image.paste(shade, (0, 0), shade)
            base.render(c, self)
        if chrome:
            self.footer(c, base)
        if self.toast_text and time.monotonic() < self.toast_until:
            f = font("bold", 10)
            tw = c.text_width(self.toast_text, f)
            width = min(W - 20, tw + 24)
            x0 = (W - width) // 2
            y0 = H - FOOTER_H - 24
            c.rect((x0, y0, x0 + width, y0 + 18), fill=SURFACE, outline=self.toast_color, radius=9)
            c.text_center(W // 2, y0 + 3, c.fit(self.toast_text, width - 16, f), f, self.toast_color)
        return c.image

    def status_bar(self, c, screen):
        mark = image("radio-mark.png", (9, 15))
        c.paste(mark, (5, 2))
        x = 18 + c.text((18, 2), "LORA TUNNEL", font("display", 12), GREEN)
        right = W - 5
        c.text_right(right, 4, time.strftime("%H:%M"), font("monob", 9), TEXT)
        right -= 36
        gps = self.engine.gps.snapshot()
        color = GREEN if gps["valid"] else (AMBER if gps["status"] == "stale" else FAINT)
        label = (str(gps.get("satellites") or "FIX") if gps["valid"] else "--")
        c.text_right(right, 4, label, font("monob", 9), color)
        right -= max(10, int(c.text_width(label, font("monob", 9)))) + 2
        icons.pin(c.draw, right - 10, 3, 11, color)
        right -= 18
        if self.recon.state == "running":
            summary = self.recon.summary()
            eye = RED if summary["strong"] or summary["following"] else AMBER if summary["flagged"] else GREEN
            if summary["flagged"]:
                c.text_right(right, 4, str(summary["flagged"]), font("monob", 9), eye)
                right -= int(c.text_width(str(summary["flagged"]), font("monob", 9))) + 2
            icons.eye(c.draw, right - 13, 3, 12, eye)
            right -= 18
        if self.cfg.get("tx_enabled"):
            f = font("monob", 7)
            c.rect((right - 17, 4, right - 1, 14), fill=(60, 44, 8), radius=3)
            c.text_center(right - 9, 5, "TX", f, AMBER)
            right -= 21
        if self.engine.state == "capturing":
            f = font("monob", 8)
            text = clock(self.engine.elapsed())
            width = int(c.text_width(text, f)) + 18
            c.rect((right - width, 3, right, 15), fill=(70, 12, 14), radius=6)
            blink = int(time.monotonic() * 2) % 2 == 0
            c.draw.ellipse((right - width + 5, 6, right - width + 11, 12), fill=RED if blink else (120, 30, 30))
            c.text((right - width + 14, 5), text, f, RED)
        c.line((0, STATUS_H, W, STATUS_H), fill=LINE)

    def footer(self, c, screen):
        y = H - FOOTER_H
        c.rect((0, y, W, H), fill=SURFACE)
        c.line((0, y, W, y), fill=LINE)
        x = 4
        for key, label in screen.hints(self):
            if x > W - 40:
                break
            x += c.keycap(x, y + 2, key, label)

    # -- loop --------------------------------------------------------------
    def first_run(self):
        if self._first_run_checked or isinstance(self.screen, screens.Splash):
            return
        self._first_run_checked = True
        if self._check_updates_on_start and self.cfg.get("update_check_start", True):
            self.updates.start()
        if not self.cfg.get("region"):
            self.pick_region()
            self.toast("Choose the LoRa region you're in", AMBER, 4)

    def announce_update(self):
        if self.updates.checking or self.updates.result is None:
            return
        version = self.updates.take_announcement()
        if version and not isinstance(self.screen, screens.Updates):
            self.toast("Update %s available  ·  Settings › Updates" % version, CYAN, 6)

    def step(self, timeout=0.05):
        screen = self.screen
        if isinstance(screen, screens.Splash) and screen.done():
            self.pop()
        self.first_run()
        self.announce_update()
        self.keyboard.text_mode = getattr(self.screen, "text_mode", False)
        for key in self.keyboard.poll(timeout):
            self.screen.handle(key, self)
            self.dirty = True

    def run(self):
        last_draw = 0.0
        try:
            while self.running:
                self.step(0.05)
                now = time.monotonic()
                interval = min(getattr(self.screen, "refresh", 1.0),
                               0.25 if self.engine.state == "capturing" else 1.0)
                if self.dirty or now - last_draw >= interval:
                    self.display.show(self.compose())
                    last_draw, self.dirty = now, False
        finally:
            self.recon.stop()
            self.engine.shutdown()


def name_title(name):
    return {"mode": "Scan mode", "preset": "Meshtastic preset", "slot": "Frequency slot",
            "meshcore_profile": "MeshCore profile", "dwell_seconds": "Dwell per profile",
            "survey_dwell_seconds": "Survey dwell", "backend": "Receiver", "tx_power_dbm": "Transmit power",
            "hop_limit": "Hop limit", "recon_display_min": "Show devices from",
            "recon_alert_min": "Alert from"}.get(name, name)
