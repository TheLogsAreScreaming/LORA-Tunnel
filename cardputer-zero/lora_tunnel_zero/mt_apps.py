"""Meshtastic application payload decoders (one function per port).

Each decoder reads a bounded protobuf body and returns structured fields plus
`details`: short (label, value) lines for the packet inspector. Field numbers
follow meshtastic/protobufs (mesh.proto, telemetry.proto, mqtt.proto,
paxcount.proto). Unknown or absent fields are left out, never invented.
"""

import math
import struct

from . import mt_names


class AppError(ValueError):
    pass


# ------------------------------------------------------------------ wire helpers
def _varint(data, pos):
    value = shift = 0
    while shift < 70:
        if pos >= len(data):
            raise AppError("Truncated varint")
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
        shift += 7
    raise AppError("Varint overflow")


def fields(data, limit=128):
    """Every field in order, as (number, wire, value); repeated fields are kept."""
    out, pos = [], 0
    while pos < len(data):
        if len(out) >= limit:
            raise AppError("Too many fields")
        tag, pos = _varint(data, pos)
        number, wire = tag >> 3, tag & 7
        if number < 1:
            raise AppError("Invalid tag")
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            if pos + size > len(data):
                raise AppError("Truncated fixed field")
            value, pos = data[pos:pos + size], pos + size
        elif wire == 2:
            size, pos = _varint(data, pos)
            if size > len(data) - pos:
                raise AppError("Truncated field")
            value, pos = data[pos:pos + size], pos + size
        else:
            raise AppError("Unsupported wire type")
        out.append((number, wire, value))
    return out


class Msg:
    """Read access to a decoded protobuf message: last scalar wins, repeated kept."""

    def __init__(self, data):
        self.items = fields(data)
        self.last = {}
        for number, wire, value in self.items:
            self.last[number] = (wire, value)

    def has(self, number):
        return number in self.last

    def uint(self, number):
        item = self.last.get(number)
        return item[1] if item and item[0] == 0 else None

    def int32(self, number):
        value = self.uint(number)
        if value is None:
            return None
        value &= 0xFFFFFFFFFFFFFFFF
        return value - (1 << 64) if value >= 1 << 63 else value

    def sint(self, number):
        value = self.uint(number)
        return None if value is None else (value >> 1) ^ -(value & 1)

    def boolean(self, number):
        value = self.uint(number)
        return None if value is None else bool(value)

    def fixed32(self, number):
        item = self.last.get(number)
        return int.from_bytes(item[1], "little") if item and item[0] == 5 else None

    def sfixed32(self, number):
        item = self.last.get(number)
        return struct.unpack("<i", item[1])[0] if item and item[0] == 5 else None

    def f32(self, number):
        item = self.last.get(number)
        if not item or item[0] != 5:
            return None
        value = struct.unpack("<f", item[1])[0]
        return value if math.isfinite(value) else None

    def raw(self, number):
        item = self.last.get(number)
        return item[1] if item and item[0] == 2 else None

    def text(self, number, limit=240):
        raw = self.raw(number)
        if raw is None:
            return None
        if len(raw) > limit:
            raise AppError("Oversize text")
        value = raw.decode("utf-8", "strict").rstrip("\x00")
        return "".join(c if c.isprintable() else "�" for c in value)

    def messages(self, number):
        return [Msg(value) for n, wire, value in self.items if n == number and wire == 2]

    def repeated_fixed32(self, number):
        out = []
        for n, wire, value in self.items:
            if n != number:
                continue
            if wire == 5:
                out.append(int.from_bytes(value, "little"))
            elif wire == 2 and len(value) % 4 == 0:
                out += [int.from_bytes(value[i:i + 4], "little") for i in range(0, len(value), 4)]
        return out

    def repeated_int32(self, number):
        out = []
        for n, wire, value in self.items:
            if n != number:
                continue
            values = [value] if wire == 0 else []
            if wire == 2:
                pos = 0
                while pos < len(value):
                    item, pos = _varint(value, pos)
                    values.append(item)
            for item in values:
                item &= 0xFFFFFFFFFFFFFFFF
                out.append(item - (1 << 64) if item >= 1 << 63 else item)
        return out


def node_name(number):
    if number in (None, 0):
        return None
    return "^all" if number == 0xFFFFFFFF else "!%08x" % number


