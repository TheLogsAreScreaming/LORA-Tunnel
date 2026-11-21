"""Screens. Each draws into the content area and handles logical keys.

Shared keys everywhere: Esc/` goes back, arrows (or ; . , /) move, Enter opens.
"""

from datetime import datetime
import shutil
import time

from .. import __version__, config as configuration, profiles
from ..store import list_sessions
from . import icons
from .gfx import (AMBER, BG, CONTENT_BOTTOM, CONTENT_TOP, CYAN, FAINT, GREEN, GREEN_DIM, GREEN_INK,
                  H, LINE, MUTED, PROTOCOL_COLOR, RED, SURFACE, SURFACE_2, TEXT, W, ago, bearing,
                  clock, compass, distance_m, font, human_distance, image, rssi_color)

TOP = CONTENT_TOP + 3


class Screen:
    title = ""
    refresh = 1.0        # seconds between redraws while idle

    def hints(self, app):
        return [("Esc", "Back")]

    def render(self, c, app):
        raise NotImplementedError

    def handle(self, key, app):
        if key in ("ESC", "BACKSPACE"):
            app.pop()
            return True
        return False


class ListMixin:
    """Cursor and scroll handling for vertical lists."""

    index = 0
    top = 0

    def move(self, key, count, visible):
        if not count:
            return False
        step = {"UP": -1, "DOWN": 1, "PAGEUP": -visible, "PAGEDOWN": visible}.get(key.name)
        if step is None:
            return False
        self.index = max(0, min(count - 1, self.index + step)) if abs(step) > 1 else (self.index + step) % count
        self.clamp(count, visible)
        return True

    def clamp(self, count, visible):
        self.index = max(0, min(self.index, max(0, count - 1)))
        if self.index < self.top:
            self.top = self.index
        if self.index >= self.top + visible:
            self.top = self.index - visible + 1
        self.top = max(0, min(self.top, max(0, count - visible)))

    def scrollbar(self, c, count, visible, x=W - 4, y0=TOP, y1=CONTENT_BOTTOM - 2):
        if count <= visible:
            return
        c.rect((x, y0, x + 1, y1), fill=LINE)
        span = y1 - y0
        h = max(8, span * visible // count)
        y = y0 + (span - h) * self.top // max(1, count - visible)
        c.rect((x - 1, y, x + 2, y + h), fill=MUTED, radius=1)


def empty_state(c, icon, title, detail):
    icons.ICONS[icon](c.draw, W // 2 - 14, 46, 28, LINE)
    c.text_center(W // 2, 84, title, font("bold", 12), TEXT)
    for i, line in enumerate(c.wrap(detail, 260, font("ui", 10))[:3]):
        c.text_center(W // 2, 102 + i * 13, line, font("ui", 10), MUTED)


def fmt_time(stamp):
    try:
        return datetime.fromtimestamp(stamp).strftime("%H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return "--:--:--"


def fmt_rssi(value):
    return "—" if value is None else "%d" % round(value)


# ---------------------------------------------------------------- splash
class Splash(Screen):
    chrome = False
    refresh = 0.1

    def __init__(self, seconds=1.6):
        self.until = time.monotonic() + seconds

    def hints(self, app):
        return []

    def render(self, c, app):
        logo = image("logo.png", (130, 118))
        c.paste(logo, ((W - logo.width) // 2, 10))
        c.text_center(W // 2, 134, "LoRa mesh wardriving  ·  Meshtastic  ·  MeshCore", font("ui", 9), MUTED)
        c.text((6, 155), "v" + __version__, font("mono", 9), FAINT)
        c.text_right(W - 6, 155, "VALLEYTECH SOLUTIONS", font("bold", 8), FAINT)

    def handle(self, key, app):
        self.until = 0
        return True

    def done(self):
        return time.monotonic() >= self.until


# ---------------------------------------------------------------- home
class Home(Screen):
    title = "HOME"
    TILES = [
        ("W", "Wardrive", "radio"),
        ("N", "Nodes", "nodes"),
        ("M", "Messages", "chat"),
        ("P", "Packets", "scan"),
        ("S", "Sessions", "folder"),
        ("C", "Settings", "sliders"),
    ]

    def __init__(self):
        self.index = 0

    def hints(self, app):
        return [("Enter", "Open"), ("Space", "Start/Stop"), ("W N M P S C", "Jump")]

    def subtitle(self, label, app):
        e = app.engine
        if label == "Wardrive":
            if e.state == "capturing":
                return "REC %s" % clock(e.elapsed())
            region = app.cfg.get("region")
            return ("Ready · " + region) if region else "Pick a region"
        if label == "Nodes":
            return "%d heard" % len(e.nodes)
        if label == "Messages":
            return "%d heard" % len(e.messages)
        if label == "Packets":
            return "%d saved" % e.counters.get("saved", 0) if e.counters else "None yet"
        if label == "Sessions":
            return "%d saved" % len(app.session_cache())
        if label == "Settings":
            return profiles.MODE_LABELS.get(app.cfg.get("mode"), "")
        return ""

    def render(self, c, app):
        tw, th, gap, x0, y0 = 101, 63, 4, 4, TOP
        for i, (key, label, icon) in enumerate(self.TILES):
            col, row = i % 3, i // 3
            x, y = x0 + col * (tw + gap), y0 + row * (th + gap)
            selected = i == self.index
            live = label == "Wardrive" and app.engine.state == "capturing"
            c.rect((x, y, x + tw, y + th), fill=SURFACE_2 if selected else SURFACE,
                   outline=GREEN if selected else LINE, radius=6, width=1)
            color = RED if live else (GREEN if selected else TEXT)
            icons.ICONS["record" if live else icon](c.draw, x + 8, y + 8, 20, color)
            c.text((x + tw - 8, y + 7), key, font("monob", 9), FAINT if not selected else GREEN, anchor="ra")
            c.text((x + 8, y + 33), label, font("bold", 12), TEXT)
            c.text((x + 8, y + 49), self.subtitle(label, app), font("mono", 9),
                   RED if live else MUTED, width=tw - 14)

    def handle(self, key, app):
        if key.name in ("LEFT", "RIGHT"):
            self.index = (self.index + (1 if key == "RIGHT" else -1)) % 6
        elif key.name in ("UP", "DOWN"):
            self.index = (self.index + 3) % 6
        elif key == "ENTER":
            app.open(self.TILES[self.index][1])
        elif key == "SPACE":
            app.toggle_capture()
        elif key.name in [t[0] for t in self.TILES]:
            app.open(next(t[1] for t in self.TILES if t[0] == key.name))
        elif key in ("ESC", "BACKSPACE", "Q"):
            app.confirm("Quit LORA Tunnel?", "Capture stops and the session is saved." if
                        app.engine.state == "capturing" else "See you on the air.", "Quit", app.quit)
        else:
            return False
        return True


# ---------------------------------------------------------------- wardrive
class Wardrive(Screen):
    title = "WARDRIVE"
    refresh = 0.25

    def hints(self, app):
        if app.engine.state == "capturing":
            hints = [("Space", "Stop")]
            if len(app.engine.plan) > 1:
                hints.append(("←→", "Hop"))
            return hints + [("N", "Nodes"), ("P", "Packets"), ("Esc", "Home")]
        return [("Space", "Start"), ("R", "Region"), ("M", "Mode"), ("Esc", "Home")]

    def render(self, c, app):
        if app.engine.state == "capturing":
            self.live(c, app)
        else:
            self.ready(c, app)

    def ready(self, c, app):
        cfg, e = app.cfg, app.engine
        y = TOP
        if e.error:
            c.rect((4, y, W - 4, y + 26), fill=(60, 14, 16), outline=RED, radius=5)
            c.text((12, y + 3), "Capture stopped", font("bold", 10), RED)
            c.text((12, y + 14), e.error, font("ui", 9), TEXT, width=W - 24)
            y += 30
        c.rect((4, y, W - 4, CONTENT_BOTTOM - 30), fill=SURFACE, radius=6)
        rows = []
        try:
            plan = profiles.scan_plan(cfg)
            names = ", ".join(p.short for p in plan[:3]) + (" +%d" % (len(plan) - 3) if len(plan) > 3 else "")
            rows.append(("Listen", names, TEXT))
            first = plan[0]
            rows.append(("First", "%.4f MHz  SF%d  %gk" % (first.frequency_mhz, first.spreading_factor,
                                                         first.bandwidth_hz / 1000), TEXT))
            if len(plan) > 1:
                rows.append(("Dwell", "%gs per profile, %d profiles" % (plan[0].dwell_seconds, len(plan)), TEXT))
        except ValueError as exc:
            rows.append(("Radio", str(exc), AMBER))
        region = profiles.REGIONS.get(cfg.get("region"))
        rows.insert(0, ("Region", region.label if region else "Not set", TEXT if region else AMBER))
        rows.append(("Receiver", {"cap": "Cap LoRa-1262", "lorapipe": "LoRaPipe serial",
                                  "demo": "Demo (synthetic)"}[cfg.get("backend", "cap")], TEXT))
        gps = e.gps.snapshot()
        rows.append(("GPS", gps_text(gps), GREEN if gps["valid"] else AMBER))
        try:
            free = shutil.disk_usage(app.data_root()).free if app.data_root().exists() else \
                shutil.disk_usage(app.data_root().parent).free
            rows.append(("Storage", "%.1f GB free" % (free / 1e9), TEXT))
        except OSError:
            rows.append(("Storage", "Unavailable", AMBER))
        for i, (label, value, color) in enumerate(rows[:7 if not e.error else 5]):
            yy = y + 6 + i * 13
            c.text((12, yy), label, font("ui", 9), MUTED)
            c.text((70, yy), value, font("mono", 9), color, width=W - 84)
        by = CONTENT_BOTTOM - 25
        ready = region is not None
        c.rect((4, by, W - 4, CONTENT_BOTTOM - 3), fill=GREEN if ready else SURFACE_2, radius=6)
        label = "SPACE  ·  START CAPTURE" if ready else "PRESS R TO CHOOSE YOUR REGION"
        c.text_center(W // 2, by + 6, label, font("display", 11), GREEN_INK if ready else AMBER)

    def live(self, c, app):
        e = app.engine
        p = e.active
        y = TOP
        c.rect((4, y, W - 4, y + 22), fill=SURFACE, radius=5)
        c.badge(10, y + 5, p.protocol)
        c.text((34, y + 4), p.label, font("bold", 11), TEXT)
        lw = c.text_width(p.label, font("bold", 11))
        c.text((40 + lw, y + 6), "%.4f MHz  SF%d  %gk" % (p.frequency_mhz, p.spreading_factor, p.bandwidth_hz / 1000),
               font("mono", 9), MUTED)
        remaining = e.dwell_remaining()
        if remaining is not None:
            c.text_right(W - 10, y + 6, "%d/%d  %ds" % (e.plan_index + 1, len(e.plan), remaining), font("mono", 9), MUTED)
            c.progress((8, y + 19, W - 8, y + 20), 1 - remaining / p.dwell_seconds, fg=PROTOCOL_COLOR[p.protocol])
        else:
            c.text_right(W - 10, y + 6, "LOCKED", font("monob", 9), GREEN_DIM)
        y += 26
        n = e.counters
        decoded = "%d%%" % (100 * n["decoded"] / n["saved"]) if n.get("saved") else "—"
        last = e.recent[0] if e.recent else None
        metrics = [("PACKETS", str(n.get("saved", 0)), TEXT), ("NODES", str(len(e.nodes)), TEXT),
                   ("DECODED", decoded, TEXT),
                   ("LAST RSSI", fmt_rssi(last["rssi"]) if last else "—", rssi_color(last["rssi"]) if last else FAINT)]
        cw = (W - 8 - 9) / 4
        for i, (label, value, color) in enumerate(metrics):
            x = 4 + i * (cw + 3)
            c.rect((x, y, x + cw, y + 33), fill=SURFACE, radius=5)
            c.text((x + 7, y + 4), label, font("bold", 7), MUTED)
            c.text((x + 7, y + 13), value, font("display", 16), color)
        y += 37
        gh = 34
        c.rect((4, y, W - 4, y + gh), fill=SURFACE, radius=5)
        counts, best = e.activity(48)
        peak = max(counts) or 1
        bw = (W - 24) / len(counts)
        for i, count in enumerate(counts):
            if not count:
                c.rect((12 + i * bw, y + gh - 7, 12 + i * bw + bw - 2, y + gh - 6), fill=LINE)
                continue
            h = max(3, (gh - 12) * count / peak)
            c.rect((12 + i * bw, y + gh - 6 - h, 12 + i * bw + bw - 2, y + gh - 6), fill=rssi_color(best[i]))
        c.text((10, y + 3), "ACTIVITY  ·  LAST 2 MIN  ·  PEAK %d/2.5s" % peak if any(counts) else "ACTIVITY  ·  LAST 2 MIN",
               font("bold", 7), FAINT)
        y += gh + 4
        if last:
            draw_packet_row(c, y, last, selected=False, show_time=False)
        else:
            c.text_center(W // 2, y + 3, "Listening… packets appear here as they arrive", font("ui", 9), MUTED)
        if e.counters.get("queue_drops") or e.counters.get("write_errors"):
            c.text_right(W - 8, CONTENT_BOTTOM - 10, "drops %d  errors %d" % (n["queue_drops"], n["write_errors"]),
                         font("mono", 8), AMBER)

    def handle(self, key, app):
        e = app.engine
        if key == "SPACE":
            app.toggle_capture()
        elif key.name in ("LEFT", "RIGHT") and e.state == "capturing":
            e.hop(1 if key == "RIGHT" else -1)
        elif key == "N":
            app.open("Nodes")
        elif key == "P":
            app.open("Packets")
        elif key == "R" and e.state != "capturing":
            app.pick_region()
        elif key == "M" and e.state != "capturing":
            app.pick_setting("mode")
        else:
            return super().handle(key, app)
        return True


def gps_text(gps):
    if gps["valid"]:
        sats = gps.get("satellites")
        return "FIX" + (" %d sat" % sats if sats else "")
    if gps["status"] == "stale":
        return "GPS stale"
    return "No GPS fix"


def draw_packet_row(c, y, item, selected, show_time=True, width=W):
    if selected:
        c.rect((4, y, width - 8, y + 15), fill=SURFACE_2, radius=3)
        c.rect((4, y + 2, 5, y + 13), fill=GREEN)
    x = 9
    if show_time:
        c.text((x, y + 3), fmt_time(item["time"]), font("mono", 8), FAINT)
        x += 44
    x += c.badge(x, y + 2, item["protocol"])
    c.text((x + 2, y + 2), item["from"], font("ui", 10), TEXT, width=78)
    status = item["status"]
    detail = item["text"] or (item["kind"] if status == "decoded" else status.replace("_", " "))
    color = TEXT if item["text"] else (MUTED if status == "decoded" else AMBER if status != "header_only" else MUTED)
    c.text((x + 84, y + 3), detail, font("mono", 9), color, width=width - x - 84 - 62)
    c.text_right(width - 12, y + 3, fmt_rssi(item["rssi"]) + " dBm", font("mono", 9), rssi_color(item["rssi"]))


# ---------------------------------------------------------------- packets
class Packets(Screen, ListMixin):
    title = "PACKETS"
    refresh = 0.5
    VISIBLE = 8

    def __init__(self):
        self.index = self.top = 0
        self.follow = True

    def hints(self, app):
        return [("Enter", "Details"), ("F", "Follow " + ("on" if self.follow else "off")), ("Esc", "Back")]

    def render(self, c, app):
        items = list(app.engine.recent)
        if not items:
            empty_state(c, "scan", "No packets yet", "Start Wardrive and every frame shows here, decoded or not.")
            return
        if self.follow:
            self.index = self.top = 0
        self.clamp(len(items), self.VISIBLE)
        for row, item in enumerate(items[self.top:self.top + self.VISIBLE]):
            draw_packet_row(c, TOP + row * 16, item, self.top + row == self.index)
        self.scrollbar(c, len(items), self.VISIBLE)

    def handle(self, key, app):
        items = list(app.engine.recent)
        if self.move(key, len(items), self.VISIBLE):
            self.follow = self.index == 0
        elif key == "ENTER" and items:
            app.push(PacketDetail(items[self.index]))
        elif key == "F":
            self.follow = not self.follow
        else:
            return super().handle(key, app)
        return True


class Details(Screen, ListMixin):
    """Scrollable label/value list used for packets, nodes and sessions."""

    VISIBLE = 10

    def __init__(self, title):
        self.title = title
        self.index = self.top = 0

    def rows(self, app):
        return []

    def hints(self, app):
        return [("↑↓", "Scroll"), ("Esc", "Back")]

    def render(self, c, app):
        rows = self.layout(c, app)
        self.top = max(0, min(self.top, max(0, len(rows) - self.VISIBLE)))
        for i, (label, value, color) in enumerate(rows[self.top:self.top + self.VISIBLE]):
            y = TOP + i * 13
            if label:
                c.text((8, y), label, font("ui", 9), MUTED)
            c.text((78 if label else 8, y), value, font("mono", 9), color, width=W - (90 if label else 20))
        self.index = self.top
        self.scrollbar(c, len(rows), self.VISIBLE)

    def layout(self, c, app):
        out = []
        for label, value, *rest in self.rows(app):
            color = rest[0] if rest else TEXT
            width = W - (90 if label else 20)
            lines = c.wrap(str(value), width, font("mono", 9)) or [""]
            out.append((label, lines[0], color))
            out.extend(("", line, color) for line in lines[1:])
        return out

    def handle(self, key, app):
        if key.name in ("UP", "DOWN", "PAGEUP", "PAGEDOWN"):
            step = {"UP": -1, "DOWN": 1, "PAGEUP": -self.VISIBLE, "PAGEDOWN": self.VISIBLE}[key.name]
            self.top = max(0, self.top + step)
            return True
        return super().handle(key, app)


class PacketDetail(Details):
    def __init__(self, item):
        super().__init__("PACKET")
        self.item = item

    def rows(self, app):
        record = self.item["record"]
        d = record.get("decoded", {})
        p = record.get("profile", {})
        gps = record.get("receiver_gps") or {}
        rows = [("Time", datetime.fromtimestamp(record["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")),
                ("Protocol", "%s  ·  %s" % (d.get("protocol", "unknown"), d.get("decode_status", "raw")),
                 PROTOCOL_COLOR.get(d.get("protocol"), MUTED)),
                ("Type", d.get("port_name") or d.get("payload_name") or "—")]
        for label, key in (("From", "source_id"), ("To", "destination_id"), ("Channel", "channel_name"),
                           ("Name", "name"), ("Short", "short_name"), ("Role", "node_type"),
                           ("Packet ID", "packet_id"), ("Route", "route_name"), ("Path", "path_hex")):
            if d.get(key) not in (None, ""):
                rows.append((label, d[key]))
        if "hop_start" in d:
            rows.append(("Hops", "%d of %d used" % (d["hop_start"] - d.get("hop_limit", 0), d["hop_start"])))
        if d.get("text"):
            rows.append(("Text", d["text"], GREEN))
        if d.get("node_position"):
            pos = d["node_position"]
            rows.append(("Advertised", "%.5f, %.5f" % (pos["latitude"], pos["longitude"])))
        if d.get("telemetry"):
            rows.append(("Telemetry", ", ".join("%s %s" % (k.replace("_", " "), round(v, 2))
                                                for k, v in d["telemetry"].items())))
        if "signature_valid" in d:
            rows.append(("Signature", {True: "valid", False: "INVALID", None: "unchecked"}[d["signature_valid"]],
                         GREEN if d["signature_valid"] else RED))
        rows += [("Signal", "%s dBm  SNR %s dB" % (fmt_rssi(record.get("rssi_dbm")), record.get("snr_db")),
                  rssi_color(record.get("rssi_dbm"))),
                 ("Radio", "%.4f MHz BW%gk SF%s CR4/%s sync 0x%02x" % (
                     p.get("frequency_hz", 0) / 1e6, p.get("bandwidth_hz", 0) / 1000, p.get("spreading_factor"),
                     p.get("coding_rate"), p.get("sync_word", 0))),
                 ("Receiver", "%.5f, %.5f" % (gps["latitude"], gps["longitude"]) if gps.get("valid") else "no fix",
                  TEXT if gps.get("valid") else MUTED),
                 ("Raw", "%d bytes" % (len(record["raw_hex"]) // 2)),
                 ("", " ".join(record["raw_hex"][i:i + 2] for i in range(0, len(record["raw_hex"]), 2)), MUTED)]
        if record.get("synthetic"):
            rows.insert(0, ("Note", "Synthetic demo packet", AMBER))
        return rows


# ---------------------------------------------------------------- nodes
class Nodes(Screen, ListMixin):
    title = "NODES"
    refresh = 1.0
    VISIBLE = 7
    SORTS = ("recent", "signal", "count")

    def __init__(self):
        self.index = self.top = 0
        self.sort = 0

    def hints(self, app):
        return [("Enter", "Details"), ("S", "Sort: " + self.SORTS[self.sort]), ("Esc", "Back")]

    def render(self, c, app):
        nodes = app.engine.node_list(self.SORTS[self.sort])
        if not nodes:
            empty_state(c, "nodes", "No nodes identified yet",
                        "Meshtastic nodes appear when heard. MeshCore nodes appear after a signed advert.")
            return
        mt = sum(1 for n in nodes if n["protocol"] == "meshtastic")
        c.text((8, TOP - 1), "%d nodes  ·  %d Meshtastic  ·  %d MeshCore" % (len(nodes), mt, len(nodes) - mt),
               font("ui", 9), MUTED)
        self.clamp(len(nodes), self.VISIBLE)
        now = time.time()
        for row, node in enumerate(nodes[self.top:self.top + self.VISIBLE]):
            y = TOP + 13 + row * 16
            if self.top + row == self.index:
                c.rect((4, y, W - 8, y + 15), fill=SURFACE_2, radius=3)
                c.rect((4, y + 2, 5, y + 13), fill=GREEN)
            x = 9 + c.badge(9, y + 2, node["protocol"])
            name = node.get("name") or node.get("short_name") or node["id"][:12]
            c.text((x + 2, y + 2), name, font("ui", 10), TEXT, width=110)
            c.text((x + 116, y + 3), node.get("short_name") or node["id"][-6:], font("mono", 8), FAINT, width=40)
            c.signal_bars(W - 104, y + 3, node.get("rssi"))
            c.text_right(W - 58, y + 3, fmt_rssi(node.get("rssi")), font("mono", 9), rssi_color(node.get("rssi")))
            c.text_right(W - 36, y + 3, "×%d" % node["count"], font("mono", 9), MUTED)
            c.text_right(W - 12, y + 3, ago(now - node.get("last_seen", now)), font("mono", 9), MUTED)
        self.scrollbar(c, len(nodes), self.VISIBLE, y0=TOP + 13)

    def handle(self, key, app):
        nodes = app.engine.node_list(self.SORTS[self.sort])
        if self.move(key, len(nodes), self.VISIBLE):
            pass
        elif key == "S":
            self.sort = (self.sort + 1) % len(self.SORTS)
            self.index = self.top = 0
        elif key == "ENTER" and nodes:
            app.push(NodeDetail(nodes[self.index]["protocol"], nodes[self.index]["id"]))
        else:
            return super().handle(key, app)
        return True


class NodeDetail(Details):
    refresh = 1.0

    def __init__(self, protocol, node_id):
        super().__init__("NODE")
        self.key = (protocol, node_id)

    def rows(self, app):
        node = app.engine.nodes.get(self.key)
        if node is None:
            return [("", "This node is no longer in the live table.", MUTED)]
        now = time.time()
        rows = [("Name", node.get("name") or "—", TEXT),
                ("Protocol", node["protocol"], PROTOCOL_COLOR.get(node["protocol"], MUTED)),
                ("ID", node["id"])]
        for label, key in (("Short", "short_name"), ("Role", "node_type"), ("Hardware", "hardware_model")):
            if node.get(key) not in (None, ""):
                rows.append((label, node[key]))
        rows += [("Signal", "%s dBm now, best %s dBm, SNR %s" % (fmt_rssi(node.get("rssi")),
                                                                fmt_rssi(node.get("best_rssi")), node.get("snr")),
                  rssi_color(node.get("rssi"))),
                 ("Heard", "%d packets, last %s ago, first %s ago" % (node["count"], ago(now - node["last_seen"]),
                                                                     ago(now - node["first_seen"]))),
                 ("Profile", node.get("profile") or "—")]
        if "hops" in node:
            rows.append(("Hops away", str(node["hops"]), TEXT if node["hops"] else GREEN))
        position = node.get("position")
        if position:
            rows.append(("Advertised", "%.5f, %.5f" % (position["latitude"], position["longitude"])))
            gps = app.engine.gps.snapshot()
            if gps["valid"]:
                here = (gps["latitude"], gps["longitude"])
                there = (position["latitude"], position["longitude"])
                rows.append(("Distance", "%s %s (claimed position)" % (
                    human_distance(distance_m(here, there)), compass(bearing(here, there))), CYAN))
        if node.get("best_fix"):
            rows.append(("Best RX at", "%.5f, %.5f" % node["best_fix"]))
        telemetry = node.get("telemetry") or {}
        if "battery_percent" in telemetry:
            rows.append(("Battery", "%d%%%s" % (telemetry["battery_percent"],
                                               "  %.2f V" % telemetry["voltage"] if "voltage" in telemetry else "")))
        if "channel_utilization" in telemetry:
            rows.append(("Ch. util", "%.1f%%  airtime %.1f%%" % (telemetry["channel_utilization"],
                                                                 telemetry.get("air_util_tx", 0))))
        for text in list(node.get("texts", []))[:4]:
            rows.append(("Said", text, GREEN))
        return rows


# ---------------------------------------------------------------- messages
class Messages(Screen):
    title = "MESSAGES"
    refresh = 1.0

    def __init__(self):
        self.top = 0

    def hints(self, app):
        return [("↑↓", "Scroll"), ("Esc", "Back")]

    def render(self, c, app):
        items = list(app.engine.messages)
        if not items:
            empty_state(c, "chat", "No channel messages heard",
                        "Text on channels you hold keys for (default keys included) shows here as it's heard.")
            return
        self.top = max(0, min(self.top, len(items) - 1))
        y = TOP
        now = time.time()
        for item in items[self.top:]:
            lines = c.wrap(item["text"], W - 30, font("ui", 10))[:3]
            height = 14 + len(lines) * 12
            if y + height > CONTENT_BOTTOM:
                break
            color = PROTOCOL_COLOR.get(item["protocol"], MUTED)
            c.rect((4, y, W - 8, y + height - 3), fill=SURFACE, radius=5)
            c.rect((4, y + 3, 5, y + height - 6), fill=color)
            c.text((12, y + 2), item["from"], font("bold", 9), color, width=120)
            c.text_right(W - 14, y + 2, "%s · %s ago · %s dBm" % (item["channel"], ago(now - item["time"]),
                                                                 fmt_rssi(item["rssi"])), font("mono", 8), FAINT)
            for i, line in enumerate(lines):
                c.text((12, y + 13 + i * 12), line, font("ui", 10), TEXT)
            y += height
        if len(items) > 1:
            c.text_right(W - 10, CONTENT_BOTTOM - 10, "%d/%d" % (self.top + 1, len(items)), font("mono", 8), FAINT)

    def handle(self, key, app):
        if key in ("UP", "DOWN"):
            self.top = max(0, min(len(app.engine.messages) - 1, self.top + (1 if key == "DOWN" else -1)))
            return True
        return super().handle(key, app)


# ---------------------------------------------------------------- sessions
class Sessions(Screen, ListMixin):
    title = "SESSIONS"
    VISIBLE = 8
    refresh = 2.0

    def __init__(self):
        self.index = self.top = 0

    def hints(self, app):
        return [("Enter", "Open"), ("Esc", "Back")]

    def render(self, c, app):
        sessions = app.session_cache(refresh=True)
        if not sessions:
            empty_state(c, "folder", "No sessions yet", "Each Wardrive run is saved to ~/LoRaTunnel/sessions.")
            return
        self.clamp(len(sessions), self.VISIBLE)
        for row, (path, meta) in enumerate(sessions[self.top:self.top + self.VISIBLE]):
            y = TOP + row * 16
            if self.top + row == self.index:
                c.rect((4, y, W - 8, y + 15), fill=SURFACE_2, radius=3)
                c.rect((4, y + 2, 5, y + 13), fill=GREEN)
            started = datetime.fromtimestamp(meta.get("started_at") or meta.get("created_at", 0))
            c.text((10, y + 2), started.strftime("%b %d  %H:%M"), font("ui", 10), TEXT)
            status = meta.get("status", "?")
            color = {"closed": GREEN_DIM, "capturing": RED, "interrupted": AMBER}.get(status, FAINT)
            c.pill(96, y + 2, status.upper(), font("bold", 7), BG if status != "closed" else GREEN, color, height=11)
            counters = meta.get("counters", {})
            c.text_right(W - 70, y + 3, "%d pkts" % counters.get("saved", 0), font("mono", 9), MUTED)
            c.text_right(W - 14, y + 3, "%d nodes" % meta.get("nodes", 0), font("mono", 9), MUTED)
        self.scrollbar(c, len(sessions), self.VISIBLE)

    def handle(self, key, app):
        sessions = app.session_cache()
        if self.move(key, len(sessions), self.VISIBLE):
            return True
        if key == "ENTER" and sessions:
            app.push(SessionDetail(*sessions[self.index]))
            return True
        return super().handle(key, app)


class SessionDetail(Details):
    def __init__(self, path, meta):
        super().__init__("SESSION")
        self.path, self.meta = path, meta

    def hints(self, app):
        return [("E", "Export"), ("D", "Delete"), ("Esc", "Back")]

    def rows(self, app):
        m = self.meta
        counters = m.get("counters", {})
        start, end = m.get("started_at"), m.get("ended_at")
        rows = [("Folder", self.path.name),
                ("Status", m.get("status", "?"), GREEN if m.get("status") == "closed" else AMBER),
                ("Started", datetime.fromtimestamp(start).strftime("%Y-%m-%d %H:%M:%S") if start else "—"),
                ("Duration", clock(end - start) if start and end else "—"),
                ("Region", "%s  ·  %s" % (m.get("region", "—"), profiles.MODE_LABELS.get(m.get("mode"), "—"))),
                ("Packets", "%d saved, %d decoded, %d encrypted" % (counters.get("saved", 0),
                                                                    counters.get("decoded", 0),
                                                                    counters.get("encrypted", 0))),
                ("Nodes", str(m.get("nodes", 0))),
                ("Profiles", ", ".join(p.get("id", "") for p in m.get("profiles", [])))]
        for error in m.get("errors", []):
            rows.append(("Error", error, AMBER))
        rows.append(("Files", "observations.jsonl, capture.sqlite3, lora.pcap (LoRaTAP)", MUTED))
        if (self.path / "export").is_dir():
            rows.append(("Exported", "export/nodes.csv, nodes.kml, packets.csv", GREEN))
        return rows

    def handle(self, key, app):
        if key == "E":
            app.export(self.path)
        elif key == "D":
            if app.engine.directory and app.engine.directory == self.path and app.engine.state == "capturing":
                app.toast("Stop capture before deleting this session", AMBER)
            else:
                app.confirm("Delete this session?", "All files in %s are removed." % self.path.name, "Delete",
                            lambda: app.delete_session(self.path))
        else:
            return super().handle(key, app)
        return True


# ---------------------------------------------------------------- settings
class Settings(Screen, ListMixin):
    title = "SETTINGS"
    VISIBLE = 9

    def __init__(self):
        self.index = self.top = 0

    def items(self, app):
        cfg = app.cfg
        region = profiles.REGIONS.get(cfg.get("region"))
        mc = profiles.meshcore(cfg.get("region"), cfg.get("meshcore_profile", "AUTO")) if region else None
        preset = profiles.PRESETS[cfg.get("preset", "LONG_FAST")]
        items = [
            ("region", "Region", region.label if region else "Not set"),
            ("mode", "Scan mode", profiles.MODE_LABELS[cfg.get("mode", "meshtastic")]),
            ("preset", "Meshtastic preset", preset.name),
            ("slot", "Frequency slot", "Default" if not cfg.get("slot") else str(cfg["slot"])),
            ("meshcore_profile", "MeshCore profile",
             (mc.label if mc else "None in band") + (" (auto)" if cfg.get("meshcore_profile") == "AUTO" else "")),
            ("dwell_seconds", "Dwell per profile", "%gs" % cfg.get("dwell_seconds", 30)),
            ("survey_dwell_seconds", "Survey dwell", "%gs" % cfg.get("survey_dwell_seconds", 15)),
            ("backend", "Receiver", {"cap": "Cap LoRa-1262", "lorapipe": "LoRaPipe serial",
                                     "demo": "Demo"}[cfg.get("backend", "cap")]),
        ]
        if cfg.get("backend") == "lorapipe":
            items.append(("serial_device", "Serial device", cfg.get("serial_device") or "Not set"))
        items += [
            ("decode_public", "Default channel keys", "On" if cfg.get("decode_public", True) else "Off"),
            ("meshtastic_keys", "Meshtastic keys", "%d added" % len(cfg.get("meshtastic_keys", []))),
            ("meshcore_keys", "MeshCore keys", "%d added" % (len(cfg.get("meshcore_keys", []))
                                                            + len(cfg.get("meshcore_hashtags", [])))),
            ("about", "About", "v" + __version__),
        ]
        return items

    def hints(self, app):
        return [("Enter", "Change"), ("Esc", "Back")]

    def render(self, c, app):
        items = self.items(app)
        self.clamp(len(items), self.VISIBLE)
        locked = app.engine.state == "capturing"
        for row, (key, label, value) in enumerate(items[self.top:self.top + self.VISIBLE]):
            y = TOP + row * 15
            selected = self.top + row == self.index
            if selected:
                c.rect((4, y - 1, W - 8, y + 13), fill=SURFACE_2, radius=3)
                c.rect((4, y + 1, 5, y + 11), fill=GREEN)
            c.text((11, y), label, font("ui", 10), TEXT if not locked or key == "about" else FAINT)
            c.text_right(W - 22, y + 1, value, font("mono", 9), GREEN if selected else MUTED)
            c.text((W - 18, y - 1), "›", font("bold", 11), FAINT)
        self.scrollbar(c, len(items), self.VISIBLE)
        if locked:
            c.text_center(W // 2, CONTENT_BOTTOM - 11, "Radio settings are locked while capturing", font("ui", 8), AMBER)

    def handle(self, key, app):
        items = self.items(app)
        if self.move(key, len(items), self.VISIBLE):
            return True
        if key == "ENTER":
            name = items[self.index][0]
            if name == "about":
                app.push(About())
            elif app.engine.state == "capturing":
                app.toast("Stop capture to change radio settings", AMBER)
            elif name in ("meshtastic_keys", "meshcore_keys"):
                app.push(KeyList(name))
            else:
                app.pick_setting(name)
            return True
        return super().handle(key, app)


class KeyList(Screen, ListMixin):
    VISIBLE = 8

    def __init__(self, field):
        self.field = field
        self.title = "MESHTASTIC KEYS" if field == "meshtastic_keys" else "MESHCORE KEYS"
        self.index = self.top = 0

    def entries(self, app):
        entries = [(k["name"], "key", k) for k in app.cfg.get(self.field, [])]
        if self.field == "meshcore_keys":
            entries += [(tag, "hashtag", tag) for tag in app.cfg.get("meshcore_hashtags", [])]
        return entries

    def hints(self, app):
        hints = [("A", "Add key")]
        if self.field == "meshcore_keys":
            hints.append(("H", "Add #tag"))
        return hints + [("D", "Remove"), ("Esc", "Back")]

    def render(self, c, app):
        entries = self.entries(app)
        if not entries:
            empty_state(c, "shield", "No private channels",
                        "Default channels decode automatically. Add a channel name and its base64 key to decode "
                        "private channels you belong to.")
            return
        self.clamp(len(entries), self.VISIBLE)
        for row, (name, kind, _) in enumerate(entries[self.top:self.top + self.VISIBLE]):
            y = TOP + row * 16
            if self.top + row == self.index:
                c.rect((4, y, W - 8, y + 15), fill=SURFACE_2, radius=3)
                c.rect((4, y + 2, 5, y + 13), fill=GREEN)
            c.text((11, y + 2), name, font("ui", 10), TEXT, width=180)
            c.text_right(W - 14, y + 3, "hashtag" if kind == "hashtag" else "key ••••", font("mono", 9), MUTED)

    def handle(self, key, app):
        entries = self.entries(app)
        if self.move(key, len(entries), self.VISIBLE):
            return True
        if key == "A":
            def got_name(name):
                app.push(TextInput("Channel key (base64)", lambda value: app.add_key(self.field, name, value),
                                   secret=True))
            app.push(TextInput("Channel name (exact)", got_name))
        elif key == "H" and self.field == "meshcore_keys":
            app.push(TextInput("Hashtag channel, e.g. #test", lambda value: app.add_hashtag(value)))
        elif key == "D" and entries:
            name, kind, entry = entries[self.index]
            app.confirm("Remove %s?" % name, "It will no longer be used for decoding.", "Remove",
                        lambda: app.remove_key(self.field, kind, entry))
        else:
            return super().handle(key, app)
        return True


class About(Screen):
    title = "ABOUT"

    def render(self, c, app):
        mark = image("radio-mark.png", (40, 66))
        c.paste(mark, (16, TOP + 6))
        c.text((70, TOP + 4), "LORA TUNNEL", font("display", 18), GREEN)
        c.text((70, TOP + 26), "for M5Stack CardputerZero  ·  v" + __version__, font("ui", 9), MUTED)
        lines = ["Receive-only LoRa mesh wardriving and decoding for",
                 "Meshtastic and MeshCore. Logs JSONL, SQLite and LoRaTAP",
                 "PCAP for Wireshark and Kismet-style analysis.",
                 "MIT licensed  ·  github.com/valleytechsolutions/LORA-Tunnel"]
        for i, line in enumerate(lines):
            c.text((70, TOP + 44 + i * 12), line, font("ui", 8), TEXT if i < 3 else FAINT)
        vts = image("vts.png", (28, 32))
        c.paste(vts, (W - 40, CONTENT_BOTTOM - 36))
        c.text_right(W - 46, CONTENT_BOTTOM - 22, "Valleytech Solutions", font("bold", 9), MUTED)


# ---------------------------------------------------------------- modals
class Modal(Screen):
    modal = True


class Picker(Modal, ListMixin):
    VISIBLE = 6

    def __init__(self, title, options, current=None, on_select=None):
        self.title = title
        self.options = options            # list of (value, label, detail)
        self.on_select = on_select
        self.index = next((i for i, o in enumerate(options) if o[0] == current), 0)
        self.top = 0
        self.clamp(len(options), self.VISIBLE)

    def hints(self, app):
        return [("Enter", "Select"), ("Esc", "Cancel")]

    def render(self, c, app):
        x0, y0, x1 = 28, 22, W - 28
        y1 = y0 + 26 + min(self.VISIBLE, len(self.options)) * 17
        c.rect((x0, y0, x1, y1), fill=SURFACE, outline=GREEN_DIM, radius=7)
        c.text((x0 + 10, y0 + 6), self.title, font("bold", 11), GREEN)
        for row, (value, label, detail) in enumerate(self.options[self.top:self.top + self.VISIBLE]):
            y = y0 + 23 + row * 17
            selected = self.top + row == self.index
            if selected:
                c.rect((x0 + 4, y, x1 - 4, y + 15), fill=GREEN, radius=4)
            c.text((x0 + 10, y + 2), label, font("ui", 10), GREEN_INK if selected else TEXT, width=140)
            if detail:
                c.text_right(x1 - 10, y + 3, detail, font("mono", 8), GREEN_INK if selected else MUTED)
        self.scrollbar(c, len(self.options), self.VISIBLE, x=x1 - 3, y0=y0 + 24, y1=y1 - 4)

    def handle(self, key, app):
        if self.move(key, len(self.options), self.VISIBLE):
            return True
        if key == "ENTER":
            app.pop()
            if self.on_select:
                self.on_select(self.options[self.index][0])
            return True
        return super().handle(key, app)


class Confirm(Modal):
    def __init__(self, title, detail, action, callback):
        self.title, self.detail, self.action, self.callback = title, detail, action, callback
        self.choice = 0

    def hints(self, app):
        return [("←→", "Choose"), ("Enter", "OK"), ("Esc", "Cancel")]

    def render(self, c, app):
        x0, y0, x1, y1 = 40, 36, W - 40, 132
        c.rect((x0, y0, x1, y1), fill=SURFACE, outline=LINE, radius=8)
        c.text((x0 + 12, y0 + 10), self.title, font("bold", 12), TEXT, width=x1 - x0 - 24)
        for i, line in enumerate(c.wrap(self.detail, x1 - x0 - 24, font("ui", 9))[:3]):
            c.text((x0 + 12, y0 + 30 + i * 12), line, font("ui", 9), MUTED)
        for i, label in enumerate(("Cancel", self.action)):
            bx = x0 + 12 + i * ((x1 - x0 - 30) // 2 + 6)
            bw = (x1 - x0 - 30) // 2
            selected = i == self.choice
            danger = i == 1 and self.action in ("Delete", "Remove", "Quit")
            fill = (RED if danger else GREEN) if selected else SURFACE_2
            c.rect((bx, y1 - 26, bx + bw, y1 - 9), fill=fill, radius=5)
            c.text_center(bx + bw // 2, y1 - 23, label, font("bold", 10), BG if selected else TEXT)

    def handle(self, key, app):
        if key.name in ("LEFT", "RIGHT", "TAB"):
            self.choice = 1 - self.choice
        elif key == "ENTER":
            app.pop()
            if self.choice == 1:
                self.callback()
        elif key == "Y":
            app.pop()
            self.callback()
        elif key in ("N", "ESC", "BACKSPACE"):
            app.pop()
        else:
            return False
        return True


class TextInput(Modal):
    """One-line entry using the physical keyboard."""

    text_mode = True

    def __init__(self, title, on_submit, secret=False, initial=""):
        self.title, self.on_submit, self.secret = title, on_submit, secret
        self.value = initial
        self.blink = time.monotonic()

    refresh = 0.5

    def hints(self, app):
        return [("Enter", "Save"), ("Esc", "Cancel"), ("Del", "Erase")]

    def render(self, c, app):
        x0, y0, x1, y1 = 16, 44, W - 16, 112
        c.rect((x0, y0, x1, y1), fill=SURFACE, outline=GREEN_DIM, radius=8)
        c.text((x0 + 12, y0 + 9), self.title, font("bold", 11), GREEN)
        c.rect((x0 + 10, y0 + 30, x1 - 10, y0 + 50), fill=BG, outline=LINE, radius=4)
        shown = ("•" * len(self.value)) if self.secret and len(self.value) > 0 else self.value
        shown = shown[-34:]
        w = c.text((x0 + 16, y0 + 34), shown, font("mono", 10), TEXT)
        if int((time.monotonic() - self.blink) * 2) % 2 == 0:
            c.rect((x0 + 17 + w, y0 + 34, x0 + 18 + w, y0 + 46), fill=GREEN)
        c.text_right(x1 - 12, y0 + 55, "%d chars" % len(self.value), font("mono", 8), FAINT)

    def handle(self, key, app):
        if key == "ENTER":
            app.pop()
            if self.value:
                self.on_submit(self.value)
        elif key == "ESC":
            app.pop()
        elif key.name in ("BACKSPACE", "DELETE"):
            self.value = self.value[:-1]
        elif key.char and len(self.value) < 64 and key.char.isprintable():
            self.value += key.char
        else:
            return False
        return True
