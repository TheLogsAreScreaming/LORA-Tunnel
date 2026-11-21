"""Synthetic receiver for demos, screenshots and tests. Nothing here is real traffic.

Frames are built in the real on-air formats (encrypted with the public default
keys) so they exercise the same decoder and storage paths as live capture.
"""

import hashlib
import hmac
import random
import struct
import time

from .decode import DEFAULT_MESHTASTIC_KEY, PUBLIC_MESHCORE_KEY
from .profiles import validate_profile

MT_NODES = [
    (0x9e2a51c4, "Ridge Relay", "RDG", 2, 43),
    (0x4b10d7aa, "Trail Walker", "TRLW", 0, 9),
    (0x71c3e002, "Water Tower", "WTR", 3, 4),
    (0x2fd84b19, "Base Camp", "BASE", 0, 31),
    (0x88a1f5e7, "Solar Node 7", "SN7", 6, 50),
]
MC_NODES = [("Hilltop Rptr", 2), ("Mobile K7", 1), ("Room Server", 3)]
TEXTS = ["anyone on LongFast?", "copy, 3 bars here", "heading to the ridge",
         "net check-in 19:00", "battery at 40%", "signal test 1 2 3"]


def _varint(number):
    out = bytearray()
    while number > 127:
        out.append((number & 127) | 128)
        number >>= 7
    out.append(number)
    return bytes(out)


def _field(number, data):
    return _varint(number << 3 | 2) + _varint(len(data)) + data


def _fixed32(number, value):
    return _varint(number << 3 | 5) + struct.pack("<i", value)


def _uint(number, value):
    return _varint(number << 3) + _varint(value)


def _aes_ctr(key, nonce, data):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    enc = Cipher(algorithms.AES(key), modes.CTR(nonce)).encryptor()
    return enc.update(data) + enc.finalize()


def _aes_ecb(key, data):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return enc.update(data) + enc.finalize()


def meshtastic_frame(source, port, payload, packet_id, channel="LongFast", hops=(3, 3)):
    data = _uint(1, port) + _field(2, payload)
    nonce = struct.pack("<QII", packet_id, source, 0)
    channel_hash = 0
    for byte in channel.encode() + DEFAULT_MESHTASTIC_KEY:
        channel_hash ^= byte
    hop_limit, hop_start = hops
    flags = (hop_limit & 7) | (hop_start << 5)
    header = struct.pack("<IIIBBBB", 0xFFFFFFFF, source, packet_id, flags, channel_hash, 0, source & 0xFF)
    return header + _aes_ctr(DEFAULT_MESHTASTIC_KEY, nonce, data)


class _MeshCoreIdentity:
    def __init__(self, name, kind, seed):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        self.name, self.kind = name, kind
        self.key = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(seed).digest())
        self.public = self.key.public_key().public_bytes(serialization.Encoding.Raw,
                                                          serialization.PublicFormat.Raw)

    def advert(self, lat, lon):
        flags = self.kind | 0x10 | 0x80
        app = bytes([flags]) + struct.pack("<ii", int(lat * 1e6), int(lon * 1e6)) + self.name.encode()
        stamp = struct.pack("<I", int(time.time()))
        signature = self.key.sign(self.public + stamp + app)
        return bytes([(4 << 2) | 1, 0x00]) + self.public + stamp + signature + app


def meshcore_group_text(sender, text):
    key = PUBLIC_MESHCORE_KEY
    plain = struct.pack("<I", int(time.time())) + b"\x00" + ("%s: %s" % (sender, text)).encode()
    plain += b"\x00" * (-len(plain) % 16)
    cipher = _aes_ecb(key[:16], plain)
    mac = hmac.new(key, cipher, hashlib.sha256).digest()[:2]
    channel = hashlib.sha256(key).digest()[0]
    return bytes([(5 << 2) | 1, 0x01, 0x5a]) + bytes([channel]) + mac + cipher


