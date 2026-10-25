"""Durable structured event inbox, independent of conversation and speech."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import sqlite3
from contextlib import closing, contextmanager

MAX_EVENT_BYTES = 65536


class AssistEventInbox:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS assist_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE NOT NULL,
                event_type TEXT NOT NULL,
                data_json TEXT NOT NULL,
                received_at TEXT NOT NULL
            )""")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(assist_events)")}
            if "group_id" not in columns:
                connection.execute("ALTER TABLE assist_events ADD COLUMN group_id TEXT")
            for row in connection.execute("SELECT sequence,event_type,data_json FROM assist_events WHERE group_id IS NULL").fetchall():
                connection.execute("UPDATE assist_events SET group_id=? WHERE sequence=?",
                                   (self.group_id(row[1], row[2]), row[0]))
            connection.execute("CREATE INDEX IF NOT EXISTS assist_events_group ON assist_events(group_id,sequence)")
            connection.execute("CREATE TABLE IF NOT EXISTS assist_event_ack (group_id TEXT PRIMARY KEY, through_sequence INTEGER NOT NULL)")

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
            yield connection

    @staticmethod
    def group_id(event_type, data_json):
        return hashlib.sha256((event_type + "\0" + data_json).encode("utf-8")).hexdigest()

    def receive(self, payload):
        if set(payload) != {"event_id", "event_type", "data"}:
            raise ValueError("event_id, event_type und data erforderlich; keine weiteren Felder")
        for key in ("event_id", "event_type"):
            value = payload[key]
            if not isinstance(value, str) or not value.strip() or len(value) > 128:
                raise ValueError(f"Ungültiges {key}")
        if not isinstance(payload["data"], dict):
            raise ValueError("data muss ein JSON-Objekt sein")
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_EVENT_BYTES:
            raise ValueError("Ereignis überschreitet 64 KiB")
        data_json = json.dumps(payload["data"], ensure_ascii=False, sort_keys=True, allow_nan=False)
        group_id = self.group_id(payload["event_type"], data_json)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute(
                "SELECT event_type, data_json FROM assist_events WHERE event_id=?",
                (payload["event_id"],),
            ).fetchone()
            if old is not None:
                if old != (payload["event_type"], data_json):
                    raise ValueError("event_id wurde bereits mit anderen Daten verwendet")
                return {"accepted": True, "event_id": payload["event_id"], "duplicate": True}
            connection.execute(
                "INSERT INTO assist_events(event_id,event_type,data_json,received_at,group_id) VALUES (?,?,?,?,?)",
                (payload["event_id"], payload["event_type"], data_json,
                 datetime.now(timezone.utc).isoformat(), group_id),
            )
        return {"accepted": True, "event_id": payload["event_id"], "duplicate": False}

    def read(self, after=0, limit=100):
        if after < 0 or not 1 <= limit <= 100:
            raise ValueError("after muss >= 0 und limit zwischen 1 und 100 sein")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT sequence,event_id,event_type,data_json,received_at FROM assist_events "
                "WHERE sequence>? ORDER BY sequence LIMIT ?", (after, limit),
            ).fetchall()
        return {"events": [{"sequence": row[0], "event_id": row[1], "event_type": row[2],
                            "data": json.loads(row[3]), "received_at": row[4]} for row in rows],
                "next_cursor": rows[-1][0] if rows else after}

    def groups(self, offset=0, limit=50):
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("offset muss >= 0 und limit zwischen 1 und 100 sein")
        with self._connect() as connection:
            connection.execute("BEGIN")
            rows = connection.execute(
                "SELECT e.group_id,e.event_type,e.data_json,COUNT(*),MIN(e.received_at),"
                "MAX(e.received_at),MAX(e.sequence) FROM assist_events e "
                "LEFT JOIN assist_event_ack a ON a.group_id=e.group_id "
                "WHERE e.sequence>COALESCE(a.through_sequence,0) GROUP BY e.group_id "
                "ORDER BY MAX(e.sequence) DESC LIMIT ? OFFSET ?", (limit, offset),
            ).fetchall()
            pending = connection.execute(
                "SELECT COUNT(*),COUNT(DISTINCT e.group_id) FROM assist_events e "
                "LEFT JOIN assist_event_ack a ON a.group_id=e.group_id "
                "WHERE e.sequence>COALESCE(a.through_sequence,0)").fetchone()
            total = connection.execute("SELECT COUNT(*) FROM assist_events").fetchone()[0]
        return {"groups": [{"group_id": row[0], "event_type": row[1], "data": json.loads(row[2]),
                            "count": row[3], "first_received_at": row[4], "last_received_at": row[5],
                            "through_sequence": row[6]} for row in rows],
                "pending_count": pending[0], "pending_groups": pending[1], "total_count": total,
                "next_offset": offset + len(rows) if offset + len(rows) < pending[1] else None}

    def acknowledge(self, group_id, through_sequence):
        if not isinstance(group_id, str) or type(through_sequence) is not int or through_sequence < 1:
            raise ValueError("Ungültige Gruppen-ID oder Sequenznummer")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM assist_events WHERE group_id=? AND sequence=?",
                                  (group_id, through_sequence)).fetchone() is None:
                raise ValueError("Gruppe und Sequenznummer wurden nicht gefunden")
            connection.execute("INSERT INTO assist_event_ack(group_id,through_sequence) VALUES (?,?) "
                               "ON CONFLICT(group_id) DO UPDATE SET through_sequence=MAX(through_sequence,excluded.through_sequence)",
                               (group_id, through_sequence))
        return {"acknowledged": True, "group_id": group_id, "through_sequence": through_sequence}

    def minimal_contract(self):
        integer = {"type": "integer", "minimum": 0}
        return {"capability": "assist_events", "description": "Persisted structured external events and exact duplicate counts.",
                "operations": {
                    "list": {"description": "Read unacknowledged groups with event data, counts and receipt timestamps. Does not acknowledge or react.",
                             "effect": "read", "parameters_schema": {"type": "object", "properties": {
                                 "offset": integer, "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False}},
                    "acknowledge": {"description": "Mark a published group as acknowledged through its published sequence. Retains raw events; does not execute a reaction.",
                                    "effect": "write", "parameters_schema": {"type": "object", "properties": {
                                        "group_id": {"type": "string"}, "through_sequence": {"type": "integer", "minimum": 1}},
                                        "required": ["group_id", "through_sequence"], "additionalProperties": False}}}}

    def execute_operation(self, operation, parameters):
        if operation == "list":
            return self.groups(**parameters)
        if operation == "acknowledge":
            return self.acknowledge(**parameters)
        raise ValueError("Unbekannte Ereignisoperation")
