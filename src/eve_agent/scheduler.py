from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .memory import redact_sensitive
from .transport_access import transport_metadata


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


def _local_timezone_name() -> str:
    try:
        resolved = str(Path("/etc/localtime").resolve())
        marker = "/zoneinfo/"
        if marker in resolved:
            return resolved.split(marker, 1)[1]
    except OSError:
        pass
    return "local"


def _timezone(name: str | None):
    selected = str(name or "local").strip() or "local"
    if selected == "local":
        return datetime.now().astimezone().tzinfo
    try:
        return ZoneInfo(selected)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Unbekannte IANA-Zeitzone") from exc


class ScheduledTasks:
    """Persistent scheduler with structured actions and auditable, idempotent runs."""

    def __init__(self, database, home_assistant=None, *, start_monitor: bool = True, title_normalizer=None):
        self.database = database
        self.home_assistant = home_assistant
        self._lock = threading.RLock()
        # Model execution can take minutes. Never hold the data/delivery lock
        # while running an executor, and never queue another scheduler tick.
        self._run_lock = threading.Lock()
        self._executors: dict[str, Callable[[dict], dict]] = {"notify": self._notify}
        self.conversation_id: str | None = None
        self._monitor_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.output_targets_provider = lambda: []
        from .scheduled_execution import restore_scheduled_origins
        restore_scheduled_origins(database)
        with self.database.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS scheduled_deliveries (
                id TEXT PRIMARY KEY, target_json TEXT NOT NULL, payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', error TEXT, updated_at TEXT NOT NULL)""")
            columns = {row['name'] for row in connection.execute('PRAGMA table_info(scheduled_deliveries)')}
            for name, definition in (('claim_token', 'TEXT'), ('claim_until', 'REAL'),
                                     ('retry_at', 'REAL NOT NULL DEFAULT 0')):
                if name not in columns:
                    connection.execute(f'ALTER TABLE scheduled_deliveries ADD COLUMN {name} {definition}')
            # Old sending rows have no dispatch marker. Their outcome cannot be
            # inferred safely, so preserve the output without publishing it again.
            connection.execute("""UPDATE scheduled_deliveries SET status='uncertain',
                error='Send interrupted; delivery outcome unknown',updated_at=?
                WHERE status='sending'""", (_utc_iso(datetime.now(timezone.utc)),))
            connection.execute("""UPDATE scheduled_deliveries SET status='pending',
                claim_token=NULL,claim_until=NULL WHERE status='claimed'""")
            for row in connection.execute('SELECT id,status FROM scheduled_deliveries').fetchall():
                self._delivery_result(connection, row['id'], row['status'])
        if start_monitor:
            self.start()

    def start(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._stop.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor, name="eve-scheduler", daemon=True,
        )
        self._monitor_thread.start()

    def stop(self) -> None:
        self._stop.set()

    @staticmethod
    def self_descriptions():
        from .runtime_self_knowledge import RuntimeSelfDescription
        return [RuntimeSelfDescription(
            "scheduled_tasks.manage", "scheduled_tasks.manage",
            "Ich kann Erinnerungen und geplante Aufgaben erstellen, anzeigen und verwalten.",
            "ScheduledTasks", "handle,list_tasks,get_task,update_task,delete_task",
        )]

    def set_conversation(self, conversation_id: str | None) -> None:
        self.conversation_id = conversation_id

    def minimal_contract(self) -> dict:
        schedule_schema = {
            "type": "object", "additionalProperties": False,
            "properties": {
                "at": {"type": "string", "format": "date-time"},
                "seconds": {"type": "integer", "minimum": 1},
                "first_at": {"type": "string", "format": "date-time"},
                "hour": {"type": "integer", "minimum": 0, "maximum": 23},
                "minute": {"type": "integer", "minimum": 0, "maximum": 59},
                "weekdays": {"type": "array", "minItems": 1, "items": {
                    "type": "integer", "minimum": 0, "maximum": 6,
                }},
                "ends_at": {"type": ["string", "null"], "format": "date-time",
                            "description": "Optional inclusive end instant. No execution after this time; omit/null for no end."},
            },
        }
        # Inventories belong in tool results, not repeated in every function
        # schema: hundreds of conversation IDs can exceed the model context.
        # resolve_output_target/get_task still validate IDs and access at use.
        target_schema = {"type": "string", "minLength": 1,
                         "description": (
                             "Omit or use current for this conversation. For another destination, "
                             "use an ID returned by list_output_targets. For a Chatto reminder to be delivered "
                             "by DM, select chatto:dm:self from that list, even when requested in a channel."
                         )}
        task_id_schema = {"type": "string", "minLength": 1,
                          "description": "Task ID returned by create or list."}
        return {
            "description": "Future and recurring EVE turns: create, inspect, pause, change or delete schedules.",
            "operations": {
                "list_output_targets": {"effect": "read", "parameters_schema": {
                    "type": "object", "additionalProperties": False, "properties": {}}},
                "create": {"effect": "write", "description": (
                    "Store a self-contained instruction EVE shall execute when due, not a confirmation or editing instruction. "
                    "For reminders, instruct EVE to address the recipient now. Use schedule.ends_at when recurrence must stop. "
                    "delay is one-shot; interval repeats. "
                    "once uses schedule.at; delay uses seconds; interval uses seconds and optional first_at; "
                    "daily uses hour/minute; weekly additionally uses weekdays where Monday=0."
                ), "parameters_schema": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "output_target_id": target_schema,
                        "request": {"type": "string", "minLength": 1},
                        "name": {"type": "string", "minLength": 1},
                        "schedule_type": {"enum": ["once", "delay", "interval", "daily", "weekly"]},
                        "schedule": schedule_schema,
                        "timezone": {"type": "string", "minLength": 1},
                    },
                    "required": ["request", "schedule_type", "schedule"],
                }},
                "list": {"effect": "read", "parameters_schema": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"include_finished": {"type": "boolean"}},
                }},
                "get": {"effect": "read", "parameters_schema": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"task_id": task_id_schema}, "required": ["task_id"],
                }},
                "list_deliveries": {"effect": "read", "parameters_schema": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"task_id": task_id_schema}, "required": ["task_id"]}},
                "retry_delivery": {"effect": "write", "description": "Retry a blocked delivery without executing the task again. Uncertain sends cannot be retried automatically.",
                    "parameters_schema": {"type": "object", "additionalProperties": False,
                    "properties": {"task_id": task_id_schema, "delivery_id": {"type": "string"}},
                    "required": ["task_id", "delivery_id"]}},
                "list_runs": {"effect": "read", "parameters_schema": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"task_id": task_id_schema, "limit": {"type": "integer", "minimum": 1}},
                    "required": ["task_id"],
                }},
                "update": {"effect": "write", "parameters_schema": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
                        "task_id": task_id_schema,
                        "changes": {"type": "object", "additionalProperties": False, "properties": {
                            "name": {"type": "string", "minLength": 1},
                            "output_target_id": target_schema,
                            "request": {"type": "string", "minLength": 1},
                            "status": {"enum": ["active", "paused"]},
                            "schedule_type": {"enum": ["once", "delay", "interval", "daily", "weekly"]},
                            "schedule": schedule_schema,
                            "next_run_at": {"type": "string", "format": "date-time"},
                            "timezone": {"type": "string", "minLength": 1},
                        }},
                    }, "required": ["task_id", "changes"],
                }},
                "delete": {"effect": "write", "parameters_schema": {
                    "type": "object", "additionalProperties": False,
                    "properties": {"task_id": task_id_schema}, "required": ["task_id"],
                }},
            },
            "current_time": datetime.now().astimezone().isoformat(),
            "local_timezone": _local_timezone_name(),
            "tasks": [{"id": item["id"], "name": item["name"], "status": item["status"],
                       "next_run_at": item["next_run_at"], "output_target": item["action"].get("output_target"), "request": item["action"].get("request") or item["action"].get("message")}
                      for item in self.list_tasks(include_finished=False)],
        }

    def execute_operation(self, operation: str, arguments: dict, *, conversation_id: str | None = None) -> dict:
        if not isinstance(arguments, dict):
            raise ValueError("Scheduler-Argumente müssen ein Objekt sein")
        if operation == "list_output_targets":
            return {"status": "completed", "result": [{"id": "current", "name": "Current conversation"}] + self.output_targets_provider()}
        published = {item["id"] for item in self.list_tasks(include_finished=False)}
        if operation == "list":
            tasks = self.list_tasks(include_finished=bool(arguments.get("include_finished", False)))
            return {"status": "completed", "result": tasks}
        if operation == "create":
            request = redact_sensitive(str(arguments.get("request") or arguments.get("message") or "").strip())
            name = redact_sensitive(str(arguments.get("name") or request).strip())
            schedule_type = str(arguments.get("schedule_type", "")).casefold()
            timezone_name = str(arguments.get("timezone") or _local_timezone_name())
            if not request or not name or len(name) > 120:
                raise ValueError("Ungültiger geplanter Auftrag")
            schedule = self._validate_schedule(schedule_type, arguments.get("schedule"), timezone_name)
            next_run = self._next_for_update(schedule_type, schedule, timezone_name)
            self._validate_first_run(next_run, schedule)
            task_id = str(uuid.uuid4())
            now = _utc_iso(datetime.now(timezone.utc))
            action = {
                "tool": "eve_turn", "request": request, "conversation_id": conversation_id or self.conversation_id,
                "task_id": task_id, "name": name,
                "execution_context": transport_metadata(),
                "output_target": self.resolve_output_target(arguments.get("output_target_id", "current"), conversation_id or self.conversation_id),
            }
            metadata = {"origin": "eve_native_schedule"}
            with self.database.connect() as connection:
                connection.execute(
                    """INSERT INTO scheduled_tasks
                       (id, conversation_id, name, status, schedule_type, schedule_json,
                        action_json, next_run_at, timezone, risk_level, created_at, updated_at, metadata_json)
                       VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, 'low', ?, ?, ?)""",
                    (task_id, conversation_id or self.conversation_id, name, schedule_type,
                     json.dumps(schedule, ensure_ascii=False), json.dumps(action, ensure_ascii=False),
                     _utc_iso(next_run), timezone_name, now, now, json.dumps(metadata, ensure_ascii=False)),
                )
                self._audit(connection, task_id, conversation_id or self.conversation_id,
                            "task.created", "eve", f"Aufgabe erstellt: {name}")
            task = self.get_task(task_id)
            return {"status": "created", "result": task}
        if operation == "get":
            return {"status": "completed", "result": self.get_task(arguments.get("task_id"))}
        if operation in {"list_deliveries", "retry_delivery"}:
            self.get_task(arguments.get("task_id"))
            with self.database.connect() as connection:
                rows = connection.execute("SELECT id,status,error,updated_at FROM scheduled_deliveries WHERE json_extract(payload_json, '$.notification.task_id')=?",
                                          (arguments["task_id"],)).fetchall()
                if operation == "list_deliveries":
                    return {"status": "completed", "result": [dict(row) for row in rows]}
                if not any(row["id"] == arguments["delivery_id"] and row["status"] == "blocked" for row in rows):
                    raise ValueError("Nur blockierte Zustellungen können erneut versucht werden")
                connection.execute("""UPDATE scheduled_deliveries SET status='pending',error=NULL,
                    claim_token=NULL,claim_until=NULL,retry_at=0,updated_at=? WHERE id=? AND status='blocked'""",
                    (_utc_iso(datetime.now(timezone.utc)), arguments["delivery_id"]))
                self._delivery_result(connection, arguments['delivery_id'], 'pending')
            return {"status": "updated", "result": {"delivery_id": arguments["delivery_id"], "status": "pending"}}
        if operation == "list_runs":
            return {"status": "completed", "result": self.list_runs(
                arguments.get("task_id"), limit=arguments.get("limit", 20),
            )}
        task_id = str(arguments.get("task_id", ""))
        if task_id not in published:
            raise ValueError("Die geplante Aufgabe wurde nicht veröffentlicht")
        if operation == "update":
            task = self.update_task(task_id, arguments.get("changes"))
            return {"status": "updated", "result": task}
        if operation == "delete":
            task = self.get_task(task_id)
            self.delete_task(task_id)
            return {"status": "deleted", "result": task}
        raise ValueError("Nicht veröffentlichte Scheduler-Operation")

    def resolve_output_target(self, identifier, conversation_id):
        if identifier == "current":
            context = transport_metadata()
            return ({"transport": "chatto", **context} if context else
                    {"transport": "eve", "conversation_id": conversation_id})
        for target in self.output_targets_provider():
            if target["id"] == identifier:
                return dict(target)
        raise ValueError("Unbekanntes oder nicht erlaubtes Ausgabeziel")

    def claim_deliveries(self):
        """Lease one output; only claims that never started dispatch may replay."""
        now = time.time()
        token = uuid.uuid4().hex
        with self._lock, self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            self._expire_deliveries(connection)
            rows = connection.execute("""UPDATE scheduled_deliveries SET status='claimed',
                claim_token=?,claim_until=?,updated_at=? WHERE id=(SELECT id FROM scheduled_deliveries
                WHERE status='pending' AND retry_at<=? ORDER BY updated_at,id LIMIT 1) RETURNING *""",
                (token, now + 300, _utc_iso(datetime.now(timezone.utc)), now)).fetchall()
            for row in rows:
                self._delivery_result(connection, row['id'], 'claimed')
        return [{"id": row["id"], "target": json.loads(row["target_json"]),
                 "payload": json.loads(row["payload_json"]), 'claim_token': token} for row in rows]

    def _expire_deliveries(self, connection):
        # Also called by the scheduler monitor: a disconnected bot must not
        # leave a started send stuck forever awaiting another delivery poll.
        expired = connection.execute("""UPDATE scheduled_deliveries SET
            status=CASE WHEN status='claimed' THEN 'pending' ELSE 'uncertain' END,
            error=CASE WHEN status='sending' THEN 'Send timed out; delivery outcome unknown' ELSE error END,
            updated_at=? WHERE status IN ('claimed','sending') AND claim_until<=? RETURNING id,status""",
            (_utc_iso(datetime.now(timezone.utc)), time.time())).fetchall()
        for row in expired:
            self._delivery_result(connection, row['id'], row['status'])

    def begin_delivery(self, identifier, token):
        """Persist the irreversible boundary immediately before visible output."""
        with self.database.connect() as connection:
            changed = connection.execute("""UPDATE scheduled_deliveries SET status='sending',
                claim_until=?,updated_at=? WHERE id=? AND claim_token=?
                AND status='claimed' AND claim_until>?""",
                (time.time() + 300, _utc_iso(datetime.now(timezone.utc)), identifier, token, time.time())).rowcount
            if not changed:
                raise ValueError('Scheduled delivery claim is no longer valid')
            self._delivery_result(connection, identifier, 'sending')

    def acknowledge_delivery(self, identifier, status, error=None, *, claim_token=None):
        """Accept idempotent ACKs for the current claim, including late success."""
        if status not in {"delivered", "blocked", "uncertain", "retry"}:
            raise ValueError("Invalid delivery status")
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT status,claim_token FROM scheduled_deliveries WHERE id=?', (identifier,)).fetchone()
            if row is None or not claim_token or row['claim_token'] != claim_token:
                raise ValueError('Scheduled delivery claim is no longer valid')
            stored = 'pending' if status == 'retry' else status
            if row['status'] == stored:
                return
            allowed = {'claimed'} if status in {'retry', 'blocked'} else {'sending'}
            if status == 'delivered':
                allowed.add('uncertain')
            if row['status'] not in allowed:
                raise ValueError('Invalid scheduled delivery transition')
            connection.execute("""UPDATE scheduled_deliveries SET status=?,error=?,retry_at=?,updated_at=?
                WHERE id=?""", (stored, redact_sensitive(str(error or ''))[:500],
                    time.time() + 15 if status == 'retry' else 0, _utc_iso(datetime.now(timezone.utc)), identifier))
            self._delivery_result(connection, identifier, stored)

    @staticmethod
    def _delivery_result(connection, identifier, status):
        # Execution success and confirmed transport delivery are independent.
        for table, column in (('task_runs', 'result_json'), ('scheduled_deliveries', 'payload_json')):
            connection.execute(f"""UPDATE {table} SET {column}=json_set({column},
                '$.notification.delivered',json(?),'$.notification.delivery_status',?)
                WHERE id=?""", ('true' if status == 'delivered' else 'false', status, identifier))

    def register_executor(self, tool: str, executor: Callable[[dict], dict]) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", tool):
            raise ValueError("Ungültiger Werkzeugname")
        self._executors[tool] = executor

    def list_tasks(self, *, include_finished: bool = False, limit: int | None = None) -> list[dict]:
        where = "status != 'deleted'" if include_finished else "status IN ('active', 'paused')"
        sql = (
            f"SELECT * FROM scheduled_tasks WHERE {where} ORDER BY "
            "CASE WHEN next_run_at IS NULL THEN 1 ELSE 0 END, next_run_at, created_at DESC"
        )
        parameters = ()
        if limit is not None:
            sql += " LIMIT ?"
            parameters = (max(int(limit), 1),)
        with self.database.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [self._task_dict(row) for row in rows if self._task_accessible(self._task_dict(row))]

    @staticmethod
    def _task_accessible(task):
        context = transport_metadata()
        if not context or context.get("access_profile") == "owner_dm":
            return True
        origin = task["action"].get("execution_context") or {}
        target = task["action"].get("output_target") or {}
        if target.get("recipient_user_id") and target["recipient_user_id"] != context.get("sender_id"):
            return False
        keys = ["server_url", "bot_id", "room_id", "thread_root_id", "access_profile"]
        if context.get("access_profile") == "member_dm":
            keys.append("sender_id")
        return all(origin.get(key) == context.get(key) for key in keys)

    def get_task(self, task_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_tasks WHERE id=? AND status!='deleted'", (str(task_id),)
            ).fetchone()
        if row is None:
            raise KeyError("Geplante Aufgabe wurde nicht gefunden")
        task = self._task_dict(row)
        if not self._task_accessible(task):
            raise PermissionError("Aufgabe gehört zu einem anderen Gespräch")
        return task

    def list_runs(self, task_id: str, *, limit: int = 20) -> list[dict]:
        self.get_task(task_id)
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT id,status,scheduled_for,started_at,finished_at,attempt,
                          result_json,error_text,created_at
                   FROM task_runs WHERE task_id=? ORDER BY created_at DESC LIMIT ?""",
                (str(task_id), max(1, int(limit))),
            ).fetchall()
        return [{
            "id": row["id"], "status": row["status"], "scheduled_for": row["scheduled_for"],
            "started_at": row["started_at"], "finished_at": row["finished_at"],
            "attempt": row["attempt"], "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error_text"], "created_at": row["created_at"],
        } for row in rows]

    def update_task(self, task_id: str, changes: dict) -> dict:
        self.get_task(task_id)
        if not isinstance(changes, dict):
            raise ValueError("Änderungen müssen ein Objekt sein")
        allowed = {"name", "message", "request", "status", "next_run_at", "schedule_type", "schedule", "timezone", "output_target_id"}
        if set(changes) - allowed:
            raise ValueError("Unbekanntes Aufgabenfeld")
        with self._lock, self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_tasks WHERE id=? AND status!='deleted'", (str(task_id),)
            ).fetchone()
            if row is None:
                raise KeyError("Geplante Aufgabe wurde nicht gefunden")
            name = str(changes.get("name", row["name"])).strip()
            if not name or len(name) > 120:
                raise ValueError("Der Aufgabenname muss zwischen 1 und 120 Zeichen lang sein")
            action = json.loads(row["action_json"])
            metadata = json.loads(row["metadata_json"])
            if "output_target_id" in changes:
                action["output_target"] = self.resolve_output_target(changes["output_target_id"], row["conversation_id"])
            request_change = changes.get("request", changes.get("message"))
            if request_change is not None:
                request = redact_sensitive(str(request_change).strip())
                if not request:
                    raise ValueError("Der geplante Auftrag darf nicht leer sein")
                if action.get("tool") == "notify":
                    action["message"] = request
                    action["raw_message"] = request
                else:
                    action["request"] = request
                if "name" not in changes:
                    name = request[:120]
            status = str(changes.get("status", row["status"])).casefold()
            if status not in {"active", "paused"}:
                raise ValueError("Eine Aufgabe kann nur aktiv oder pausiert sein")
            next_run = row["next_run_at"]
            schedule_type = str(changes.get("schedule_type", row["schedule_type"])).casefold()
            schedule = json.loads(row["schedule_json"])
            timezone_name = str(changes.get("timezone", row["timezone"] or _local_timezone_name()))
            _timezone(timezone_name)
            if "schedule_type" in changes or "schedule" in changes:
                if "schedule_type" not in changes or "schedule" not in changes:
                    raise ValueError("Zeitplantyp und Zeitplandaten müssen gemeinsam geändert werden")
                schedule = self._validate_schedule(schedule_type, changes["schedule"], timezone_name)
                candidate = self._next_for_update(schedule_type, schedule, timezone_name)
                self._validate_first_run(candidate, schedule)
                next_run = _utc_iso(candidate)
            elif "next_run_at" in changes:
                value = str(changes["next_run_at"]).strip()
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise ValueError("Ungültiger Ausführungszeitpunkt") from exc
                if parsed.tzinfo is None:
                    parsed = parsed.astimezone()
                if parsed <= datetime.now(timezone.utc):
                    raise ValueError("Der Ausführungszeitpunkt muss in der Zukunft liegen")
                next_run = _utc_iso(parsed)
                self._validate_first_run(parsed, schedule)
            if status == "active" and not next_run:
                candidate = self._next_for_update(schedule_type, schedule, timezone_name)
                self._validate_first_run(candidate, schedule)
                if candidate <= datetime.now(timezone.utc):
                    raise ValueError("Für die Fortsetzung muss ein zukünftiger Termin gesetzt werden")
                next_run = _utc_iso(candidate)
            if schedule.get("ends_at") and _from_iso(schedule["ends_at"]) < datetime.now(timezone.utc):
                status, next_run = "completed", None
            now = _utc_iso(datetime.now(timezone.utc))
            connection.execute(
                "UPDATE scheduled_tasks SET name=?, action_json=?, status=?, schedule_type=?, schedule_json=?, next_run_at=?, timezone=?, metadata_json=?, updated_at=? WHERE id=?",
                (name, json.dumps(action, ensure_ascii=False), status, schedule_type,
                 json.dumps(schedule, ensure_ascii=False), next_run, timezone_name,
                 json.dumps(metadata, ensure_ascii=False), now, row["id"]),
            )
            self._audit(connection, row["id"], row["conversation_id"], "task.updated", "user", "Aufgabe geändert")
        return self.get_task(task_id)

    @classmethod
    def _validate_schedule(cls, schedule_type: str, raw: object, timezone_name: str = "local") -> dict:
        result = cls._validate_timing(schedule_type, raw, timezone_name)
        if raw.get("ends_at") is not None:
            try:
                end = datetime.fromisoformat(raw["ends_at"].replace("Z", "+00:00"))
                if end.tzinfo is None:
                    end = end.replace(tzinfo=_timezone(timezone_name))
                result["ends_at"] = _utc_iso(end)
            except (AttributeError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError("Ungültiges Enddatum") from exc
        return result

    @staticmethod
    def _validate_first_run(candidate, schedule):
        end = _from_iso(schedule.get("ends_at"))
        if end is not None and candidate > end:
            raise ValueError("Das Enddatum liegt vor dem nächsten Ausführungstermin")

    @classmethod
    def _validate_timing(cls, schedule_type: str, raw: object, timezone_name: str = "local") -> dict:
        if schedule_type not in {"once", "delay", "daily", "weekly", "interval"} or not isinstance(raw, dict):
            raise ValueError("Ungültiger Zeitplan")
        _timezone(timezone_name)
        try:
            if schedule_type == "once":
                value = str(raw["at"])
                due = _from_iso(value)
                if due.tzinfo is None: due = due.astimezone()
                if due <= datetime.now(timezone.utc): raise ValueError
                return {"at": _utc_iso(due)}
            if schedule_type in {"delay", "interval"}:
                seconds = int(raw["seconds"])
                if seconds < 1: raise ValueError
                result = {"seconds": seconds}
                if schedule_type == "interval" and raw.get("first_at"):
                    first = _from_iso(str(raw["first_at"]))
                    if first <= datetime.now(timezone.utc): raise ValueError
                    result["first_at"] = _utc_iso(first)
                return result
            hour, minute = int(raw["hour"]), int(raw["minute"])
            if not 0 <= hour <= 23 or not 0 <= minute <= 59: raise ValueError
            if schedule_type == "daily": return {"hour": hour, "minute": minute}
            weekdays = sorted({int(day) for day in raw["weekdays"]})
            if not weekdays or any(day < 0 or day > 6 for day in weekdays): raise ValueError
            return {"weekdays": weekdays, "hour": hour, "minute": minute}
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Ungültige Zeitplandaten") from exc

    @classmethod
    def _next_for_update(cls, schedule_type: str, schedule: dict, timezone_name: str = "local") -> datetime:
        now = datetime.now(_timezone(timezone_name))
        if schedule_type == "once": return _from_iso(schedule["at"])
        if schedule_type == "delay": return now + timedelta(seconds=schedule["seconds"])
        if schedule_type == "interval" and schedule.get("first_at"):
            return _from_iso(schedule["first_at"])
        if schedule_type == "interval": return now + timedelta(seconds=schedule["seconds"])
        if schedule_type == "daily":
            due = now.replace(hour=schedule["hour"], minute=schedule["minute"], second=0, microsecond=0)
            return due + timedelta(days=1) if due <= now else due
        return cls._next_weekly(schedule, now)

    def delete_task(self, task_id: str) -> None:
        self.get_task(task_id)
        with self._lock, self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, conversation_id FROM scheduled_tasks WHERE id=? AND status!='deleted'", (str(task_id),)
            ).fetchone()
            if row is None:
                raise KeyError("Geplante Aufgabe wurde nicht gefunden")
            connection.execute(
                "UPDATE scheduled_tasks SET status='deleted', updated_at=? WHERE id=?",
                (_utc_iso(datetime.now(timezone.utc)), row["id"]),
            )
            self._audit(connection, row["id"], row["conversation_id"], "task.deleted", "user", "Aufgabe gelöscht")

    @staticmethod
    def _task_dict(row) -> dict:
        schedule = json.loads(row["schedule_json"])
        action = json.loads(row["action_json"])
        metadata = json.loads(row["metadata_json"])
        return {
            "id": row["id"], "conversation_id": row["conversation_id"], "name": row["name"],
            "status": row["status"], "schedule_type": row["schedule_type"], "schedule": schedule,
            "action": action, "next_run_at": row["next_run_at"], "timezone": row["timezone"],
            "risk_level": row["risk_level"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "metadata": metadata,
        }

    def pop_due(self, limit: int | None = None) -> list[dict]:
        if limit is not None and int(limit) <= 0:
            return []
        requested = None if limit is None else int(limit)
        # In service mode only the background monitor executes tasks. HTTP
        # notification polling must only read already completed outputs.
        if not self._monitor_thread or not self._monitor_thread.is_alive():
            self._run_due(requested)
        with self._lock:
            with self.database.connect() as connection:
                connection.execute('BEGIN IMMEDIATE')
                suffix = "" if requested is None else " LIMIT ?"
                parameters = () if requested is None else (requested,)
                rows = connection.execute(
                    """SELECT id, result_json FROM task_runs
                       WHERE status='succeeded' AND json_extract(result_json, '$.notification.message') IS NOT NULL
                         AND COALESCE(json_extract(result_json, '$.notification.delivered'), 0) = 0
                         AND NOT EXISTS (SELECT 1 FROM scheduled_deliveries WHERE id=task_runs.id)
                       ORDER BY created_at, id""" + suffix, parameters,
                ).fetchall()
                result = []
                for row in rows:
                    payload = json.loads(row["result_json"])
                    notification = dict(payload["notification"])
                    notification.pop("delivered", None)
                    result.append(notification)
                    payload["notification"]["delivered"] = True
                    connection.execute("UPDATE task_runs SET result_json=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), row["id"]))
                return result

    def _monitor(self) -> None:
        while not self._stop.is_set():
            try:
                self._run_due(20)
            except (OSError, sqlite3.Error, ValueError, RuntimeError):
                # A transient backend or database failure is recorded on an
                # individual run where possible. The daemon must stay alive.
                pass
            self._stop.wait(1)

    def _run_due(self, limit: int | None) -> None:
        if not self._run_lock.acquire(blocking=False):
            return
        try:
            self._run_due_unlocked(limit)
        finally:
            self._run_lock.release()

    def _run_due_unlocked(self, limit: int | None) -> None:
        now = datetime.now(timezone.utc)
        # Expire before claiming work, including overdue tasks after downtime.
        # Paused tasks also finish when their deadline passes.
        with self.database.connect() as connection:
            self._expire_deliveries(connection)
            for task in connection.execute("SELECT * FROM scheduled_tasks WHERE status IN ('active','paused') AND json_extract(schedule_json,'$.ends_at') IS NOT NULL").fetchall():
                end = _from_iso(json.loads(task["schedule_json"]).get("ends_at"))
                if end is not None and now > end:
                    connection.execute("UPDATE scheduled_tasks SET status='completed',next_run_at=NULL,updated_at=? WHERE id=?",
                                       (_utc_iso(now), task["id"]))
                    self._audit(connection, task["id"], task["conversation_id"], "task.expired", "scheduler", "Enddatum erreicht")
        suffix = "" if limit is None else " LIMIT ?"
        parameters: tuple[object, ...] = (_utc_iso(now),)
        if limit is not None:
            parameters += (max(0, int(limit)),)
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM scheduled_tasks WHERE status='active' AND next_run_at IS NOT NULL
                   AND next_run_at <= ? ORDER BY next_run_at, id""" + suffix,
                parameters,
            ).fetchall()
        for row in rows:
            scheduled_for = row["next_run_at"]
            idempotency_key = f"{row['id']}:{scheduled_for}"
            run_id = str(uuid.uuid4())
            started = _utc_iso(datetime.now(timezone.utc))
            try:
                with self._lock, self.database.connect() as connection:
                    connection.execute('BEGIN IMMEDIATE')
                    # A task may have been paused, deleted or rescheduled since
                    # the due list was read. Claim only its current occurrence.
                    current = connection.execute(
                        "SELECT * FROM scheduled_tasks WHERE id=? AND status='active' AND next_run_at=?",
                        (row['id'], scheduled_for),
                    ).fetchone()
                    if current is None:
                        continue
                    row = current
                    connection.execute(
                        """INSERT INTO task_runs(id, task_id, status, scheduled_for, started_at,
                           attempt, idempotency_key, created_at) VALUES (?, ?, 'running', ?, ?, 1, ?, ?)""",
                        (run_id, row["id"], scheduled_for, started, idempotency_key, started),
                    )
                action = json.loads(row["action_json"])
                action.setdefault("task_id", row["id"])
                action.setdefault("conversation_id", row["conversation_id"])
                action["scheduled_for"] = scheduled_for
                action["run_id"] = run_id
                action["ends_at"] = json.loads(row["schedule_json"]).get("ends_at")
                tool = str(action.get("tool", ""))
                if tool not in self._executors:
                    raise RuntimeError(f"Kein Executor für {tool}")
                result = self._executors[tool](action)
                target = action.get("output_target")
                if target and target.get("transport") == "chatto" and result.get("notification"):
                    result["notification"]["delivered"] = False
                    result["notification"]["delivery_status"] = 'pending'
                    with self.database.connect() as connection:
                        connection.execute("""INSERT INTO scheduled_deliveries
                            (id,target_json,payload_json,status,error,updated_at) VALUES (?, ?, ?, 'pending', NULL, ?)""",
                            (run_id, json.dumps(target), json.dumps(result, ensure_ascii=False), _utc_iso(datetime.now(timezone.utc))))
                        self._finish(row, run_id, result=result, connection=connection)
                else:
                    self._finish(row, run_id, result=result)
            except sqlite3.IntegrityError:
                # The unique idempotency key means another scheduler tick has
                # already claimed this exact occurrence.
                continue
            except Exception as exc:
                self._finish(row, run_id, error=str(exc))

    def _finish(self, task, run_id: str, *, result: dict | None = None, error: str | None = None,
                connection=None) -> None:
        finished = datetime.now(timezone.utc)
        run_status = "failed" if error else "succeeded"
        with self.database.connect() if connection is None else nullcontext(connection) as connection:
            # Respect end dates, pauses and deletions edited during a model turn.
            current = connection.execute("SELECT * FROM scheduled_tasks WHERE id=?", (task["id"],)).fetchone()
            schedule = json.loads(current["schedule_json"])
            next_run = self._next_after(current["schedule_type"], schedule, _from_iso(task["next_run_at"]),
                                        finished, current["timezone"] or "local")
            if any(current[key] != task[key] for key in ("schedule_type", "schedule_json", "next_run_at", "timezone")):
                next_run = _from_iso(current["next_run_at"])
                end = _from_iso(schedule.get("ends_at"))
                if end is not None and (finished > end or next_run is not None and next_run > end):
                    next_run = None
            task_status = "active" if next_run else ("failed" if error else "completed")
            if schedule.get("ends_at") and finished > _from_iso(schedule["ends_at"]):
                task_status = "completed"
            if current["status"] in {"paused", "deleted", "completed"}:
                task_status = current["status"]
            connection.execute(
                "UPDATE task_runs SET status=?, finished_at=?, result_json=?, error_text=? WHERE id=?",
                (run_status, _utc_iso(finished), json.dumps(result, ensure_ascii=False) if result else None,
                 redact_sensitive(error)[:500] if error else None, run_id),
            )
            connection.execute(
                "UPDATE scheduled_tasks SET status=?, next_run_at=?, updated_at=? WHERE id=?",
                (task_status, _utc_iso(next_run) if next_run else None, _utc_iso(finished), task["id"]),
            )
            self._audit(connection, task["id"], task["conversation_id"], f"task.run.{run_status}", "scheduler", error or "Aufgabe ausgeführt")

    @staticmethod
    def _notify(action: dict) -> dict:
        message = str(action.get("message", "")).strip()
        if not message:
            raise ValueError("Leere Benachrichtigung")
        return {"notification": {
            "message": message, "kind": "reminder", "delivered": False,
            "conversation_id": action.get("conversation_id"), "task_id": action.get("task_id"),
        }}

    @classmethod
    def _next_after(cls, schedule_type: str, schedule: dict, scheduled_for: datetime,
                    finished: datetime, timezone_name: str = "local") -> datetime | None:
        candidate = cls._next_after_unbounded(schedule_type, schedule, scheduled_for, finished, timezone_name)
        end = _from_iso(schedule.get("ends_at"))
        return None if end is not None and (finished > end or candidate is not None and candidate > end) else candidate

    @classmethod
    def _next_after_unbounded(cls, schedule_type: str, schedule: dict, scheduled_for: datetime,
                              finished: datetime, timezone_name: str = "local") -> datetime | None:
        if schedule_type in {"once", "delay", "event"}: return None
        if schedule_type == "interval":
            step = timedelta(seconds=max(1, int(schedule["seconds"])))
            candidate = scheduled_for + step
            if candidate <= finished:
                missed = int((finished - candidate).total_seconds() // step.total_seconds()) + 1
                candidate += step * missed
            return candidate
        local = finished.astimezone(_timezone(timezone_name))
        if schedule_type == "daily":
            due = local.replace(hour=int(schedule["hour"]), minute=int(schedule["minute"]), second=0, microsecond=0)
            return due + timedelta(days=1) if due <= local else due
        if schedule_type == "weekly": return cls._next_weekly(schedule, local)
        raise ValueError("Unbekannter Zeitplantyp")

    @staticmethod
    def _next_weekly(schedule: dict, now: datetime) -> datetime:
        for offset in range(8):
            candidate = (now + timedelta(days=offset)).replace(hour=int(schedule["hour"]), minute=int(schedule["minute"]), second=0, microsecond=0)
            if candidate.weekday() in schedule["weekdays"] and candidate > now:
                return candidate
        raise ValueError("Kein nächster Wochentermin")

    @staticmethod
    def _audit(connection, task_id: str, conversation_id: str | None, event_type: str, actor: str, summary: str) -> None:
        connection.execute(
            "INSERT INTO audit_events(conversation_id, task_id, event_type, actor, summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (conversation_id, task_id, event_type, actor, redact_sensitive(summary)[:500], _utc_iso(datetime.now(timezone.utc))),
        )