def _position(lat_i, lon_i):
    if lat_i is None or lon_i is None:
        return None
    lat, lon = lat_i / 1e7, lon_i / 1e7
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise AppError("Invalid position")
    return {"latitude": lat, "longitude": lon, "source": "advertised"}


def _named(table, value):
    if value is None:
        return None
    return table.get(value, str(value))


def _fmt(value, digits=1):
    if isinstance(value, float):
        return ("%%.%df" % digits) % value
    return str(value)


# ------------------------------------------------------------------ ports
def text_port(label):
    def decode(body, data):
        msg_text = body.decode("utf-8", "strict").rstrip("\x00")
        if len(body) > 240:
            raise AppError("Oversize text")
        value = "".join(c if c.isprintable() or c in "\n\t" else "�" for c in msg_text)
        out = {"text": value}
        if label:
            out["text_kind"] = label
            out["details"] = [("Kind", label)]
        return out
    return decode


def position(body, data):
    m = Msg(body)
    out, details = {}, []
    pos = _position(m.sfixed32(1), m.sfixed32(2))
    if pos is not None:
        altitude = m.int32(3)
        if altitude is not None and -1000 <= altitude <= 100000:
            pos["altitude_m"] = altitude
        out["node_position"] = pos
    stamp = m.fixed32(4) or m.fixed32(7)
    if stamp:
        out["advertised_timestamp"] = stamp
    extra = {}
    for number, name in ((19, "sats_in_view"), (23, "precision_bits"), (18, "fix_type"), (17, "fix_quality")):
        value = m.uint(number)
        if value:
            extra[name] = value
    hdop = m.uint(12) or m.uint(11)
    if hdop:
        extra["dop"] = hdop / 100
    speed = m.uint(15)
    if speed is not None:
        extra["ground_speed_ms"] = speed
    track = m.uint(16)
    if track is not None:
        extra["ground_track_deg"] = track / 1e5
    source = m.uint(5)
    if source:
        extra["location_source"] = {1: "manual", 2: "internal GPS", 3: "external GPS"}.get(source, str(source))
    if extra:
        out["position_info"] = extra
        if "sats_in_view" in extra:
            details.append(("Satellites", str(extra["sats_in_view"])))
        if "precision_bits" in extra and extra["precision_bits"] < 32:
            # Meshtastic truncates coordinates to this many bits; 32 is full precision.
            details.append(("Precision", "%d bits (position is deliberately blurred)" % extra["precision_bits"]))
        if "ground_speed_ms" in extra:
            details.append(("Speed", "%d m/s" % extra["ground_speed_ms"]))
        if "location_source" in extra:
            details.append(("Source", extra["location_source"]))
    out["details"] = details
    return out


def nodeinfo(body, data):
    m = Msg(body)
    out, details = {}, []
    for number, name, limit in ((1, "user_id", 16), (2, "name", 80), (3, "short_name", 16)):
        value = m.text(number, limit)
        if value is not None:
            out[name] = value
    role = m.uint(7) or 0
    out["role"] = role
    out["node_type"] = mt_names.ROLES.get(role, str(role)).lower()
    model = m.uint(5)
    if model is not None:
        out["hardware_model"] = model
        out["hardware_name"] = _named(mt_names.HW_MODELS, model)
        details.append(("Hardware", out["hardware_name"]))
    key = m.raw(8)
    if key and len(key) == 32:
        out["public_key"] = key.hex()
        details.append(("Public key", key.hex()[:16] + "…"))
    if m.boolean(6):
        out["is_licensed"] = True
        details.append(("Licensed", "yes (ham mode, unencrypted)"))
    if m.boolean(9):
        out["is_unmessagable"] = True
    out["details"] = details
    return out


ROUTING_ERRORS = {0: "none", 1: "no route", 2: "got NAK", 3: "timeout", 4: "no interface",
                  5: "max retransmit", 6: "no channel", 7: "too large", 8: "no response",
                  9: "duty cycle limit", 32: "bad request", 33: "not authorized", 34: "PKI failed",
                  35: "PKI unknown public key", 36: "admin bad session key",
                  37: "admin public key unauthorized", 38: "rate limit exceeded",
                  39: "PKI send failed (public key)"}


