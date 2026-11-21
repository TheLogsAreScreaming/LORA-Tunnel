"""Offline exports from a closed session: nodes.csv, nodes.kml and packets.csv."""

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from xml.sax.saxutils import escape


def _iso(stamp):
    try:
        return datetime.fromtimestamp(float(stamp), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _connect(directory):
    path = Path(directory) / "capture.sqlite3"
    if not path.is_file():
        raise ValueError("This session has no capture database")
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)


def export_session(directory):
    """Write the three files into <session>/export/ and return their paths."""
    directory = Path(directory)
    out = directory / "export"
    out.mkdir(mode=0o700, exist_ok=True)
    db = _connect(directory)
    try:
        nodes = []
        for protocol, node, first, last, count, best, latest in db.execute(
                "SELECT protocol,node_id,first_seen,last_seen,sightings,best_rssi,latest_json FROM devices"
                " ORDER BY last_seen DESC"):
            record = json.loads(latest)
            decoded = record.get("decoded", {})
            position = decoded.get("node_position") or {}
            nodes.append({
                "protocol": protocol, "node_id": node, "name": decoded.get("name", ""),
                "short_name": decoded.get("short_name", ""), "node_type": decoded.get("node_type", ""),
                "first_seen": _iso(first), "last_seen": _iso(last), "packets": count,
                "best_rssi_dbm": best, "advertised_lat": position.get("latitude", ""),
                "advertised_lon": position.get("longitude", ""),
                "profile": record.get("profile", {}).get("id", ""),
            })
        # Receiver position at each node's strongest reception, when a fix existed.
        for item in nodes:
            row = db.execute("SELECT latitude,longitude FROM observations WHERE protocol=? AND node_id=?"
                             " AND latitude IS NOT NULL ORDER BY rssi DESC LIMIT 1",
                             (item["protocol"], item["node_id"])).fetchone()
            item["receiver_lat"], item["receiver_lon"] = row if row else ("", "")
        fields = ["protocol", "node_id", "name", "short_name", "node_type", "first_seen", "last_seen",
                  "packets", "best_rssi_dbm", "advertised_lat", "advertised_lon", "receiver_lat",
                  "receiver_lon", "profile"]
        with (out / "nodes.csv").open("w", newline="", encoding="utf8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(nodes)

        with (out / "packets.csv").open("w", newline="", encoding="utf8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["time_utc", "profile", "protocol", "node_id", "decode_status", "type",
                             "rssi_dbm", "snr_db", "receiver_lat", "receiver_lon", "text", "raw_hex"])
            for stamp, profile, protocol, node, rssi, snr, lat, lon, record_json in db.execute(
                    "SELECT received_at,profile,protocol,node_id,rssi,snr,latitude,longitude,record_json"
                    " FROM observations ORDER BY id"):
                record = json.loads(record_json)
                decoded = record.get("decoded", {})
                writer.writerow([_iso(stamp), profile, protocol, node or "", decoded.get("decode_status", ""),
                                 decoded.get("port_name") or decoded.get("payload_name") or "",
                                 rssi, snr, "" if lat is None else lat, "" if lon is None else lon,
                                 decoded.get("text", ""), record.get("raw_hex", "")])
    finally:
        db.close()

    placemarks = []
    for item in nodes:
        label = item["name"] or item["short_name"] or item["node_id"]
        detail = "%s %s, %s packets, best %s dBm" % (item["protocol"], item["node_id"], item["packets"],
                                                      item["best_rssi_dbm"])
        for kind, lat, lon in (("advertised", item["advertised_lat"], item["advertised_lon"]),
                               ("heard from here", item["receiver_lat"], item["receiver_lon"])):
            if lat == "" or lon == "":
                continue
            placemarks.append(
                "<Placemark><name>%s</name><description>%s</description><styleUrl>#%s</styleUrl>"
                "<Point><coordinates>%f,%f,0</coordinates></Point></Placemark>"
                % (escape("%s (%s)" % (label, kind)), escape(detail),
                   "adv" if kind == "advertised" else "rx", float(lon), float(lat)))
    kml = ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           "<name>LORA Tunnel %s</name>"
           '<Style id="adv"><IconStyle><color>ff4dff4d</color></IconStyle></Style>'
           '<Style id="rx"><IconStyle><color>ffffd640</color></IconStyle></Style>%s</Document></kml>\n'
           % (escape(directory.name), "".join(placemarks)))
    (out / "nodes.kml").write_text(kml, encoding="utf8")
    return [out / "nodes.csv", out / "nodes.kml", out / "packets.csv"]


