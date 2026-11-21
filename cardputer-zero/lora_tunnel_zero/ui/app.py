"""Navigation, chrome (status bar and key hints) and the main loop."""

import shutil
import time

from PIL import Image

from .. import RadioError, config as configuration, profiles
from ..export import export_session
from ..store import list_sessions
from . import icons, screens
from .gfx import (AMBER, BG, FAINT, FOOTER_H, GREEN, H, LINE, MUTED, RED, STATUS_H, SURFACE, TEXT, W,
                  Canvas, clock, font, image)


class App:
    def __init__(self, display, keyboard, engine, cfg, config_path=None, data_root=None, splash=True):
        self.display, self.keyboard, self.engine = display, keyboard, engine
        self.cfg = dict(cfg)
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
                   "Packets": screens.Packets, "Sessions": screens.Sessions, "Settings": screens.Settings}
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
        return True

    # -- actions ---------------------------------------------------------
    def toggle_capture(self):
        e = self.engine
        if e.state == "capturing":
            e.stop()
            self.session_cache(refresh=True)
            self.toast("Session saved  ·  %d packets" % e.counters.get("saved", 0) if not e.error
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
        if not isinstance(self.screen, screens.Wardrive):
            self.open("Wardrive")
        self.toast("Capture started", GREEN)

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
        if screen.title:
            c.text((x + 6, 5), screen.title, font("bold", 8), MUTED)
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
        if not self.cfg.get("region"):
            self.pick_region()
            self.toast("Choose the LoRa region you're in", AMBER, 4)

    def step(self, timeout=0.05):
        screen = self.screen
        if isinstance(screen, screens.Splash) and screen.done():
            self.pop()
        self.first_run()
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
            self.engine.shutdown()


def name_title(name):
    return {"mode": "Scan mode", "preset": "Meshtastic preset", "slot": "Frequency slot",
            "meshcore_profile": "MeshCore profile", "dwell_seconds": "Dwell per profile",
            "survey_dwell_seconds": "Survey dwell", "backend": "Receiver"}.get(name, name)
