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

    def open(self):
        return self

    def close(self):
        pass

    def tune(self, profile):
        self.profile = validate_profile(profile)
        self.diagnostics["retunes"] += 1

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
        if choice < 0.25:
            payload = (_field(1, ("!%08x" % node).encode()) + _field(2, name.encode())
                       + _field(3, short.encode()) + _uint(5, hw) + _uint(7, role))
            port = 4
        elif choice < 0.5:
            lat = self.base[0] + r.uniform(-0.03, 0.03)
            lon = self.base[1] + r.uniform(-0.03, 0.03)
            payload = _fixed32(1, int(lat * 1e7)) + _fixed32(2, int(lon * 1e7)) + _uint(3, r.randint(5, 400))
            port = 3
        elif choice < 0.75:
            device = (_uint(1, r.randint(20, 100)) + _varint(2 << 3 | 5) + struct.pack("<f", r.uniform(3.6, 4.2))
                      + _varint(3 << 3 | 5) + struct.pack("<f", r.uniform(1, 30)) + _uint(5, r.randint(100, 900000)))
            payload = _field(2, device)
            port = 67
        else:
            payload = r.choice(TEXTS).encode()
            port = 1
        hop_start = 3
        return meshtastic_frame(node, port, payload, self._packet, self.profile.label,
                                (r.randint(0, hop_start), hop_start))

    def receive(self, timeout=0.25):
        now = self.clock()
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
