"""Every Meshtastic application decoder and the extended MeshCore payload types.

Frames are built with the app's own encoders (mesh_tx) and small protobuf
helpers, encrypted on the default channel, and decoded through decode_packet.
"""

import hashlib
import hmac
import struct
import unittest

from lora_tunnel_zero import mesh_tx
from lora_tunnel_zero.decode import DEFAULT_MESHTASTIC_KEY, PUBLIC_MESHCORE_KEY, decode_packet
from lora_tunnel_zero.mesh_tx import _bytes_field, _uint_field, _varint
from lora_tunnel_zero.profiles import meshcore, meshtastic

MT = meshtastic("US")
MC = meshcore("US", "AUTO")
SRC, DST = 0x1A2B3C4D, 0x55667788


def fixed32(number, value):
    return _varint(number << 3 | 5) + struct.pack("<I", value & 0xFFFFFFFF)


def sfixed32(number, value):
    return _varint(number << 3 | 5) + struct.pack("<i", value)


def f32(number, value):
    return _varint(number << 3 | 5) + struct.pack("<f", value)


def int32(number, value):
    return _uint_field(number, value & 0xFFFFFFFFFFFFFFFF)


def mt(port, body, *, request_id=None, destination=mesh_tx.BROADCAST):
    data = _uint_field(1, port) + _bytes_field(2, body)
    if request_id:
        data += fixed32(6, request_id)
    raw = header_frame(data, destination)
    out = decode_packet(raw, MT)
    assert out["decode_status"] == "decoded", out
    return out


def header_frame(data, destination):
    key, name = DEFAULT_MESHTASTIC_KEY, "LongFast"
    packet_id = 0x01020304
    header = struct.pack("<IIIBBBB", destination, SRC, packet_id, 3 | 3 << 5,
                         mesh_tx.meshtastic_channel_hash(name, key), 0, SRC & 0xFF)
    return header + mesh_tx._encrypt_ctr(key, struct.pack("<QII", packet_id, SRC, 0), data)