def _route_discovery(m, prefix):
    out = {}
    route = [node_name(n) for n in m.repeated_fixed32(1)]
    back = [node_name(n) for n in m.repeated_fixed32(3)]
    snr = [s / 4 if s != -128 else None for s in m.repeated_int32(2)]
    snr_back = [s / 4 if s != -128 else None for s in m.repeated_int32(4)]
    out[prefix + "route"] = route
    if snr:
        out[prefix + "snr_towards"] = snr
    if back:
        out[prefix + "route_back"] = back
    if snr_back:
        out[prefix + "snr_back"] = snr_back
    return out


def _hops_text(source, route, snr, destination):
    hops = [source or "?"] + list(route) + [destination or "?"]
    parts = []
    for i, node in enumerate(hops):
        parts.append(node)
        if i < len(hops) - 1 and i < len(snr) and snr[i] is not None:
            parts.append("(%+.1f dB)" % snr[i])
    return " → ".join(p for p in parts)


def routing(body, data):
    m = Msg(body)
    out, details = {}, []
    if m.has(3):
        code = m.uint(3) or 0
        out["routing_error"] = ROUTING_ERRORS.get(code, str(code))
        out["routing_kind"] = "ack" if code == 0 else "nak"
        details.append(("Routing", "ACK" if code == 0 else "Failed: " + out["routing_error"]))
    for number, kind in ((1, "route_request"), (2, "route_reply")):
        raw = m.raw(number)
        if raw is not None:
            out["routing_kind"] = kind
            out.update(_route_discovery(Msg(raw), ""))
            details.append(("Routing", kind.replace("_", " ")))
    if data.get("request_id"):
        details.append(("Answers", "packet %08x" % data["request_id"]))
    out["details"] = details
    return out


def traceroute(body, data):
    m = Msg(body)
    out = _route_discovery(m, "")
    details = []
    source, destination = data.get("source_name"), data.get("destination_name")
    if data.get("request_id"):
        out["traceroute_kind"] = "reply"
        # A reply travels back: the original requester is this packet's destination.
        details.append(("Route there", _hops_text(destination, out.get("route", []),
                                                   out.get("snr_towards", []), source)))
        if out.get("route_back") or out.get("snr_back"):
            details.append(("Route back", _hops_text(source, out.get("route_back", []),
                                                      out.get("snr_back", []), destination)))
    else:
        out["traceroute_kind"] = "request"
        details.append(("Traceroute", "request to %s, %d hops so far" % (destination or "?",
                                                                          len(out.get("route", [])))))
    out["details"] = details
    return out


def neighborinfo(body, data):
    m = Msg(body)
    neighbors = []
    for item in m.messages(4)[:32]:
        number = item.uint(1)
        if not number:
            continue
        snr = item.f32(2)
        neighbors.append({"id": node_name(number), "snr": round(snr, 2) if snr is not None else None})
    out = {"neighbors": neighbors}
    if m.uint(1):
        out["reporting_node"] = node_name(m.uint(1))
    interval = m.uint(3)
    if interval:
        out["broadcast_interval_s"] = interval
    details = [("Neighbors", "%d heard directly" % len(neighbors))]
    for item in neighbors[:12]:
        details.append(("", "%s  SNR %s dB" % (item["id"], _fmt(item["snr"]) if item["snr"] is not None else "?")))
    out["details"] = details
    return out


def waypoint(body, data):
    m = Msg(body)
    out = {"waypoint_id": m.uint(1) or 0}
    pos = _position(m.sfixed32(2), m.sfixed32(3))
    name, description = m.text(6, 64), m.text(7, 160)
    details = [("Waypoint", name or "(unnamed)")]
    if pos:
        out["waypoint_position"] = pos
        details.append(("At", "%.5f, %.5f" % (pos["latitude"], pos["longitude"])))
    if name:
        out["waypoint_name"] = name
    if description:
        out["waypoint_description"] = description
        details.append(("Note", description))
    icon = m.fixed32(8)
    if icon:
        try:
            out["waypoint_icon"] = chr(icon)
        except (ValueError, OverflowError):
            pass
    expire = m.uint(4)
    if expire:
        out["waypoint_expires"] = expire
    if m.uint(5):
        out["waypoint_locked_to"] = node_name(m.uint(5))
    out["details"] = details
    return out


