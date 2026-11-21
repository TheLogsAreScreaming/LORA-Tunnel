"""Session folders and durable sinks: JSONL, SQLite and LoRaTAP PCAP.

Every received frame is stored with its raw bytes and the exact receive-time
radio settings, including frames the decoder can't interpret. Adapted from
Evil-LORA-Tunnel, copyright 2026 Valleytech Solutions, MIT license.
"""

import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import uuid

from .loratap import PCAPWriter

SCHEMA_VERSION = 1
MIN_FREE_BYTES = 16 * 1024 * 1024


def atomic_json(path, data, *, durable=True):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="." + path.name + "-")
    try:
        with os.fdopen(fd, "w", encoding="utf8") as stream:
            json.dump(data, stream, ensure_ascii=True, allow_nan=False, indent=1)
            stream.write("\n")
            if durable:
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def create_session(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if shutil.disk_usage(root).free < MIN_FREE_BYTES:
        raise RuntimeError("Storage has less than 16 MiB free")
    name = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:6]
    directory = root / name
    directory.mkdir(mode=0o700)
    atomic_json(directory / "session.json", {
        "schema_version": SCHEMA_VERSION, "status": "created", "created_at": time.time(),
        "app": "lora-tunnel-zero",
        "time_source": "system clock; receiver UTC recorded separately",
    })
    return directory.resolve()


def read_metadata(directory):
    path = Path(directory) / "session.json"
    if not path.is_file() or path.stat().st_size > 262144:
        raise ValueError("Missing or invalid session metadata")
    data = json.loads(path.read_text(encoding="utf8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported session schema")
    return data


def list_sessions(root):
    root = Path(root)
    if not root.is_dir():
        return []
    result = []
    for meta in sorted(root.glob("*/session.json"), reverse=True):
        if meta.is_symlink() or meta.parent.is_symlink():
            continue
        try:
            result.append((meta.parent, read_metadata(meta.parent)))
        except (OSError, ValueError):
            continue
    return result


def node_id(decoded):
    node = decoded.get("source_id")
    if isinstance(node, str) and 0 < len(node) <= 128:
        # MeshCore identities are only trusted from validly signed adverts.
        if decoded.get("protocol") == "meshcore" and decoded.get("signature_valid") is not True:
            return None
        return node
    return None


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.pcap = PCAPWriter(self.directory / "lora.pcap")
        self.db = sqlite3.connect(self.directory / "capture.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY, received_at REAL NOT NULL, profile TEXT,
                protocol TEXT, node_id TEXT, rssi REAL, snr REAL, latitude REAL, longitude REAL,
                raw BLOB NOT NULL, record_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS devices (
                protocol TEXT NOT NULL, node_id TEXT NOT NULL,
                first_seen REAL NOT NULL, last_seen REAL NOT NULL, sightings INTEGER NOT NULL,
                best_rssi REAL, latest_json TEXT NOT NULL, PRIMARY KEY(protocol, node_id));
            CREATE INDEX IF NOT EXISTS devices_last_seen ON devices(last_seen DESC);
            PRAGMA user_version=1;
        """)
        self.stream = (self.directory / "observations.jsonl").open("a", encoding="utf8", buffering=65536)
        os.chmod(self.directory / "observations.jsonl", 0o600)
        self.count = 0

    def append(self, record):
        raw = bytes.fromhex(record["raw_hex"])
        if not 1 <= len(raw) <= 255:
            raise ValueError("Invalid radio packet length")
        record = dict(record, schema_version=SCHEMA_VERSION)
        text = json.dumps(record, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        if len(text) > 32768:
            raise ValueError("Observation exceeded size limit")
        decoded = record.get("decoded", {})
        protocol = decoded.get("protocol", "unknown")
        node = node_id(decoded)
        gps = record.get("receiver_gps") or {}
        stamp = record["timestamp"]
        self.db.execute(
            "INSERT INTO observations(received_at,profile,protocol,node_id,rssi,snr,latitude,longitude,raw,record_json)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (stamp, record.get("profile", {}).get("id"), protocol, node, record.get("rssi_dbm"),
             record.get("snr_db"), gps.get("latitude"), gps.get("longitude"), raw, text))
        if node:
            previous = self.db.execute("SELECT latest_json FROM devices WHERE protocol=? AND node_id=?",
                                       (protocol, node)).fetchone()
            summary = dict(record)
            if previous:
                prior = json.loads(previous[0])
                summary["decoded"] = dict(prior.get("decoded", {}), **decoded)
            summary_text = json.dumps(summary, ensure_ascii=True, allow_nan=False)
            rssi = record.get("rssi_dbm")
            self.db.execute("""INSERT INTO devices VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(protocol,node_id) DO UPDATE SET
                last_seen=excluded.last_seen, sightings=devices.sightings+1,
                best_rssi=max(coalesce(devices.best_rssi,-999), coalesce(excluded.best_rssi,-999)),
                latest_json=excluded.latest_json""",
                (protocol, node, stamp, stamp, 1, rssi, summary_text))
        self.stream.write(text + "\n")
        self.pcap.append(record)
        self.count += 1

    def flush(self):
        self.db.commit()
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.pcap.flush()

    def close(self):
        failure = None
        try:
            self.flush()
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as exc:  # keep closing the other sinks
            failure = exc
        finally:
            for resource in (self.db, self.stream, self.pcap):
                try:
                    resource.close()
                except Exception as exc:
                    failure = failure or exc
        if failure is not None:
            raise failure
