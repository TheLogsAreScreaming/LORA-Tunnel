"""Bounded on-air decoders; radio capture and key availability are independent.

Adapted from Evil-LORA-Tunnel / LORA-Pager-Pipe, copyright 2026 Valleytech
Solutions, MIT license.

Wire formats: Meshtastic protobufs/mesh.proto and MeshCore docs/packet_format.md,
docs/payloads.md. This is independent Python code, not a translation of Kismet.
The cryptography package supplies AES and Ed25519. PyCryptodome and PyNaCl
are alternative providers. Recording preserves raw bytes without a provider.
"""

import base64
import hashlib
import hmac
import math
import struct

from . import mt_apps


class DecodeError(ValueError):
    pass


DEFAULT_MESHTASTIC_KEY = bytes.fromhex("d4f1bb3a20290759f0bcffabcf4e6901")
PUBLIC_MESHCORE_KEY = base64.b64decode("izOH6cXN6mrJ5e26oRXNcg==")
MT_CHANNELS = ("LongFast", "LongSlow", "LongTurbo", "LongMod", "LongModerate", "MediumFast",
               "MediumSlow", "ShortFast", "ShortSlow", "ShortTurbo")
MT_PORTS = {1: "text", 2: "remote_hardware", 3: "position", 4: "nodeinfo", 5: "routing", 6: "admin",
            7: "compressed_text", 8: "waypoint", 9: "audio", 10: "detection", 11: "alert",
            12: "key_verification", 13: "remote_shell", 32: "reply", 33: "ip_tunnel", 34: "paxcounter",
            35: "store_forward_plus", 36: "node_status", 37: "mesh_beacon", 38: "paging",
            64: "serial", 65: "store_forward", 66: "range_test", 67: "telemetry", 68: "zps",
            69: "simulator", 70: "traceroute", 71: "neighborinfo", 72: "atak", 73: "map_report",
            74: "powerstress", 75: "lorawan_bridge", 76: "reticulum", 77: "cayenne", 78: "atak_v2",
            79: "lora_ota", 112: "group_alarm", 256: "private", 257: "atak_forwarder"}
MC_TYPES = {0: "request", 1: "response", 2: "text", 3: "ack", 4: "advert",
            5: "group_text", 6: "group_data", 7: "anon_request", 8: "path",
            9: "trace", 10: "multipart", 11: "control", 15: "raw_custom"}
MC_TEXT_TYPES = {0: "plain", 1: "cli", 2: "signed", 3: "cli_command"}
MC_NODE_TYPES = {1: "companion", 2: "repeater", 3: "room_server", 4: "sensor"}


def _varint(data, pos):
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(data):
            raise DecodeError("Truncated varint")
        byte = data[pos]
        pos += 1
        if shift == 63 and byte > 1:
            raise DecodeError("Varint overflow")
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise DecodeError("Varint overflow")


def protobuf_fields(data):
    """Parse one bounded protobuf message, retaining wire types for validation."""
    if len(data) > 255:
        raise DecodeError("Oversize protobuf message")
    fields, pos, count = {}, 0, 0
    while pos < len(data):
        count += 1
        if count > 96:
            raise DecodeError("Too many protobuf fields")
        tag, pos = _varint(data, pos)
        number, wire = tag >> 3, tag & 7
        if not 1 <= number <= 0x1FFFFFFF:
            raise DecodeError("Invalid protobuf tag")
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire in {1, 5}:
            size = 8 if wire == 1 else 4
            if pos + size > len(data):
                raise DecodeError("Truncated fixed field")
            value = data[pos:pos + size]
            pos += size
        elif wire == 2:
            size, pos = _varint(data, pos)
            if size > len(data) - pos:
                raise DecodeError("Truncated length-delimited field")
            value = data[pos:pos + size]
            pos += size
        else:
            raise DecodeError("Unsupported protobuf wire type")
        # These protobufs have scalar fields; last scalar occurrence wins.
        fields[number] = (wire, value)
    return fields