def paxcounter(body, data):
    m = Msg(body)
    out = {"paxcounter": {"wifi": m.uint(1) or 0, "ble": m.uint(2) or 0, "uptime_seconds": m.uint(3) or 0}}
    out["details"] = [("People nearby", "%d Wi-Fi, %d BLE devices" % (out["paxcounter"]["wifi"],
                                                                     out["paxcounter"]["ble"]))]
    return out


def map_report(body, data):
    m = Msg(body)
    report = {}
    for number, name, limit in ((1, "name", 80), (2, "short_name", 16), (5, "firmware_version", 32)):
        value = m.text(number, limit)
        if value:
            report[name] = value
    role, model, region, preset = m.uint(3) or 0, m.uint(4), m.uint(6), m.uint(7)
    report["node_type"] = mt_names.ROLES.get(role, str(role)).lower()
    if model is not None:
        report["hardware_model"] = model
        report["hardware_name"] = _named(mt_names.HW_MODELS, model)
    if region is not None:
        report["region"] = _named(mt_names.REGIONS, region)
    if preset is not None:
        report["modem_preset"] = _named(mt_names.MODEM_PRESETS, preset)
    if m.boolean(8) is not None:
        report["has_default_channel"] = m.boolean(8)
    online = m.uint(13)
    if online is not None:
        report["online_local_nodes"] = online
    out = {k: report[k] for k in ("name", "short_name", "node_type", "hardware_model", "hardware_name")
           if k in report}
    pos = _position(m.sfixed32(9), m.sfixed32(10))
    if pos:
        altitude = m.int32(11)
        if altitude is not None and -1000 <= altitude <= 100000:
            pos["altitude_m"] = altitude
        out["node_position"] = pos
    out["map_report"] = report
    details = []
    for label, key in (("Firmware", "firmware_version"), ("Hardware", "hardware_name"), ("Region", "region"),
                       ("Preset", "modem_preset"), ("Nodes online", "online_local_nodes")):
        if key in report:
            details.append((label, str(report[key])))
    out["details"] = details
    return out


# Telemetry sub-messages: (field, name, kind, unit, display label)
_TELEMETRY = {
    2: ("device", [(1, "battery_percent", "u", "%", "Battery"), (2, "voltage", "f", "V", "Voltage"),
                   (3, "channel_utilization", "f", "%", "Ch. util"), (4, "air_util_tx", "f", "%", "Airtime"),
                   (5, "uptime_seconds", "u", "s", "Uptime")]),
    3: ("environment", [(1, "temperature_c", "f", "°C", "Temperature"), (2, "humidity", "f", "%", "Humidity"),
                        (3, "pressure_hpa", "f", "hPa", "Pressure"), (4, "gas_resistance", "f", "MΩ", "Gas"),
                        (5, "env_voltage", "f", "V", "Voltage"), (6, "env_current", "f", "mA", "Current"),
                        (7, "iaq", "u", "", "IAQ"), (8, "distance_mm", "f", "mm", "Distance"),
                        (9, "lux", "f", "lx", "Light"), (12, "uv_lux", "f", "lx", "UV"),
                        (13, "wind_direction", "u", "°", "Wind dir"), (14, "wind_speed", "f", "m/s", "Wind"),
                        (16, "wind_gust", "f", "m/s", "Gust"), (15, "weight_kg", "f", "kg", "Weight"),
                        (18, "radiation", "f", "µR/h", "Radiation"), (19, "rain_1h_mm", "f", "mm", "Rain 1h"),
                        (20, "rain_24h_mm", "f", "mm", "Rain 24h"), (21, "soil_moisture", "u", "%", "Soil"),
                        (22, "soil_temperature_c", "f", "°C", "Soil temp"),
                        (40, "lightning_1h", "u", "", "Lightning 1h"),
                        (41, "lightning_km", "f", "km", "Lightning")]),
    4: ("air_quality", [(2, "pm25", "u", "µg/m³", "PM2.5"), (1, "pm10", "u", "µg/m³", "PM1.0"),
                        (3, "pm100", "u", "µg/m³", "PM10"), (13, "co2_ppm", "u", "ppm", "CO₂"),
                        (23, "voc_index", "f", "", "VOC")]),
    5: ("power", [(1, "ch1_voltage", "f", "V", "Ch1"), (2, "ch1_current", "f", "mA", "Ch1"),
                  (3, "ch2_voltage", "f", "V", "Ch2"), (4, "ch2_current", "f", "mA", "Ch2"),
                  (5, "ch3_voltage", "f", "V", "Ch3"), (6, "ch3_current", "f", "mA", "Ch3")]),
    6: ("local_stats", [(1, "uptime_seconds", "u", "s", "Uptime"), (2, "channel_utilization", "f", "%", "Ch. util"),
                        (3, "air_util_tx", "f", "%", "Airtime"), (4, "packets_tx", "u", "", "TX"),
                        (5, "packets_rx", "u", "", "RX"), (6, "packets_rx_bad", "u", "", "RX bad"),
                        (7, "nodes_online", "u", "", "Online"), (8, "nodes_total", "u", "", "Nodes"),
                        (9, "rx_dupes", "u", "", "Dupes"), (10, "tx_relays", "u", "", "Relays"),
                        (15, "noise_floor_dbm", "i", "dBm", "Noise")]),
    7: ("health", [(1, "heart_bpm", "u", "bpm", "Heart"), (2, "spo2", "u", "%", "SpO₂"),
                   (3, "body_temperature_c", "f", "°C", "Body temp")]),
    8: ("host", [(1, "uptime_seconds", "u", "s", "Uptime"), (6, "load1", "u", "", "Load")]),
}


