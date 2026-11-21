"""Outgoing Meshtastic and MeshCore channel messages: frame builders and airtime.

Frames are built in the same wire formats the decoder reads (Meshtastic
mesh.proto Data inside an AES-CTR channel payload; MeshCore GRP_TXT with
AES-128-ECB and a truncated HMAC-SHA256). Transmit is off by default and is
gated in three places: the config flag, the engine's rate and airtime budget,
and the radio driver's transmit window.
"""

import base64
import hashlib
import hmac
import math
import os
import struct
import time

from .decode import DEFAULT_MESHTASTIC_KEY, MT_CHANNELS, PUBLIC_MESHCORE_KEY, _key_bytes

BROADCAST = 0xFFFFFFFF
MESHTASTIC_TEXT_MAX = 200      # bytes; firmware DATA_PAYLOAD_LEN leaves room for the header
MESHCORE_TEXT_MAX = 140        # bytes of "Name: text" (firmware MAX_TEXT_LEN 160 incl. framing)
HW_MODEL_PRIVATE = 255

# Conservative transmit caps (dBm at the radio) and duty-cycle percent per
# region, from Meshtastic's region table. Where a regulator's limit is unclear
# the cap is lower. Local rules always take precedence.
REGION_TX = {
    "US": (22, 100), "EU_868": (22, 10), "ANZ": (22, 100), "JP": (13, 100), "KR": (14, 100),
    "TW": (22, 100), "RU": (20, 100), "IN": (22, 100), "NZ_865": (22, 100), "TH": (16, 100),
    "UA_868": (14, 1), "MY_919": (22, 100), "SG_923": (20, 100), "PH_868": (14, 100), "PH_915": (14, 100),
    "KZ_863": (10, 100), "NP_865": (14, 100), "BR_902": (22, 100),
}


class SendError(ValueError):
    """A reason a message can't be sent, safe to show on screen."""


# ------------------------------------------------------------------ crypto
def _encrypt_ctr(key, nonce, data):
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        enc = Cipher(algorithms.AES(key), modes.CTR(nonce)).encryptor()
        return enc.update(data) + enc.finalize()
    except ImportError:
        from Crypto.Cipher import AES
        return AES.new(key, AES.MODE_CTR, nonce=b"", initial_value=int.from_bytes(nonce, "big")).encrypt(data)


def _encrypt_ecb(key, data):
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        return enc.update(data) + enc.finalize()
    except ImportError:
        from Crypto.Cipher import AES
        return AES.new(key, AES.MODE_ECB).encrypt(data)


# ------------------------------------------------------------------ protobuf
def _varint(number):
    out = bytearray()
    while number > 127:
        out.append((number & 127) | 128)
        number >>= 7
    out.append(number)
    return bytes(out)


def _bytes_field(number, data):
    return _varint(number << 3 | 2) + _varint(len(data)) + data


def _uint_field(number, value):
    return _varint(number << 3) + _varint(value)


# ------------------------------------------------------------------ Meshtastic
def meshtastic_channel_hash(name, key):
    result = 0
    for byte in name.encode("utf-8") + key:
        result ^= byte
    return result


def meshtastic_frame(source, packet_id, port, payload, channel_name, key, hop_limit=3, want_ack=False,
                     destination=BROADCAST):
    if not 1 <= source < BROADCAST:
        raise SendError("Invalid node number")
    hop_limit = max(0, min(7, hop_limit))
    data = _uint_field(1, port) + _bytes_field(2, payload)
    flags = hop_limit | (8 if want_ack else 0) | hop_limit << 5
    header = struct.pack("<IIIBBBB", destination, source, packet_id, flags,
                         meshtastic_channel_hash(channel_name, key), 0, source & 0xFF)
    if not key:
        return header + data
    nonce = struct.pack("<QII", packet_id, source, 0)
    return header + _encrypt_ctr(key, nonce, data)