class DemoRadio:
    """Drop-in for CapRadio. Emits a plausible synthetic packet every ~1-3 s."""

    def __init__(self, profile, seed=7, rate=1.0, clock=time.time):
        self.profile = validate_profile(profile)
        self.random = random.Random(seed)
        self.rate = rate
        self.clock = clock
        self.diagnostics = dict(received=0, timeouts=0, header_errors=0, crc_errors=0,
                                malformed=0, retunes=0)
        self._next = 0.0
        self._packet = 0x1000
        self._mc = [_MeshCoreIdentity(name, kind, name.encode()) for name, kind in MC_NODES]
        self.base = (37.7749, -122.4194)
        self.allow_tx = False
        self.sent = []
        self._echo = []   # (due, frame): a neighbour repeating what we sent

    def open(self):
        return self

    def close(self):
        pass

    def tune(self, profile):
        self.profile = validate_profile(profile)
        self.diagnostics["retunes"] += 1

    def transmit(self, payload, profile=None, power_dbm=14, timeout=8.0):
        """Pretend to transmit; a synthetic neighbour repeats the frame shortly after."""
        from . import RadioError
        if not self.allow_tx:
            raise RadioError("Transmit is turned off in Settings")
        if profile is not None and profile != self.profile:
            self.tune(profile)
        frame = bytes(payload)
        self.sent.append((frame, self.profile.id, power_dbm))
        if self.profile.protocol == "meshtastic" and len(frame) > 16:
            relayed = bytearray(frame)
            hop_limit = relayed[12] & 7
            relayed[12] = (relayed[12] & 0xF8) | max(0, hop_limit - 1)
            relayed[15] = 0xC4  # the relaying node's last byte
            self._echo.append((self.clock() + 1.2, bytes(relayed), self.profile))
        elif self.profile.protocol == "meshcore" and len(frame) > 3:
            relayed = frame[:1] + b"\x01\x5a" + frame[2:]
            self._echo.append((self.clock() + 1.6, relayed, self.profile))
        self.diagnostics["transmitted"] = self.diagnostics.get("transmitted", 0) + 1
        return 0.2

    def __enter__(self):
        return self.open()

    def __exit__(self, *_):
        self.close()

    def next_frame(self):
        r = self.random
        self._packet += r.randint(1, 40)
        if self.profile.protocol == "meshcore":
            ident = r.choice(self._mc)
            if r.random() < 0.55:
                lat = self.base[0] + r.uniform(-0.05, 0.05)
                lon = self.base[1] + r.uniform(-0.05, 0.05)
                return ident.advert(lat, lon)
            return meshcore_group_text(ident.name, r.choice(TEXTS))
        node, name, short, role, hw = r.choice(MT_NODES)
        choice = r.random()
        f32 = lambda number, value: _varint(number << 3 | 5) + struct.pack("<f", value)  # noqa: E731
        u32 = lambda number, value: _varint(number << 3 | 5) + struct.pack("<I", value)  # noqa: E731
        if choice < 0.2:
            payload = (_field(1, ("!%08x" % node).encode()) + _field(2, name.encode())
                       + _field(3, short.encode()) + _uint(5, hw) + _uint(7, role))
            port = 4
        elif choice < 0.4:
            lat = self.base[0] + r.uniform(-0.03, 0.03)
            lon = self.base[1] + r.uniform(-0.03, 0.03)
            payload = (_fixed32(1, int(lat * 1e7)) + _fixed32(2, int(lon * 1e7)) + _uint(3, r.randint(5, 400))
                       + _uint(19, r.randint(4, 14)))
            port = 3
        elif choice < 0.55:
            device = (_uint(1, r.randint(20, 100)) + f32(2, r.uniform(3.6, 4.2)) + f32(3, r.uniform(1, 30))
                      + _uint(5, r.randint(100, 900000)))
            payload = _field(2, device)
            port = 67
        elif choice < 0.62:
            env = f32(1, r.uniform(8, 31)) + f32(2, r.uniform(20, 80)) + f32(3, r.uniform(995, 1025))
            payload = _field(3, env)
            port = 67
        elif choice < 0.69:
            neighbors = b"".join(_field(4, _uint(1, other[0]) + f32(2, round(r.uniform(-12, 10), 2)))
                                 for other in MT_NODES if other[0] != node and r.random() < 0.7)
            payload = _uint(1, node) + _uint(3, 900) + neighbors
            port = 71
        elif choice < 0.75:
            others = [other[0] for other in MT_NODES if other[0] != node]
            r.shuffle(others)
            destination, hops = others[0], others[1:1 + r.randint(1, 3)]
            payload = (_field(1, b"".join(struct.pack("<I", h) for h in hops))
                       + _field(2, b"".join(_varint(r.randint(-40, 40) & 0xFFFFFFFFFFFFFFFF)
                                            for _ in range(len(hops) + 1))))
            port = 70
            data = _uint(1, port) + _field(2, payload) + u32(6, r.randint(1, 0xFFFFFFF))
            return self._mt_data(node, data, r, destination)
        elif choice < 0.8:
            payload = (_field(1, name.encode()) + _field(2, short.encode()) + _uint(3, role) + _uint(4, hw)
                       + _field(5, b"2.7.15.567b8ea") + _uint(6, 1) + _uint(7, 0) + _uint(8, 1)
                       + _fixed32(9, int((self.base[0] + 0.01) * 1e7)) + _fixed32(10, int((self.base[1] - 0.02) * 1e7))
                       + _uint(13, r.randint(5, 40)))
            port = 73
        else:
            payload = r.choice(TEXTS).encode()
            port = 1
        hop_start = 3
        return meshtastic_frame(node, port, payload, self._packet, self.profile.label,
                                (r.randint(0, hop_start), hop_start))

    def _mt_data(self, node, data, r, destination=0xFFFFFFFF):
        nonce = struct.pack("<QII", self._packet, node, 0)
        channel_hash = 0
        for byte in self.profile.label.encode() + DEFAULT_MESHTASTIC_KEY:
            channel_hash ^= byte
        hop_start = 3
        flags = (r.randint(0, hop_start) & 7) | (hop_start << 5)
        header = struct.pack("<IIIBBBB", destination, node, self._packet, flags, channel_hash, 0, node & 0xFF)
        return header + _aes_ctr(DEFAULT_MESHTASTIC_KEY, nonce, data)

    def receive(self, timeout=0.25):
        now = self.clock()
        self._echo = [e for e in self._echo if now - e[0] < 30]
        # A repeat is only heard while tuned to the profile it was sent on.
        if self._echo and self._echo[0][0] <= now and self._echo[0][2] == self.profile:
            _, raw, _ = self._echo.pop(0)
            return {"timestamp": now, "profile": self.profile.to_dict(), "raw_hex": raw.hex(),
                    "rssi_dbm": -84.0, "snr_db": 6.5, "crc_ok": True, "synthetic": True}
        if now < self._next:
            time.sleep(min(timeout, max(0.0, self._next - now)))
            if self.clock() < self._next:
                return None
        self._next = self.clock() + self.random.uniform(0.8, 2.6) / max(self.rate, 0.01)
        raw = self.next_frame()
        self.diagnostics["received"] += 1
        rssi = round(self.random.uniform(-122, -58), 1)
        return {"timestamp": self.clock(), "profile": self.profile.to_dict(), "raw_hex": raw.hex(),
                "rssi_dbm": rssi, "snr_db": round(max(-18, min(12, (rssi + 112) / 4 + self.random.uniform(-3, 3))), 2),
                "crc_ok": True, "synthetic": True}