class MeshtasticAppTests(unittest.TestCase):
    def test_position_extras(self):
        body = (sfixed32(1, 377749000) + sfixed32(2, -1224194000) + int32(3, 52) + _uint_field(19, 9)
                + _uint_field(23, 13) + _uint_field(15, 4) + _uint_field(5, 2))
        d = mt(3, body)
        self.assertAlmostEqual(d["node_position"]["latitude"], 37.7749)
        self.assertEqual(d["node_position"]["altitude_m"], 52)
        self.assertEqual(d["position_info"]["sats_in_view"], 9)
        self.assertEqual(d["position_info"]["precision_bits"], 13)
        self.assertIn(("Precision", "13 bits (position is deliberately blurred)"), d["details"])

    def test_nodeinfo_names_hardware_and_key(self):
        body = (_bytes_field(1, b"!1a2b3c4d") + _bytes_field(2, "Hilltop Rptr".encode()) + _bytes_field(3, b"HTR")
                + _uint_field(5, 43) + _uint_field(7, 2) + _bytes_field(8, bytes(range(32))))
        d = mt(4, body)
        self.assertEqual((d["name"], d["short_name"], d["node_type"]), ("Hilltop Rptr", "HTR", "router"))
        self.assertEqual(d["hardware_name"], "HELTEC_V3")
        self.assertEqual(d["public_key"], bytes(range(32)).hex())

    def test_routing_ack_and_error(self):
        ack = mt(5, _uint_field(3, 0), request_id=0xDEADBEEF)
        self.assertEqual((ack["routing_kind"], ack["request_id"]), ("ack", 0xDEADBEEF))
        nak = mt(5, _uint_field(3, 1))
        self.assertEqual((nak["routing_kind"], nak["routing_error"]), ("nak", "no route"))

    def test_traceroute_reply_with_snr_both_ways(self):
        route = struct.pack("<II", 0x11111111, 0x22222222)
        body = (_bytes_field(1, route) + _bytes_field(2, b"".join(_varint(x & 0xFFFFFFFFFFFFFFFF)
                                                                   for x in (24, -8, 12)))
                + _bytes_field(3, struct.pack("<I", 0x33333333)) + _bytes_field(4, _varint(40) + _varint(20)))
        d = mt(70, body, request_id=0x99, destination=DST)
        self.assertEqual(d["traceroute_kind"], "reply")
        self.assertEqual(d["route"], ["!11111111", "!22222222"])
        self.assertEqual(d["snr_towards"], [6.0, -2.0, 3.0])
        self.assertEqual(d["route_back"], ["!33333333"])
        there = dict(d["details"])["Route there"]
        self.assertEqual(there, "!55667788 → (+6.0 dB) → !11111111 → (-2.0 dB) → !22222222 → (+3.0 dB) → !1a2b3c4d")

    def test_traceroute_request(self):
        d = mt(70, b"", destination=DST)
        self.assertEqual(d["traceroute_kind"], "request")

    def test_neighborinfo(self):
        n1 = _uint_field(1, 0xAAAA0001) + f32(2, 7.25)
        n2 = _uint_field(1, 0xAAAA0002) + f32(2, -3.5)
        body = _uint_field(1, SRC) + _uint_field(3, 900) + _bytes_field(4, n1) + _bytes_field(4, n2)
        d = mt(71, body)
        self.assertEqual(d["neighbors"], [{"id": "!aaaa0001", "snr": 7.25}, {"id": "!aaaa0002", "snr": -3.5}])
        self.assertEqual(d["broadcast_interval_s"], 900)

    def test_waypoint(self):
        body = (_uint_field(1, 7) + sfixed32(2, 400000000) + sfixed32(3, -740000000) + _bytes_field(6, b"Camp")
                + _bytes_field(7, b"meet here") + fixed32(8, ord("⛺")))
        d = mt(8, body)
        self.assertEqual((d["waypoint_name"], d["waypoint_description"], d["waypoint_icon"]),
                         ("Camp", "meet here", "⛺"))
        self.assertAlmostEqual(d["waypoint_position"]["longitude"], -74.0)

    def test_telemetry_every_kind(self):
        env = f32(1, 21.5) + f32(2, 40.0) + f32(3, 1013.2) + _uint_field(7, 55)
        air = _uint_field(2, 12) + _uint_field(13, 640)
        power = f32(1, 12.6) + f32(2, 250.0)
        stats = _uint_field(4, 10) + _uint_field(5, 99) + _uint_field(7, 14) + int32(15, -112)
        device = _uint_field(1, 87) + f32(2, 4.01) + f32(3, 12.5) + _uint_field(5, 7200)
        cases = {2: device, 3: env, 4: air, 5: power, 6: stats}
        expected = {2: {"battery_percent": 87, "uptime_seconds": 7200},
                    3: {"temperature_c": 21.5, "humidity": 40.0, "iaq": 55},
                    4: {"pm25": 12, "co2_ppm": 640},
                    5: {"ch1_voltage": 12.6, "ch1_current": 250.0},
                    6: {"packets_rx": 99, "nodes_online": 14, "noise_floor_dbm": -112}}
        for field, sub in cases.items():
            d = mt(67, fixed32(1, 1700000000) + _bytes_field(field, sub))
            for key, value in expected[field].items():
                self.assertAlmostEqual(d["telemetry"][key], value, places=2, msg=(field, key))
            self.assertTrue(d["details"])

    def test_paxcounter_map_report_and_text_kinds(self):
        pax = mt(34, _uint_field(1, 23) + _uint_field(2, 41) + _uint_field(3, 600))
        self.assertEqual(pax["paxcounter"], {"wifi": 23, "ble": 41, "uptime_seconds": 600})
        report = (_bytes_field(1, b"Base Camp") + _bytes_field(2, b"BASE") + _uint_field(3, 2) + _uint_field(4, 9)
                  + _bytes_field(5, b"2.7.15") + _uint_field(6, 1) + _uint_field(7, 0) + _uint_field(8, 1)
                  + sfixed32(9, 377000000) + sfixed32(10, -1224000000) + _uint_field(13, 31))
        d = mt(73, report)
        self.assertEqual(d["name"], "Base Camp")
        self.assertEqual(d["map_report"]["region"], "US")
        self.assertEqual(d["map_report"]["modem_preset"], "LONG_FAST")
        self.assertEqual(d["map_report"]["online_local_nodes"], 31)
        self.assertEqual(d["hardware_name"], "RAK4631")
        self.assertAlmostEqual(d["node_position"]["latitude"], 37.7)
        for port, kind in ((10, "detection sensor"), (11, "alert"), (66, "range test")):
            out = mt(port, b"seq 42")
            self.assertEqual((out["text"], out["text_kind"]), ("seq 42", kind))

    def test_malformed_optional_app_keeps_the_packet(self):
        d = mt(71, b"\x22\xff")  # neighbors field claims 255 bytes
        self.assertEqual(d["port_name"], "neighborinfo")
        self.assertIn("app_decode_error", d)

    def test_unknown_port_is_named(self):
        d = mt(76, b"\x01\x02")
        self.assertEqual(d["port_name"], "reticulum")