def meshtastic_text(source, packet_id, text, channel_name, key, hop_limit=3):
    body = text.encode("utf-8")
    if not body:
        raise SendError("Type a message first")
    if len(body) > MESHTASTIC_TEXT_MAX:
        raise SendError("Message is %d bytes; Meshtastic allows %d" % (len(body), MESHTASTIC_TEXT_MAX))
    return meshtastic_frame(source, packet_id, 1, body, channel_name, key, hop_limit)


def meshtastic_nodeinfo(source, packet_id, long_name, short_name, channel_name, key, hop_limit=3):
    user = (_bytes_field(1, ("!%08x" % source).encode()) + _bytes_field(2, long_name.encode("utf-8")[:39])
            + _bytes_field(3, short_name.encode("utf-8")[:4]) + _uint_field(5, HW_MODEL_PRIVATE))
    return meshtastic_frame(source, packet_id, 4, user, channel_name, key, hop_limit)


def new_packet_id():
    return int.from_bytes(os.urandom(4), "little") or 1


def new_node_number():
    while True:
        number = int.from_bytes(os.urandom(4), "little")
        # Avoid broadcast, zero and the reserved low range used by some firmware.
        if 4 <= number < BROADCAST:
            return number


# ------------------------------------------------------------------ MeshCore
def meshcore_group_text(key, sender, text, timestamp=None, with_plain=False):
    message = ("%s: %s" % (sender, text)).encode("utf-8") if sender else text.encode("utf-8")
    if not text:
        raise SendError("Type a message first")
    if len(message) > MESHCORE_TEXT_MAX:
        raise SendError("Message is %d bytes; MeshCore allows %d" % (len(message), MESHCORE_TEXT_MAX))
    stamp = int(time.time() if timestamp is None else timestamp) & 0xFFFFFFFF
    plain = struct.pack("<I", stamp) + b"\x00" + message
    plain += b"\x00" * (-len(plain) % 16)
    cipher = _encrypt_ecb(key[:16], plain)
    mac = hmac.new(key, cipher, hashlib.sha256).digest()[:2]
    channel = hashlib.sha256(key).digest()[0]
    # Header: payload type GRP_TXT (5), route FLOOD (1); empty path.
    frame = bytes([(5 << 2) | 1, 0x00, channel]) + mac + cipher
    return (frame, plain) if with_plain else frame


# ------------------------------------------------------------------ channels
def send_channels(cfg, protocol):
    """(name, key bytes) a message can be sent on, default channel first."""
    from .config import decode_keys
    from .profiles import PRESETS
    mt, mc = decode_keys(cfg)
    out = []
    if protocol == "meshtastic":
        preset = PRESETS.get(cfg.get("preset", "LONG_FAST"))
        default = preset.name if preset else "LongFast"
        if cfg.get("decode_public", True):
            out.append((default, DEFAULT_MESHTASTIC_KEY))
        for item in mt:
            try:
                out.append((item["name"], _key_bytes(item["key"], "meshtastic")))
            except (ValueError, TypeError, KeyError):
                continue
    else:
        if cfg.get("decode_public", True):
            out.append(("Public", PUBLIC_MESHCORE_KEY))
        for item in mc:
            try:
                key = base64.b64decode(item["key"], validate=True)
            except (ValueError, TypeError, KeyError):
                continue
            if len(key) in (16, 32):
                out.append((item["name"], key))
    seen, unique = set(), []
    for name, key in out:
        if name not in seen:
            seen.add(name)
            unique.append((name, key))
    return unique


def is_default_meshtastic_channel(name):
    return name in MT_CHANNELS


# ------------------------------------------------------------------ airtime
def airtime(profile, length):
    """Time on air in seconds (Semtech SX1262 datasheet, explicit header, CRC on)."""
    sf, bw = profile.spreading_factor, profile.bandwidth_hz
    symbol = (2 ** sf) / bw
    ldro = 1 if symbol > 0.016 else 0
    cr = profile.coding_rate - 4
    numerator = 8 * length - 4 * sf + 28 + 16
    payload_symbols = 8 + max(math.ceil(numerator / (4 * (sf - 2 * ldro))) * (cr + 4), 0)
    return (profile.preamble_symbols + 4.25) * symbol + payload_symbols * symbol


def region_limits(region):
    return REGION_TX.get(region, (14, 1))
