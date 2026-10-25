"""Atomic technical audit for productive Memory-v2 claim mutations.

The module observes SQL mutations already chosen by the existing domain code.  It
does not decide whether a claim should be created, changed, or retired.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps

from .memory_runtime_telemetry import MemoryRuntimeRecorder, TelemetryContractError


WRITER_VERSION = "memory-lifecycle-v1"
CHANGE_KINDS = {
    "created", "activated", "confirmed", "updated", "retired", "invalidated",
    "superseded", "restored",
}
CLAIM_FIELDS = (
    "claim_kind", "scope", "canonical_key", "slot_key", "display_text", "payload_json",
    "lifecycle", "valid_from", "valid_until", "verification_policy", "created_at", "updated_at",
)
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,255}$")
_ORIGIN: ContextVar[dict | None] = ContextVar("memory_lifecycle_origin", default=None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_identifier(value, fallback: str) -> str:
    text = str(value or "")
    if _IDENTIFIER.fullmatch(text):
        return text
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
    return f"{fallback}:{digest}"


def _turn_from_source(source_ref) -> str | None:
    text = str(source_ref or "")
    if not text.startswith("turn:"):
        return None
    value = text.removeprefix("turn:").strip()
    if not value:
        return None
    try:
        return uuid.UUID(value).hex
    except ValueError:
        return _bounded_identifier(value, "turn")


def current_lifecycle_origin() -> dict:
    existing = _ORIGIN.get()
    if existing is not None:
        return dict(existing)
    trace_id = uuid.uuid4().hex
    return {
        "trace_id": trace_id,
        "operation_id": uuid.uuid4().hex,
        "producer": "memory.lifecycle",
        "reason_code": "direct_claim_mutation",
    }


def lifecycle_operation(producer: str, reason_code: str | None = None, *, extractor=None):
    """Attach technical provenance to claim writes performed by a function."""
    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            bound = signature.bind_partial(*args, **kwargs)
            values = bound.arguments
            extra = dict(extractor(values) if extractor else {})
            source_ref = extra.pop("source_ref", values.get("source_ref"))
            turn_id = extra.pop("turn_id", values.get("source_turn_id") or values.get("turn_id"))
            trace_id = extra.pop("trace_id", values.get("trace_id"))
            parsed_turn = _turn_from_source(source_ref)
            turn_id = str(turn_id) if turn_id else parsed_turn
            trace_id = str(trace_id) if trace_id else turn_id
            if trace_id is None:
                trace_id = uuid.uuid4().hex
            origin = {
                "trace_id": _bounded_identifier(trace_id, "trace"),
                "operation_id": _bounded_identifier(
                    extra.pop(
                        "operation_id",
                        f"{producer}:{reason_code or function.__name__}:{source_ref or uuid.uuid4().hex}",
                    ),
                    "operation",
                ),
                "producer": _bounded_identifier(producer, "producer"),
                "reason_code": _bounded_identifier(
                    extra.pop("reason_code", reason_code or function.__name__), "reason",
                ),
            }
            if turn_id:
                origin["turn_id"] = _bounded_identifier(turn_id, "turn")
            for key in ("conversation_id", "learning_decision_id", "change_kind"):
                value = extra.pop(key, values.get(key))
                if value is not None:
                    origin[key] = _bounded_identifier(value, key)
            origin.update(extra)
            token = _ORIGIN.set(origin)
            try:
                return function(*args, **kwargs)
            finally:
                _ORIGIN.reset(token)

        return wrapped
    return decorate


def install_connection_audit(connection, *, started_at: str | None = None) -> None:
    """Install connection-local capture triggers; no persistent schema is changed."""
    started_at = started_at or _now()
    connection.execute("PRAGMA temp_store = MEMORY")
    connection.execute("""CREATE TEMP TABLE IF NOT EXISTS _eve_claim_lifecycle_audit (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        occurred_at TEXT NOT NULL,
        origin_json TEXT NOT NULL,
        claim_id TEXT NOT NULL,
        before_json TEXT,
        after_json TEXT
    )""")
    connection.execute("""CREATE TEMP TABLE IF NOT EXISTS _eve_claim_lifecycle_context (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        started_at TEXT NOT NULL
    )""")
    connection.execute("""CREATE TEMP TABLE IF NOT EXISTS _eve_claim_reference_audit (
        claim_id TEXT NOT NULL,
        reference_kind TEXT NOT NULL CHECK(reference_kind IN ('evidence','relation')),
        reference_id TEXT NOT NULL,
        relation_type TEXT,
        relation_target_id TEXT
    )""")
    connection.execute(
        "INSERT OR REPLACE INTO temp._eve_claim_lifecycle_context(singleton,started_at) VALUES (1,?)",
        (started_at,),
    )
    fallback_origin = current_lifecycle_origin()
    connection.create_function(
        "eve_lifecycle_origin", 0,
        lambda: json.dumps(
            dict(_ORIGIN.get() or fallback_origin), sort_keys=True, separators=(",", ":"),
        ),
    )
    # Concatenation removes SQLite JSON subtypes produced by json_set/json_patch.
    # The persisted column is TEXT, so both sides then hash exactly as stored.
    old = "json_object(" + ",".join(
        f"'{field}',CASE WHEN OLD.{field} IS NULL THEN NULL ELSE OLD.{field}||'' END"
        for field in ("id", *CLAIM_FIELDS)
    ) + ")"
    new = "json_object(" + ",".join(
        f"'{field}',CASE WHEN NEW.{field} IS NULL THEN NULL ELSE NEW.{field}||'' END"
        for field in ("id", *CLAIM_FIELDS)
    ) + ")"
    connection.executescript(f"""
        CREATE TEMP TRIGGER IF NOT EXISTS _eve_claim_lifecycle_insert
        AFTER INSERT ON main.memory_claims BEGIN
            INSERT INTO _eve_claim_lifecycle_audit(occurred_at,origin_json,claim_id,before_json,after_json)
            VALUES (strftime('%Y-%m-%dT%H:%M:%fZ','now'),eve_lifecycle_origin(),NEW.id,NULL,{new});
        END;
        CREATE TEMP TRIGGER IF NOT EXISTS _eve_claim_lifecycle_update
        AFTER UPDATE ON main.memory_claims BEGIN
            INSERT INTO _eve_claim_lifecycle_audit(occurred_at,origin_json,claim_id,before_json,after_json)
            VALUES (strftime('%Y-%m-%dT%H:%M:%fZ','now'),eve_lifecycle_origin(),NEW.id,{old},{new});
        END;
        CREATE TEMP TRIGGER IF NOT EXISTS _eve_claim_lifecycle_delete
        AFTER DELETE ON main.memory_claims BEGIN
            INSERT INTO _eve_claim_lifecycle_audit(occurred_at,origin_json,claim_id,before_json,after_json)
            VALUES (strftime('%Y-%m-%dT%H:%M:%fZ','now'),eve_lifecycle_origin(),OLD.id,{old},NULL);
        END;
        CREATE TEMP TRIGGER IF NOT EXISTS _eve_claim_evidence_reference
        AFTER INSERT ON main.memory_evidence BEGIN
            INSERT INTO _eve_claim_reference_audit(claim_id,reference_kind,reference_id)
            VALUES (NEW.claim_id,'evidence',NEW.id);
        END;
        CREATE TEMP TRIGGER IF NOT EXISTS _eve_claim_relation_from_reference
        AFTER INSERT ON main.memory_relations BEGIN
            INSERT INTO _eve_claim_reference_audit(
                claim_id,reference_kind,reference_id,relation_type,relation_target_id
            ) VALUES (NEW.from_claim_id,'relation',NEW.id,NEW.relation_type,NEW.to_claim_id);
        END;
        CREATE TEMP TRIGGER IF NOT EXISTS _eve_claim_relation_to_reference
        AFTER INSERT ON main.memory_relations BEGIN
            INSERT INTO _eve_claim_reference_audit(
                claim_id,reference_kind,reference_id,relation_type,relation_target_id
            ) VALUES (NEW.to_claim_id,'relation',NEW.id,NEW.relation_type,NEW.to_claim_id);
        END;
    """)


def set_connection_lifecycle_origin(connection, **origin) -> None:
    """Override provenance for subsequent mutations on an already open connection."""
    normalized = current_lifecycle_origin()
    normalized.update({key: value for key, value in origin.items() if value is not None})
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    connection.create_function("eve_lifecycle_origin", 0, lambda: encoded)


def _snapshot_digest(snapshot: dict) -> str:
    value = {field: snapshot.get(field) for field in CLAIM_FIELDS}
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _states(before: dict | None, after: dict) -> tuple[str, str]:
    if before is None:
        return "absent", str(after.get("lifecycle") or "unknown")
    old, new = str(before.get("lifecycle") or "unknown"), str(after.get("lifecycle") or "unknown")
    if old != new:
        return old, new
    return f"{old}:{_snapshot_digest(before)[:16]}", f"{new}:{_snapshot_digest(after)[:16]}"


def _change_kind(before: dict | None, after: dict, changed: list[str], origin: dict,
                 *, superseded: bool = False) -> str:
    requested = origin.get("change_kind")
    if requested in CHANGE_KINDS:
        return requested
    if before is None:
        return "created"
    old, new = before.get("lifecycle"), after.get("lifecycle")
    reason = str(origin.get("reason_code") or "").casefold()
    if old != new:
        if new == "active" and old == "candidate":
            return "activated"
        if new == "active" and old in {"retired", "invalid"}:
            return "restored"
        if new == "invalid":
            return "invalidated"
        if new == "retired":
            return "superseded" if superseded or any(
                word in reason for word in ("supersed", "correct", "replace")
            ) else "retired"
    if "payload_json" in changed and any(word in reason for word in ("confirm", "corroborat")):
        return "confirmed"
    return "updated"


class MemoryLifecycleWriter:
    """Flush captured claim changes through the Phase-5B validator in one transaction."""

    def __init__(self, database, *, max_detail_bytes: int = 4096):
        self.database = database
        self.recorder = MemoryRuntimeRecorder(
            database, enabled=True, max_detail_bytes=max_detail_bytes,
        )

    @staticmethod
    def _references(connection, claim_id: str) -> tuple[list[str], list[str], bool]:
        evidence = [str(row[0]) for row in connection.execute(
            """SELECT DISTINCT reference_id FROM temp._eve_claim_reference_audit
               WHERE claim_id=? AND reference_kind='evidence'
               ORDER BY reference_id LIMIT 16""", (claim_id,),
        ).fetchall()]
        relation_rows = connection.execute(
            """SELECT DISTINCT reference_id,relation_type,relation_target_id
               FROM temp._eve_claim_reference_audit
               WHERE claim_id=? AND reference_kind='relation'
               ORDER BY reference_id LIMIT 16""", (claim_id,),
        ).fetchall()
        relations = [str(row[0]) for row in relation_rows]
        superseded = any(
            row["relation_type"] == "supersedes" and row["relation_target_id"] == claim_id
            for row in relation_rows
        )
        return evidence, relations, superseded

    def flush(self, connection) -> list[dict]:
        rows = connection.execute(
            "SELECT * FROM temp._eve_claim_lifecycle_audit ORDER BY sequence"
        ).fetchall()
        if not rows:
            return []
        events, traces = [], {}
        for row in rows:
            before = json.loads(row["before_json"]) if row["before_json"] else None
            after = json.loads(row["after_json"]) if row["after_json"] else None
            if after is None:
                raise TelemetryContractError("memory claims must be retired instead of deleted")
            changed = [
                field for field in CLAIM_FIELDS
                if before is None and after.get(field) is not None
                or before is not None and before.get(field) != after.get(field)
            ]
            if not changed:
                continue
            origin = json.loads(row["origin_json"])
            trace_id = _bounded_identifier(origin.get("trace_id"), "trace")
            occurred_at = str(row["occurred_at"] or _now())
            traces.setdefault(trace_id, (origin.get("conversation_id"), occurred_at))
            state_before, state_after = _states(before, after)
            evidence_ids, relation_ids, superseded = self._references(
                connection, str(row["claim_id"]),
            )
            details = {
                "change_kind": _change_kind(
                    before, after, changed, origin, superseded=superseded,
                ),
                "changed_fields": changed,
                "writer_version": WRITER_VERSION,
            }
            if evidence_ids:
                details["evidence_ids"] = evidence_ids
            if relation_ids:
                details["relation_ids"] = relation_ids
            operation_base = _bounded_identifier(origin.get("operation_id"), "operation")
            event = {
                "trace_id": trace_id,
                "event_kind": "claim_lifecycle_changed",
                "occurred_at": occurred_at,
                "operation_id": _bounded_identifier(f"{operation_base}:{row['sequence']}", "operation"),
                "claim_id": str(row["claim_id"]),
                "producer": _bounded_identifier(origin.get("producer"), "producer"),
                "proof_level": "atomic_lifecycle",
                "event_status": "completed",
                "state_before": state_before,
                "state_after": state_after,
                "reason_code": _bounded_identifier(origin.get("reason_code"), "reason"),
                "details": details,
            }
            for key in ("turn_id", "learning_decision_id"):
                if origin.get(key):
                    event[key] = _bounded_identifier(origin[key], key)
            events.append(event)
        if not events:
            return []
        for trace_id, (conversation_id, started_at_value) in traces.items():
            existing = connection.execute(
                "SELECT id FROM memory_runtime_traces WHERE id=?", (trace_id,),
            ).fetchone()
            if existing is None:
                if conversation_id and connection.execute(
                    "SELECT 1 FROM conversations WHERE id=?", (str(conversation_id),),
                ).fetchone() is None:
                    conversation_id = None
                self.recorder.create_trace(
                    trace_id=trace_id, conversation_id=conversation_id,
                    started_at=started_at_value, connection=connection, best_effort=False,
                )
        result = self.recorder.record_events(events, connection=connection, best_effort=False)
        connection.execute("DELETE FROM temp._eve_claim_lifecycle_audit")
        connection.execute("DELETE FROM temp._eve_claim_reference_audit")
        return result