def mc_frame(kind, payload, path=b"", route=1):
    return bytes([(kind << 2) | route, len(path)]) + path + payload


def group(key, plain, kind=5):
    plain += b"\x00" * (-len(plain) % 16)
    cipher = mesh_tx._encrypt_ecb(key[:16], plain)
    mac = hmac.new(key, cipher, hashlib.sha256).digest()[:2]
    return mc_frame(kind, bytes([hashlib.sha256(key).digest()[0]]) + mac + cipher)


class MeshCoreTypeTests(unittest.TestCase):
    def test_signed_and_cli_group_text(self):
        signed = decode_packet(group(PUBLIC_MESHCORE_KEY, struct.pack("<I", 5) + bytes([2 << 2 | 1])
                                     + b"\xaa\xbb\xcc\xdd" + b"Kal: hi"), MC)
        self.assertEqual((signed["text_type"], signed["sender_prefix"], signed["text"], signed["attempt"]),
                         ("signed", "aabbccdd", "Kal: hi", 2))
        cli = decode_packet(group(PUBLIC_MESHCORE_KEY, struct.pack("<I", 5) + bytes([1 << 2]) + b"ver"), MC)
        self.assertEqual(cli["text_type"], "cli")

    def test_group_data(self):
        d = decode_packet(group(PUBLIC_MESHCORE_KEY, struct.pack("<HB", 0x1234, 3) + b"abc", kind=6), MC)
        self.assertEqual((d["data_type"], d["data_hex"]), (0x1234, "616263"))

    def test_ack_trace_multipart_custom(self):
        self.assertEqual(decode_packet(mc_frame(3, b"\x01\x02\x03\x04"), MC)["ack_crc"], "01020304")
        trace = decode_packet(mc_frame(9, b"\x10\x20\x30\x40" + b"\x00" * 4 + b"\x00" + b"\xa1\xb2\xc3",
                                       path=bytes([40, 0xF8]), route=2), MC)
        self.assertEqual(trace["trace_route"], ["a1", "b2", "c3"])
        self.assertEqual(trace["trace_snr"], [10.0, -2.0])
        multi = decode_packet(mc_frame(10, bytes([2 << 4 | 3]) + b"\x09\x08\x07\x06"), MC)
        self.assertEqual((multi["multipart_remaining"], multi["multipart_type"], multi["ack_crc"]),
                         (2, "ack", "09080706"))
        self.assertIn("details", decode_packet(mc_frame(15, b"\x00" * 6), MC))

    def test_discovery_and_anonymous_request(self):
        req = decode_packet(mc_frame(11, bytes([0x80, 0b100]) + b"\x01\x02\x03\x04"), MC)
        self.assertEqual((req["control"], req["discover_types"]), ("discover_request", ["repeater"]))
        key = bytes(range(32))
        resp = decode_packet(mc_frame(11, bytes([0x92, 0xF4]) + b"\x01\x02\x03\x04" + key), MC)
        self.assertEqual((resp["control"], resp["node_type"], resp["reported_snr"]),
                         ("discover_response", "repeater", -3.0))
        self.assertEqual(resp["discovered_key"], key.hex())
        anon = decode_packet(mc_frame(7, b"\x5a" + key + b"\x00\x00" + bytes(16)), MC)
        self.assertEqual((anon["destination_hash"], anon["sender_public_key"]), ("5a", key.hex()))


if __name__ == "__main__":
    unittest.main()