def _field(fields, number, wire, default=None):
    if number not in fields:
        return default
    actual_wire, value = fields[number]
    if actual_wire != wire:
        raise DecodeError("Incorrect protobuf wire type")
    return value


def _text(raw, limit=240):
    if len(raw) > limit:
        raise DecodeError("Oversize text")
    value = raw.decode("utf-8", "strict").rstrip("\x00")
    return "".join(c if c.isprintable() or c in "\n\t" else "\ufffd" for c in value)


def _position(lat, lon):
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise DecodeError("Invalid advertised position")
    return {"latitude": lat, "longitude": lon, "source": "advertised"}


def _aes(key, payload, nonce=None):
    try:
        from Crypto.Cipher import AES
        if nonce is None:
            return AES.new(key, AES.MODE_ECB).decrypt(payload)
        return AES.new(key, AES.MODE_CTR, nonce=b"", initial_value=int.from_bytes(nonce, "big")).decrypt(payload)
    except Exception:
        # An installed package can still lack a usable native crypto provider.
        # Try the other supported provider without surfacing key-bearing errors.
        pass
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        mode = modes.ECB() if nonce is None else modes.CTR(nonce)
        decryptor = Cipher(algorithms.AES(key), mode).decryptor()
        return decryptor.update(payload) + decryptor.finalize()
    except Exception:
        return None


def _crypto_call(operation, *args):
    """Keep optional provider failures separate from malformed radio frames."""
    try:
        return operation(*args)
    except Exception:
        return None


def _verify_ed25519(key, message, signature):
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
    except Exception:
        try:
            from nacl.signing import VerifyKey
            from nacl.exceptions import BadSignatureError
        except ImportError:
            return None
        try:
            VerifyKey(key).verify(message, signature)
            return True
        except (ValueError, BadSignatureError):
            return False
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(signature, message)
        return True
    except UnsupportedAlgorithm:
        return None
    except (ValueError, InvalidSignature):
        return False


def _key_bytes(value, protocol):
    key = value if isinstance(value, bytes) else base64.b64decode(value, validate=True)
    if protocol == "meshtastic" and len(key) == 1 and key[0] != 0:
        return DEFAULT_MESHTASTIC_KEY[:-1] + bytes([(DEFAULT_MESHTASTIC_KEY[-1] + key[0] - 1) & 255])
    if protocol == "meshtastic" and key in {b"", b"\x00"}:
        return b""
    if len(key) not in {16, 32}:
        raise ValueError("Channel keys must be 16 or 32 bytes")
    return key


def _keys(user_keys, protocol, include_defaults=True):
    # Keys are input only. Neither return records nor errors contain them.
    defaults = [(name, DEFAULT_MESHTASTIC_KEY) for name in MT_CHANNELS] if protocol == "meshtastic" else [("Public", PUBLIC_MESHCORE_KEY)]
    if not include_defaults:
        defaults = []
    configured = {}
    for item in (user_keys or [])[:32]:
        try:
            name = item["name"]
            if not isinstance(name, str) or not 1 <= len(name) <= 32:
                continue
            configured[name] = _key_bytes(item["key"], protocol)
        except (ValueError, TypeError, KeyError):
            continue
    result = dict(defaults)
    result.update(configured)
    return result.items()


def _mt_hash(name, key):
    result = 0
    for byte in name.encode("utf-8") + key:
        result ^= byte
    return result