def export_recon(directory):
    """Wi-Fi/BLE session: devices.csv (every device, best signal and where) and flagged.kml."""
    directory = Path(directory)
    source = directory / "recon.jsonl"
    if not source.is_file():
        raise ValueError("This session has no Wi-Fi/BLE log")
    devices = {}
    with source.open(encoding="utf8", errors="replace") as stream:
        for line in stream:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if not isinstance(item, dict) or "address" not in item:
                continue
            key = (item.get("transport"), item["address"])
            entry = devices.setdefault(key, {"transport": item.get("transport"), "address": item["address"],
                                             "first_seen": item.get("timestamp"), "sightings": 0,
                                             "best_rssi_dbm": None, "lat": "", "lon": ""})
            entry["sightings"] += 1
            entry["last_seen"] = item.get("timestamp")
            entry["name"] = item.get("ssid") or item.get("name") or entry.get("name", "")
            for field in ("channel", "security", "address_type"):
                if item.get(field) is not None:
                    entry[field] = item[field]
            cls = item.get("classification") or {}
            if item.get("shown") and cls.get("category"):
                entry.update(category=cls.get("category"), label=cls.get("label", ""),
                             confidence=cls.get("confidence_name", ""), evidence=cls.get("evidence", ""))
            if item.get("following"):
                entry["following"] = True
            rssi, gps = item.get("rssi_dbm"), item.get("receiver_gps") or {}
            if isinstance(rssi, (int, float)) and (entry["best_rssi_dbm"] is None or rssi > entry["best_rssi_dbm"]):
                entry["best_rssi_dbm"] = rssi
                if gps.get("valid"):
                    entry["lat"], entry["lon"] = gps.get("latitude", ""), gps.get("longitude", "")
    out = directory / "export"
    out.mkdir(mode=0o700, exist_ok=True)
    fields = ["transport", "address", "name", "category", "label", "confidence", "evidence", "following",
              "first_seen", "last_seen", "sightings", "best_rssi_dbm", "lat", "lon", "channel", "security",
              "address_type"]
    rows = sorted(devices.values(), key=lambda d: (not d.get("category"), -(d["best_rssi_dbm"] or -999)))
    with (out / "devices.csv").open("w", newline="", encoding="utf8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row, first_seen=_iso(row.get("first_seen")), last_seen=_iso(row.get("last_seen"))))
    placemarks = []
    for row in rows:
        if not row.get("category") or row["lat"] == "":
            continue
        name = "%s %s" % (row.get("label") or row["category"], row.get("name") or row["address"])
        detail = "%s %s, %s, best %s dBm%s" % (row["transport"], row["address"], row.get("evidence", ""),
                                              row["best_rssi_dbm"], ", FOLLOWING" if row.get("following") else "")
        placemarks.append("<Placemark><name>%s</name><description>%s</description>"
                          "<Point><coordinates>%f,%f,0</coordinates></Point></Placemark>"
                          % (escape(name), escape(detail), float(row["lon"]), float(row["lat"])))
    kml = ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           "<name>LORA Tunnel Recon %s</name>%s</Document></kml>\n" % (escape(directory.name), "".join(placemarks)))
    (out / "flagged.kml").write_text(kml, encoding="utf8")
    files = [out / "devices.csv", out / "flagged.kml"]
    if (directory / "wigle.csv").is_file():
        files.append(directory / "wigle.csv")
    return files
