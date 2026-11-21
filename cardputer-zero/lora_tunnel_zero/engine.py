"""Capture engine: radio, dwell scheduler, decoder, storage and live state for the UI.

Threads: one reads the radio and retunes on the dwell schedule, one reads GNSS,
and one decodes and writes. The UI only reads snapshots, so a slow screen never
stalls reception.
"""

from collections import deque
import queue
import shutil
import sqlite3
import threading
import time

from . import RadioError, config as configuration
from .decode import decode_packet
from .gnss import GPS
from .profiles import scan_plan
from .store import MIN_FREE_BYTES, Store, atomic_json, create_session, node_id, read_metadata

RECENT = 120
HISTORY_SECONDS = 120


def open_radio(cfg, profile):
    backend = cfg.get("backend", "cap")
    if backend == "demo":
        from .demo import DemoRadio
        return DemoRadio(profile)
    if backend == "lorapipe":
        from .lorapipe import LoRaPipeSerial
        if not cfg.get("serial_device"):
            raise RadioError("Choose the LoRaPipe serial device in Settings")
        return LoRaPipeSerial(profile, cfg["serial_device"])
    from .cap import CapRadio
    return CapRadio(profile)


def short_id(protocol, node):
    if not node:
        return "unknown"
    if protocol == "meshcore":
        return node[:8]
    return node