def _decode_mt_data(plaintext, header=None):
    fields = protobuf_fields(plaintext)
    port = _field(fields, 1, 0)
    body = _field(fields, 2, 2, b"")
    if port is None or not 1 <= port <= 511:
        raise DecodeError("Missing or invalid application port")
    result = {"portnum": port, "port_name": MT_PORTS.get(port, "port_%d" % port),
              "payload_hex": body.hex()}
    bitfield = _field(fields, 9, 0)
    result["sender_bitfield_present"] = bitfield is not None
    if bitfield is not None:
        result["sender_bitfield"] = bitfield
    data = dict(header or {})
    for number, name in ((6, "request_id"), (7, "reply_id"), (8, "emoji")):
        raw = _field(fields, number, 5)
        if raw is not None and int.from_bytes(raw, "little"):
            data[name] = result[name] = int.from_bytes(raw, "little")
    if _field(fields, 3, 0):
        result["want_response"] = True
    if result.get("emoji") and result.get("reply_id"):
        result["reaction_to"] = "%08x" % result["reply_id"]
    if _field(fields, 10, 2):
        result["signature_present"] = True
    decoder = mt_apps.DECODERS.get(port)
    if decoder is not None:
        try:
            result.update(decoder(body, data))
        except (mt_apps.AppError, struct.error, UnicodeDecodeError) as exc:
            if port in (1, 3, 4, 67):
                # Core ports must parse; a failure means the wrong key or a corrupt frame.
                raise DecodeError(str(exc)) from exc
            result["app_decode_error"] = str(exc)
    if not result.get("details"):
        result.pop("details", None)
    return result


def _meshtastic(raw, keys, include_defaults=True):
    if len(raw) <= 16:
        raise DecodeError("Truncated Meshtastic frame")
    destination, source, packet_id, flags, channel, next_hop, relay = struct.unpack("<IIIBBBB", raw[:16])
    if source in {0, 0xFFFFFFFF}:
        raise DecodeError("Invalid Meshtastic source")
    result = {"protocol": "meshtastic", "decode_status": "encrypted",
              "source_id": "!%08x" % source, "destination_id": "!%08x" % destination,
              "packet_id": "%08x" % packet_id, "hop_limit": flags & 7,
              "hop_start": flags >> 5, "want_ack": bool(flags & 8),
              "via_mqtt": bool(flags & 16), "channel_hash": channel,
              "next_hop": next_hop, "relay_node": relay}
    # Do not infer the physical transmitter from the original source address.
    nonce = struct.pack("<QII", packet_id, source, 0)
    unavailable = False
    for name, key in _keys(keys, "meshtastic", include_defaults):
        if _mt_hash(name, key) != channel:
            continue
        plain = _crypto_call(_aes, key, raw[16:], nonce) if key else raw[16:]
        if plain is None:
            unavailable = True
            continue
        try:
            payload = _decode_mt_data(plain, {"source_name": result["source_id"],
                                               "destination_name": "^all" if destination == 0xFFFFFFFF
                                               else result["destination_id"]})
        except (DecodeError, UnicodeDecodeError):
            continue
        result.update(payload)
        result.update(decode_status="decoded", channel_name=name,
                      payload_authenticated=False,
                      encryption="aes-ctr" if key else "none")
        return result
    if unavailable:
        result["decode_status"] = "crypto_unavailable"
    return result