def _duration(seconds):
    seconds = int(seconds)
    if seconds >= 86400:
        return "%dd %dh" % (seconds // 86400, seconds % 86400 // 3600)
    if seconds >= 3600:
        return "%dh %dm" % (seconds // 3600, seconds % 3600 // 60)
    return "%dm" % (seconds // 60)


def telemetry(body, data):
    m = Msg(body)
    metrics, details, kinds = {}, [], []
    for number, (kind, spec) in _TELEMETRY.items():
        raw = m.raw(number)
        if raw is None:
            continue
        kinds.append(kind)
        sub = Msg(raw)
        line = []
        for field, name, typ, unit, label in spec:
            value = {"u": sub.uint, "f": sub.f32, "i": sub.int32}[typ](field)
            if value is None:
                continue
            if kind == "environment" and name == "pressure_hpa" and value > 2000:
                value /= 100  # some sensors report pascals
            metrics[name] = round(value, 3) if isinstance(value, float) else value
            if name == "uptime_seconds":
                line.append("%s %s" % (label, _duration(value)))
            elif name == "battery_percent" and value > 100:
                line.append("External power")
            else:
                line.append("%s %s%s" % (label, _fmt(value), unit))
        if line:
            details.append((kind.replace("_", " ").title(), ", ".join(line)))
    if not kinds:
        raise AppError("Empty telemetry")
    out = {"telemetry": metrics, "telemetry_kind": kinds[0], "details": details}
    stamp = m.fixed32(1)
    if stamp:
        out["advertised_timestamp"] = stamp
    return out


def store_forward(body, data):
    m = Msg(body)
    request = m.uint(1)
    names = {1: "router error", 2: "router heartbeat", 3: "router ping", 4: "router pong", 5: "router busy",
             6: "router history", 7: "router stats", 8: "router text direct", 9: "router text broadcast",
             64: "client error", 65: "client history", 66: "client stats", 67: "client ping",
             68: "client pong", 106: "client abort"}
    kind = names.get(request, "request %s" % request)
    out = {"store_forward": kind, "details": [("Store & Forward", kind)]}
    if request in (8, 9):
        text = m.text(5)
        if text:
            out["text"] = text
    return out


def labelled(label):
    def decode(body, data):
        return {"details": [("App", label)]}
    return decode


DECODERS = {
    1: text_port(None), 3: position, 4: nodeinfo, 5: routing, 8: waypoint,
    10: text_port("detection sensor"), 11: text_port("alert"), 32: text_port("reply"),
    34: paxcounter, 65: store_forward, 66: text_port("range test"), 67: telemetry,
    70: traceroute, 71: neighborinfo, 73: map_report,
    6: labelled("Admin (remote configuration)"), 7: labelled("Compressed text (not decoded)"),
    9: labelled("Audio"), 72: labelled("ATAK plugin"), 78: labelled("ATAK plugin"),
    257: labelled("ATAK forwarder"),
}