class Engine:
    def __init__(self, cfg, radio_factory=open_radio, gps=None):
        self.cfg = dict(cfg)
        self.radio_factory = radio_factory
        self.gps = gps or GPS(use_uart=cfg.get("backend") == "cap")
        self.lock = threading.Lock()
        self.state = "idle"          # idle | starting | capturing | stopping | error
        self.error = ""
        self.directory = None
        self.plan = []
        self.active = None
        self.plan_index = 0
        self.dwell_deadline = 0.0
        self.started = 0.0
        self.counters = {}
        self.recent = deque(maxlen=RECENT)
        self.messages = deque(maxlen=60)
        self.nodes = {}
        self.history = deque()       # (monotonic, rssi) for the activity graph
        self.per_profile = {}
        self.radio = None
        self.store = None
        self._stop = threading.Event()
        self._threads = []
        self._gps_stop = threading.Event()
        self._gps_thread = None
        self._mt_keys, self._mc_keys = configuration.decode_keys(cfg)
        self._locked = False

    # -- lifecycle -------------------------------------------------------
    def start_gps(self):
        if self._gps_thread is None or not self._gps_thread.is_alive():
            self._gps_stop.clear()
            self._gps_thread = threading.Thread(target=self.gps.run, args=(self._gps_stop,),
                                                daemon=True, name="gps")
            self._gps_thread.start()

    def start(self, data_root):
        if self.state in ("starting", "capturing", "stopping"):
            return
        self.error = ""
        self.plan = scan_plan(self.cfg)
        self.plan_index = 0
        self.active = self.plan[0]
        self.recent.clear()
        self.messages.clear()
        self.nodes.clear()
        self.history.clear()
        self.per_profile = {p.id: 0 for p in self.plan}
        self.counters = dict(received=0, saved=0, decoded=0, encrypted=0, malformed=0,
                             crc_errors=0, queue_drops=0, write_errors=0)
        self._stop.clear()
        self.state = "starting"
        self.directory = create_session(configuration.data_dir(self.cfg) if data_root is None else data_root)
        meta = read_metadata(self.directory)
        meta.update(status="capturing", started_at=time.time(), backend=self.cfg.get("backend"),
                    mode=self.cfg.get("mode"), region=self.cfg.get("region"),
                    profiles=[p.to_dict() for p in self.plan])
        try:
            self.radio = self.radio_factory(self.cfg, self.active)
            self.radio.open()
            self.store = Store(self.directory)
        except Exception as exc:
            self._fail_start(meta, exc)
            raise
        atomic_json(self.directory / "session.json", meta)
        self.started = time.monotonic()
        self.dwell_deadline = self.started + self.active.dwell_seconds
        self.start_gps()
        self._queue = queue.Queue(maxsize=512)
        self._threads = [threading.Thread(target=self._receive, daemon=True, name="radio"),
                         threading.Thread(target=self._write, daemon=True, name="writer")]
        for thread in self._threads:
            thread.start()
        self.state = "capturing"

    def _fail_start(self, meta, exc):
        message = str(exc) if isinstance(exc, (RadioError, ValueError, RuntimeError)) else type(exc).__name__
        if self.radio is not None:
            try:
                self.radio.close()
            except Exception:
                pass
            self.radio = None
        meta.update(status="interrupted", ended_at=time.time(), errors=[message])
        atomic_json(self.directory / "session.json", meta)
        self.state, self.error = "error", message

    def stop(self):
        if self.state not in ("starting", "capturing"):
            return
        self.state = "stopping"
        self._stop.set()
        for thread in self._threads:
            thread.join(4)
        failures = list(self._failures())
        if self.radio is not None:
            try:
                self.radio.close()
            except Exception:
                failures.append("Radio close failed")
        if self.store is not None:
            try:
                self.store.close()
            except Exception:
                self.counters["write_errors"] += 1
                failures.append("Storage close failed")
        try:
            meta = read_metadata(self.directory)
            meta.update(status="interrupted" if failures else "closed", ended_at=time.time(),
                        counters=dict(self.counters), errors=failures,
                        nodes=len(self.nodes), radio=dict(getattr(self.radio, "diagnostics", {})))
            atomic_json(self.directory / "session.json", meta)
        except (OSError, ValueError):
            failures.append("Session summary could not be saved")
        self.radio, self.store = None, None
        self.state = "error" if failures and not self.error else "idle"
        if failures and not self.error:
            self.error = failures[0]

    def shutdown(self):
        self.stop()
        self._gps_stop.set()

    def _failures(self):
        if self.error:
            yield self.error

    # -- workers ---------------------------------------------------------
    def _receive(self):
        try:
            while not self._stop.is_set():
                record = self.radio.receive(timeout=0.25)
                if record:
                    record["receiver_gps"] = self.gps.snapshot()
                    self.counters["received"] += 1
                    try:
                        self._queue.put_nowait(record)
                    except queue.Full:
                        self.counters["queue_drops"] += 1
                if len(self.plan) > 1 and time.monotonic() >= self.dwell_deadline:
                    self.hop(1)
        except Exception as exc:
            self.error = str(exc) if isinstance(exc, RadioError) else "Radio stopped: " + type(exc).__name__
            self._stop.set()

    def hop(self, step):
        """Move to the next/previous profile in the plan (also used by the UI)."""
        if len(self.plan) < 2 or self.radio is None:
            return
        with self.lock:
            self.plan_index = (self.plan_index + step) % len(self.plan)
            profile = self.plan[self.plan_index]
        self.radio.tune(profile)
        self.active = profile
        self.dwell_deadline = time.monotonic() + profile.dwell_seconds

    def _write(self):
        last_flush = time.monotonic()
        while True:
            if self._stop.is_set() and self._queue.empty():
                break
            try:
                record = self._queue.get(timeout=0.25)
            except queue.Empty:
                record = None
            try:
                if record is not None:
                    self._process(record)
                if time.monotonic() - last_flush >= 1:
                    self.store.flush()
                    last_flush = time.monotonic()
                    if shutil.disk_usage(self.directory).free < MIN_FREE_BYTES:
                        self.error = "Storage reserve reached; capture stopped"
                        self._stop.set()
            except (OSError, sqlite3.Error, ValueError) as exc:
                self.counters["write_errors"] += 1
                self.error = "Storage failed (%s); capture stopped" % type(exc).__name__
                self._stop.set()
                break

    def _process(self, record):
        if record.get("crc_ok") is False:
            record["decoded"] = {"protocol": "unknown", "decode_status": "crc_error"}
            self.counters["crc_errors"] += 1
        else:
            profile = next((p for p in self.plan if p.id == record["profile"]["id"]), self.active)
            try:
                record["decoded"] = decode_packet(
                    bytes.fromhex(record["raw_hex"]), profile, meshtastic_keys=self._mt_keys,
                    meshcore_keys=self._mc_keys, include_defaults=self.cfg.get("decode_public", True))
            except Exception:
                record["decoded"] = {"protocol": "unknown", "decode_status": "decoder_error"}
        self.store.append(record)
        self.counters["saved"] += 1
        status = record["decoded"].get("decode_status")
        if status == "decoded":
            self.counters["decoded"] += 1
        elif status in ("encrypted", "crypto_unavailable"):
            self.counters["encrypted"] += 1
        elif status == "malformed":
            self.counters["malformed"] += 1
        self._track(record)

    def _track(self, record):
        decoded = record["decoded"]
        protocol = decoded.get("protocol", "unknown")
        now = time.monotonic()
        rssi = record.get("rssi_dbm")
        with self.lock:
            pid = record["profile"].get("id")
            self.per_profile[pid] = self.per_profile.get(pid, 0) + 1
            if isinstance(rssi, (int, float)):
                self.history.append((now, rssi))
            while self.history and now - self.history[0][0] > HISTORY_SECONDS:
                self.history.popleft()
            node = node_id(decoded)
            entry = None
            if node:
                key = (protocol, node)
                entry = self.nodes.get(key)
                if entry is None:
                    entry = self.nodes[key] = {"protocol": protocol, "id": node, "first_seen": record["timestamp"],
                                               "count": 0, "best_rssi": rssi, "texts": deque(maxlen=8)}
                entry["count"] += 1
                entry["last_seen"] = record["timestamp"]
                entry["rssi"], entry["snr"] = rssi, record.get("snr_db")
                if isinstance(rssi, (int, float)) and (entry["best_rssi"] is None or rssi > entry["best_rssi"]):
                    entry["best_rssi"] = rssi
                    gps = record.get("receiver_gps") or {}
                    if gps.get("valid"):
                        entry["best_fix"] = (gps["latitude"], gps["longitude"])
                entry["profile"] = record["profile"].get("label")
                for field in ("name", "short_name", "node_type", "hardware_model", "public_key"):
                    if decoded.get(field) not in (None, ""):
                        entry[field] = decoded[field]
                if "node_position" in decoded:
                    entry["position"] = decoded["node_position"]
                if decoded.get("telemetry"):
                    entry["telemetry"] = decoded["telemetry"]
                if "hop_start" in decoded and decoded.get("hop_start"):
                    entry["hops"] = decoded["hop_start"] - decoded.get("hop_limit", 0)
                elif "hop_count" in decoded:
                    entry["hops"] = decoded["hop_count"]
            label = None
            if entry is not None:
                label = entry.get("short_name") or entry.get("name")
            sender = label or short_id(protocol, node)
            text = decoded.get("text")
            # MeshCore group text carries "Sender: message" inside the encrypted body.
            if text and protocol == "meshcore" and node is None and ": " in text[:40]:
                claimed, text = text.split(": ", 1)
                sender = claimed.strip()[:32] or sender
            if text:
                channel = decoded.get("channel_name", "?")
                self.messages.appendleft({"time": record["timestamp"], "protocol": protocol,
                                          "channel": channel, "from": sender, "text": text,
                                          "rssi": rssi})
                if entry is not None:
                    entry["texts"].appendleft(text)
            self.recent.appendleft({"time": record["timestamp"], "protocol": protocol, "from": sender,
                                    "kind": decoded.get("port_name") or decoded.get("payload_name") or "raw",
                                    "status": decoded.get("decode_status", "raw"), "rssi": rssi,
                                    "snr": record.get("snr_db"), "profile": record["profile"].get("label"),
                                    "text": text, "record": record})

    # -- read side ---------------------------------------------------------
    def dwell_remaining(self):
        if self.state != "capturing" or len(self.plan) < 2:
            return None
        return max(0.0, self.dwell_deadline - time.monotonic())

    def elapsed(self):
        return time.monotonic() - self.started if self.state == "capturing" else 0

    def node_list(self, sort="recent"):
        with self.lock:
            nodes = [dict(n) for n in self.nodes.values()]
        if sort == "signal":
            nodes.sort(key=lambda n: n.get("rssi") if n.get("rssi") is not None else -999, reverse=True)
        elif sort == "count":
            nodes.sort(key=lambda n: n["count"], reverse=True)
        else:
            nodes.sort(key=lambda n: n.get("last_seen", 0), reverse=True)
        return nodes

    def activity(self, buckets=40, seconds=HISTORY_SECONDS):
        """Packets per bucket and best RSSI per bucket over the recent window."""
        now = time.monotonic()
        counts, best = [0] * buckets, [None] * buckets
        with self.lock:
            points = list(self.history)
        for stamp, rssi in points:
            index = buckets - 1 - int((now - stamp) / (seconds / buckets))
            if 0 <= index < buckets:
                counts[index] += 1
                best[index] = rssi if best[index] is None else max(best[index], rssi)
        return counts, best