def _meshcore(raw, keys, include_defaults=True):
    if len(raw) < 3 or raw[0] >> 6:
        raise DecodeError("Unsupported MeshCore frame")
    route, kind = raw[0] & 3, (raw[0] >> 2) & 15
    if kind not in {*range(12), 15}:
        raise DecodeError("Unknown MeshCore payload type")
    index = 5 if route in {0, 3} else 1
    if index >= len(raw):
        raise DecodeError("Truncated transport header")
    path_info = raw[index]
    count, hash_size = path_info & 63, 1 + (path_info >> 6)
    path_size = count * hash_size
    if hash_size > 3 or path_size > 64 or index + 1 + path_size >= len(raw):
        raise DecodeError("Invalid MeshCore path")
    path = raw[index + 1:index + 1 + path_size]
    payload = raw[index + 1 + path_size:]
    if len(payload) > 184:
        raise DecodeError("Oversize MeshCore payload")
    result = {"protocol": "meshcore", "decode_status": "header_only", "route_type": route,
              "route_name": ("transport_flood", "flood", "direct", "transport_direct")[route],
              "payload_type": kind, "payload_name": MC_TYPES.get(kind, "unknown"), "path_hash_size": hash_size, "path_count": count,
              "path_hex": path.hex()}
    if route in {0, 1}:
        result["hop_count"] = count
    if kind == 4:
        if not 100 <= len(payload) <= 132:
            raise DecodeError("Invalid MeshCore advertisement length")
        key, stamp, signature, app = payload[:32], payload[32:36], payload[36:100], payload[100:]
        valid = _crypto_call(_verify_ed25519, key, key + stamp + app, signature)
        result.update(public_key=key.hex(), signature_valid=valid,
                      advertised_timestamp=int.from_bytes(stamp, "little"))
        if valid is not True:
            result["decode_status"] = "crypto_unavailable" if valid is None else "signature_invalid"
            return result
        result.update(source_id=key.hex(), decode_status="decoded")
        if not app:
            return result
        flags, cursor = app[0], 1
        result["node_type"] = MC_NODE_TYPES.get(flags & 15, "unknown")
        if flags & 0x10:
            if cursor + 8 > len(app):
                raise DecodeError("Truncated advert location")
            lat, lon = struct.unpack("<ii", app[cursor:cursor + 8])
            cursor += 8
            # MeshCore uses both zero as no-location sentinel.
            if lat != 0 or lon != 0:
                result["node_position"] = _position(lat / 1e6, lon / 1e6)
        cursor += (2 if flags & 0x20 else 0) + (2 if flags & 0x40 else 0)
        if cursor > len(app):
            raise DecodeError("Truncated advert feature fields")
        if flags & 0x80:
            result["name"] = _text(app[cursor:], 32)
        return result
    if kind in {0, 1, 2, 8, 7, 5, 6}:
        prefix = 33 if kind == 7 else (1 if kind in {5, 6} else 2)
        if len(payload) < prefix + 18 or (len(payload) - prefix - 2) % 16:
            raise DecodeError("Invalid MeshCore encrypted length")
        result["decode_status"] = "encrypted"
        if kind not in {5, 6}:
            result["destination_hash"] = payload[:1].hex()
            if prefix == 2:
                result["source_hash"] = payload[1:2].hex()
            if kind == 7:
                # Anonymous requests (logins) carry the sender's full public key in clear.
                result["sender_public_key"] = payload[1:33].hex()
                result["details"] = [("Request", "anonymous login/request to %s" % payload[:1].hex()),
                                     ("Sender key", payload[1:9].hex() + "…")]
            else:
                result["details"] = [("Direct", "%s → %s (end-to-end encrypted)" % (payload[1:2].hex(),
                                                                                  payload[:1].hex()))]
            return result
        result["channel_hash"] = payload[0]
        cipher, mac = payload[3:], payload[1:3]
        for name, key in _keys(keys, "meshcore", include_defaults):
            if hashlib.sha256(key).digest()[0] != payload[0]:
                continue
            if not hmac.compare_digest(hmac.new(key, cipher, hashlib.sha256).digest()[:2], mac):
                continue
            plain = _crypto_call(_aes, key[:16], cipher)
            if plain is None:
                result["decode_status"] = "crypto_unavailable"
                return result
            result.update(channel_name=name, decode_status="decoded", payload_authenticated=True,
                          authentication="truncated_hmac_sha256", payload_hex=plain.hex())
            if kind == 5:
                if len(plain) < 5:
                    raise DecodeError("Unsupported MeshCore group text")
                txt_type, attempt = plain[4] >> 2, plain[4] & 3
                body = plain[5:]
                result["message_timestamp"] = int.from_bytes(plain[:4], "little")
                result["text_type"] = MC_TEXT_TYPES.get(txt_type, "type_%d" % txt_type)
                if attempt:
                    result["attempt"] = attempt + 1
                if txt_type == 2:
                    if len(body) < 4:
                        raise DecodeError("Truncated signed group text")
                    result["sender_prefix"] = body[:4].hex()
                    body = body[4:]
                elif txt_type not in MC_TEXT_TYPES:
                    raise DecodeError("Unsupported MeshCore group text")
                result["text"] = _text(body.split(b"\x00", 1)[0])
            else:
                if len(plain) < 3:
                    raise DecodeError("Truncated MeshCore group data")
                data_type, size = int.from_bytes(plain[:2], "little"), plain[2]
                result.update(data_type=data_type, data_hex=plain[3:3 + size].hex())
                result["details"] = [("Group data", "type 0x%04x, %d bytes" % (data_type, size))]
            return result
        return result
    if kind == 3:
        if len(payload) < 4:
            raise DecodeError("Truncated MeshCore ACK")
        result.update(ack_crc=payload[:4].hex(), details=[("ACK", "checksum " + payload[:4].hex())])
    elif kind == 9:
        if len(payload) < 9:
            raise DecodeError("Truncated MeshCore trace")
        flags = payload[8]
        width = 1 << (flags & 3)
        hops = payload[9:]
        route = [hops[i:i + width].hex() for i in range(0, len(hops) - len(hops) % width, width)]
        # A trace packet's path field collects one signed SNR*4 byte per hop so far.
        snrs = [struct.unpack("b", bytes([b]))[0] / 4 for b in path]
        result.update(trace_tag=payload[:4].hex(), trace_route=route, trace_snr=snrs)
        line = " → ".join("%s%s" % (node, " (%+.1f dB)" % snrs[i] if i < len(snrs) else "")
                          for i, node in enumerate(route)) or "(direct)"
        result["details"] = [("Trace", line)]
    elif kind == 10:
        if len(payload) < 1:
            raise DecodeError("Truncated MeshCore multipart")
        remaining, inner = payload[0] >> 4, payload[0] & 15
        result.update(multipart_remaining=remaining, multipart_type=MC_TYPES.get(inner, str(inner)))
        result["details"] = [("Multipart", "%s, %d more to come" % (MC_TYPES.get(inner, str(inner)), remaining))]
        if inner == 3 and len(payload) >= 5:
            result["ack_crc"] = payload[1:5].hex()
    elif kind == 11:
        if len(payload) < 1:
            raise DecodeError("Truncated MeshCore control")
        sub = payload[0] >> 4
        if sub == 8 and len(payload) >= 6:
            wanted = [MC_NODE_TYPES[b] for b in MC_NODE_TYPES if payload[1] & (1 << b)]
            result.update(control="discover_request", discover_tag=payload[2:6].hex(),
                          discover_types=wanted)
            result["details"] = [("Discover", "asking for " + (", ".join(wanted) or "any node"))]
        elif sub == 9 and len(payload) >= 14:
            node_type = MC_NODE_TYPES.get(payload[0] & 15, "unknown")
            key = payload[6:38] if len(payload) >= 38 else payload[6:14]
            snr = struct.unpack("b", payload[1:2])[0] / 4
            result.update(control="discover_response", node_type=node_type, discover_tag=payload[2:6].hex(),
                          discovered_key=key.hex(), reported_snr=snr)
            if len(key) == 32:
                # Same identity as the node's adverts; not signed here, so unverified.
                result.update(source_id=key.hex(), identity_verified=False)
            result["details"] = [("Discover", "%s answered, heard us at %+.1f dB" % (node_type, snr))]
        else:
            result["control"] = "subtype_%d" % sub
    elif kind == 15:
        result["details"] = [("Custom", "%d raw bytes (application defined)" % len(payload))]
    return result


def decode_packet(raw, profile, *, meshtastic_keys=None, meshcore_keys=None, include_defaults=True):
    """Decode one packet without allowing malformed input to escape capture."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 255:
        return {"protocol": "unknown", "decode_status": "malformed"}
    try:
        protocol = profile.protocol if hasattr(profile, "protocol") else profile.get("protocol")
        if protocol == "meshtastic":
            return _meshtastic(raw, meshtastic_keys, include_defaults)
        if protocol == "meshcore":
            return _meshcore(raw, meshcore_keys, include_defaults)
        return {"protocol": "unknown", "decode_status": "raw"}
    except (DecodeError, UnicodeDecodeError, ValueError, struct.error, IndexError):
        return {"protocol": "unknown", "decode_status": "malformed"}