# ------------------------------------------------------------------ Recon demo
def _ad(kind, data):
    return bytes((len(data) + 1, kind)) + bytes(data)


def _odid_location(lat, lon, alt=95.0, speed=8.0):
    body = struct.pack("<BBBBbiiHHHBBHB", 0x12, 0x20, 120, int(speed / 0.25), 2, int(lat * 1e7), int(lon * 1e7),
                       int((alt + 1000) * 2), int((alt + 1000) * 2), int(1050 * 2), 0x3b, 0x22, 900, 0)
    return body.ljust(25, b"\x00")[:25]


def _odid_basic(serial):
    return bytes((0x02, 0x12)) + serial.encode().ljust(20, b"\x00") + b"\x00" * 3


class DemoWifi:
    """Synthetic AP list for demos and screenshots. Not real networks."""

    name = "Wi-Fi"

    def __init__(self, seed=11):
        self.random = random.Random(seed)
        self.networks = [
            ("00:04:7D:3A:91:20", "MSI-ALPR-0420", 6, "WPA2/3"),
            ("70:C9:4E:12:5C:01", "Flock-5C01", 1, "WPA2/3"),
            ("00:25:DF:4B:02:7E", "AXON-FLEET", 11, "WPA2/3"),
            ("00:40:8C:77:10:AA", "AXIS-CAM-10AA", 6, "WPA2/3"),
            ("3C:84:6A:10:20:30", "HomeNet-5G", 36, "WPA2/3"),
            ("F0:9F:C2:55:01:02", "CoffeeShop Guest", 1, "open"),
            ("A4:2B:B0:11:22:33", "NETGEAR42", 11, "WPA2/3"),
            ("B8:27:EB:01:02:03", "pwned-by-pager", 6, "open"),
        ]

    def available(self):
        return True

    def scan(self):
        out = []
        for bssid, ssid, channel, security in self.networks:
            if self.random.random() < 0.9:
                freq = 5000 + channel * 5 if channel > 14 else 2407 + channel * 5
                out.append({"bssid": bssid, "ssid": ssid, "channel": channel, "frequency": freq,
                            "security": security, "rssi": round(self.random.uniform(-88, -42))})
        return out

    def close(self):
        pass


