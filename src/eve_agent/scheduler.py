from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .memory import redact_sensitive


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
        self._executors: dict[str, Callable[[dict], dict]] = {"notify": self._notify}
        self.conversation_id: str | None = None
        self._monitor_thread: threading.Thread | None = None
        self._stop = threading.Event()
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
            },
        }
        task_ids = [item["id"] for item in self.list_tasks(include_finished=True)]
        task_id_schema = {"type": "string"}
        if task_ids:
            task_id_schema["enum"] = task_ids
        return {
            "description": "Future and recurring EVE turns: create, inspect, pause, change or delete schedules.",
            "operations": {
                "create": {"effect": "write", "description": (
                    "Store the instruction EVE shall execute later. delay is one-shot; interval repeats. "
                    "once uses schedule.at; delay uses seconds; interval uses seconds and optional first_at; "
                    "daily uses hour/minute; weekly additionally uses weekdays where Monday=0."
                ), "parameters_schema": {
                    "type": "object", "additionalProperties": False,
                    "properties": {
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
                       "next_run_at": item["next_run_at"], "request": item["action"].get("request") or item["action"].get("message")}
                      for item in self.list_tasks(include_finished=False)],
        }

    def execute_operation(self, operation: str, arguments: dict, *, conversation_id: str | None = None) -> dict:
        if not isinstance(arguments, dict):
            raise ValueError("Scheduler-Argumente müssen ein Objekt sein")
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
            task_id = str(uuid.uuid4())
            now = _utc_iso(datetime.now(timezone.utc))
            action = {
                "tool": "eve_turn", "request": request, "conversation_id": conversation_id or self.conversation_id,
                "task_id": task_id, "name": name,
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
        return [self._task_dict(row) for row in rows]

    def get_task(self, task_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_tasks WHERE id=? AND status!='deleted'", (str(task_id),)
            ).fetchone()
        if row is None:
            raise KeyError("Geplante Aufgabe wurde nicht gefunden")
        return self._task_dict(row)

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
        if not isinstance(changes, dict):
            raise ValueError("Änderungen müssen ein Objekt sein")
        allowed = {"name", "message", "request", "status", "next_run_at", "schedule_type", "schedule", "timezone"}
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
                next_run = _utc_iso(self._next_for_update(schedule_type, schedule, timezone_name))
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
        with self._lock:
            self._run_due(requested)
            with self.database.connect() as connection:
                suffix = "" if requested is None else " LIMIT ?"
                parameters = () if requested is None else (requested,)
                rows = connection.execute(
                    """SELECT id, result_json FROM task_runs
                       WHERE status='succeeded' AND json_extract(result_json, '$.notification.message') IS NOT NULL
                         AND COALESCE(json_extract(result_json, '$.notification.delivered'), 0) = 0
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
                with self._lock:
                    self._run_due(20)
            except (OSError, sqlite3.Error, ValueError, RuntimeError):
                # A transient backend or database failure is recorded on an
                # individual run where possible. The daemon must stay alive.
                pass
            self._stop.wait(1)

    def _run_due(self, limit: int | None) -> None:
        now = datetime.now(timezone.utc)
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
                with self.database.connect() as connection:
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
                tool = str(action.get("tool", ""))
                if tool not in self._executors:
                    raise RuntimeError(f"Kein Executor für {tool}")
                result = self._executors[tool](action)
                self._finish(row, run_id, result=result)
            except sqlite3.IntegrityError:
                # The unique idempotency key means another scheduler tick has
                # already claimed this exact occurrence.
                continue
            except Exception as exc:
                self._finish(row, run_id, error=str(exc))

    def _finish(self, task, run_id: str, *, result: dict | None = None, error: str | None = None) -> None:
        finished = datetime.now(timezone.utc)
        schedule = json.loads(task["schedule_json"])
        scheduled_for = _from_iso(task["next_run_at"])
        next_run = self._next_after(
            task["schedule_type"], schedule, scheduled_for, finished,
            task["timezone"] or "local",
        )
        run_status = "failed" if error else "succeeded"
        task_status = "active" if next_run else ("failed" if error else "completed")
        with self.database.connect() as connection:
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