class DemoBle:
    """Synthetic BLE advertisements, built in real AD formats. Not real devices."""

    name = "BLE"

    def __init__(self, seed=13, base=(37.7790, -122.4170)):
        self.random = random.Random(seed)
        lat, lon = base
        rid = _ad(0x16, bytes((0xfa, 0xff, 0x0d, 0x03)) + bytes((0xF2, 25, 2)) +
                  _odid_basic("1581F5FKD229400DEMO") + _odid_location(lat + 0.0012, lon - 0.0009))
        self.devices = [
            ("58:8E:81:A0:12:34", 0, _ad(9, b"Penguin-1234567890") + _ad(0xff, b"\xc8\x09\x01\x02")),
            ("5A:3C:11:9D:20:7F", 1, _ad(0xff, b"\x4c\x00\x12\x19" + bytes(range(25)))),
            ("00:25:DF:66:01:02", 0, _ad(0xff, b"\x4d\x03\x01") + _ad(3, b"\x81\xfc")),
            ("60:60:1F:AB:CD:EF", 1, rid),
            ("C2:11:22:33:44:55", 1, _ad(3, b"\x5a\xfd") + _ad(9, b"Galaxy SmartTag2")),
            ("E4:5F:01:AA:BB:CC", 0, _ad(0xff, b"\x4c\x00\x02\x15" + bytes(range(16)) + b"\x00\x01\x00\x02\xc5")),
            ("D8:3A:DD:10:20:30", 1, _ad(9, b"Pixel Buds")),
            ("F1:22:33:44:55:66", 1, _ad(3, b"\x81\x30") + _ad(0x19, b"\x00\x86") + _ad(9, b"Flipper Demo")),
            ("C8:3F:26:01:02:03", 1, _ad(0xff, b"\x06\x00\x01\x09\x20\x02")),
        ]

    def scan(self):
        out = []
        for address, kind, ad in self.devices:
            if self.random.random() < 0.85:
                out.append({"address": address, "address_type": kind, "raw_ad": ad,
                            "rssi": round(self.random.uniform(-95, -48)), "name": ""})
        return out

    def close(self):
        pass
