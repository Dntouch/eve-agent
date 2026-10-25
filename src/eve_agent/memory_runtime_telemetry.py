"""Versioned persistence contract for Memory runtime telemetry.

It validates technical facts, stores bounded metadata, and offers a read-only
query surface without interpreting user language or claiming that an LLM used a
memory.  The atomic lifecycle hook is implemented separately and reuses this
validator and recorder.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import sqlite3
import threading
import uuid
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .memory import redact_sensitive


EVENT_CONTRACT_VERSION = "memory-runtime-events-v1"
EVENT_ID_NAMESPACE = uuid.UUID("e5cabf65-4328-4df4-98d7-dd6ee405390c")
DEFAULT_DETAIL_BYTES = 4096
MAX_DETAIL_DEPTH = 5
MAX_DETAIL_ITEMS = 64
MAX_DETAIL_TOTAL_ITEMS = 256
MAX_DETAIL_STRING = 512
QUERY_LIMIT = 100
# Leave room for Brainwatch's allowlisted projection and pagination metadata.
QUERY_RESPONSE_BYTES = 56 * 1024

PROOF_LEVELS = {
    "trace_boundary", "operation_boundary", "compiler_evaluation",
    "assembled_context", "client_boundary", "transport_payload", "transport_result",
    "deterministic_resolution", "provider_verification", "validated_binding",
    "dispatch_boundary", "provider_response", "verification_result", "action_result",
    "relation_traversal", "consumer_boundary", "atomic_lifecycle", "telemetry_boundary",
}
EVENT_STATUSES = {"started", "completed", "failed", "cancelled", "rejected"}
OUTCOME_STATUSES = {
    "success", "failed", "partial", "outcome_uncertain", "cancelled", "skipped",
    "acknowledged", "denied", "error", "not_available",
}
VERIFICATION_STATUSES = {
    "verified", "contradictory", "in_progress", "inconclusive", "not_available",
    "cancelled", "error", "not_applicable",
}

COMMON_DETAILS = {"component", "elapsed_ms", "batch_size", "error_class"}
COMPILER_DETAILS = {
    "retrieval_method", "token_cost", "rank_score", "requirement_class",
    "compiler_version", "policy_version",
}
CONTEXT_DETAILS = {"message_index", "block_role", "manifest_claim_count"}
TRANSPORT_DETAILS = {
    "finish_reason", "http_status", "prompt_tokens", "completion_tokens", "total_tokens",
    "ttft_ms", "duration_ms", "streaming", "model", "metrics",
}
ACTION_DETAILS = {
    "executor", "service", "operation", "provider_status", "error_code",
    "dispatch_started", "readback_attempts", "target_already_reached",
}
LIFECYCLE_DETAILS = {
    "change_kind", "changed_fields", "writer_version", "evidence_ids", "relation_ids",
}
QUERY_DETAILS = {"query_kind", "result_count", "scope_count"}


def _contract(
    subject: str, required=(), proofs=(), statuses=("completed",), *,
    outcomes=(), verifications=(), details=(), required_details=(),
) -> dict:
    return {
        "subject": subject,
        "required": frozenset(required),
        "proofs": frozenset(proofs),
        "statuses": frozenset(statuses),
        "outcomes": frozenset(outcomes),
        "verifications": frozenset(verifications),
        "details": frozenset(COMMON_DETAILS | set(details)),
        "required_details": frozenset(required_details),
    }


EVENT_CONTRACTS = {
    "trace_started": _contract("none", proofs={"trace_boundary"}, statuses={"started"}),
    "operation_started": _contract(
        "none", proofs={"operation_boundary"}, statuses={"started"},
    ),
    "operation_completed": _contract(
        "none", proofs={"operation_boundary"}, outcomes=OUTCOME_STATUSES,
    ),
    "operation_aborted": _contract(
        "none", proofs={"operation_boundary"}, statuses={"failed", "cancelled"},
        outcomes={"failed", "cancelled", "outcome_uncertain"},
    ),
    "telemetry_persist_failed": _contract(
        "none", proofs={"telemetry_boundary"}, statuses={"failed"},
        required_details={"error_class"},
    ),
    "transport_failed": _contract(
        "none", required={"attempt_id", "attempt_no"}, proofs={"transport_result"},
        statuses={"failed", "cancelled"},
        outcomes={"failed", "cancelled", "error"}, details=TRANSPORT_DETAILS,
    ),
    "llm_transport_result": _contract(
        "none", required={"llm_call_id", "attempt_id", "attempt_no"},
        proofs={"transport_result"}, statuses={"completed", "failed", "cancelled"},
        outcomes={"success", "failed", "cancelled", "error"}, details=TRANSPORT_DETAILS,
    ),
    "claim_retrieved": _contract(
        "claim", required={"compiler_evaluation_id", "consumer"},
        proofs={"compiler_evaluation"}, details=COMPILER_DETAILS,
        required_details={"retrieval_method"},
    ),
    "claim_eligible": _contract(
        "claim", required={"compiler_evaluation_id", "consumer"},
        proofs={"compiler_evaluation"}, details=COMPILER_DETAILS,
    ),
    "claim_selected_for_view": _contract(
        "claim", required={"compiler_evaluation_id", "consumer", "ordinal"},
        proofs={"compiler_evaluation"}, details=COMPILER_DETAILS,
    ),
    "claim_returned_to_consumer": _contract(
        "claim", required={"compiler_evaluation_id", "consumer", "ordinal"},
        proofs={"consumer_boundary"}, details=COMPILER_DETAILS,
    ),
    "relation_traversed_for_retrieval": _contract(
        "relation", required={"compiler_evaluation_id", "consumer"},
        proofs={"relation_traversal"}, details=COMPILER_DETAILS,
    ),
    "claim_added_to_prompt_context": _contract(
        "claim", required={"planner_round_id", "llm_call_id", "consumer",
                           "compiler_evaluation_id", "context_block_id",
                           "context_manifest_digest", "ordinal"},
        proofs={"assembled_context"}, details=CONTEXT_DETAILS,
    ),
    "claim_received_by_llm_client": _contract(
        "claim", required={"planner_round_id", "llm_call_id", "attempt_id", "attempt_no",
                           "consumer", "compiler_evaluation_id", "context_block_id",
                           "context_manifest_digest", "ordinal"},
        proofs={"client_boundary"}, details=CONTEXT_DETAILS,
    ),
    "claim_serialized_for_transport": _contract(
        "claim", required={"planner_round_id", "llm_call_id", "attempt_id", "attempt_no",
                           "consumer", "compiler_evaluation_id", "context_block_id",
                           "context_manifest_digest", "ordinal"},
        proofs={"transport_payload"}, details=CONTEXT_DETAILS,
    ),
    "claim_query_started": _contract(
        "none", required={"consumer"}, proofs={"operation_boundary"},
        statuses={"started"}, details=QUERY_DETAILS,
    ),
    "claim_resolved": _contract(
        "claim", required={"consumer"}, proofs={"deterministic_resolution"},
        details=QUERY_DETAILS,
    ),
    "claim_technical_verification": _contract(
        "claim", required={"provider", "target_resource_id"},
        proofs={"provider_verification"},
        statuses={"completed", "failed", "cancelled"}, verifications=VERIFICATION_STATUSES,
        details=ACTION_DETAILS,
    ),
    "claim_bound_to_plan": _contract(
        "claim", required={"planner_round_id", "plan_id"}, proofs={"validated_binding"},
    ),
    "alias_read_for_stt": _contract(
        "claim", required={"consumer"}, proofs={"deterministic_resolution"},
        details=QUERY_DETAILS,
    ),
    "claim_bound_to_action": _contract(
        "claim", required={"planner_round_id", "plan_id", "action_id", "action_index",
                           "provider", "target_resource_id"},
        proofs={"validated_binding"}, details=ACTION_DETAILS,
        required_details={"executor"},
    ),
    "action_dispatch_attempted_with_claim": _contract(
        "claim", required={"planner_round_id", "plan_id", "action_id", "action_index",
                           "attempt_id", "attempt_no", "provider", "target_resource_id"},
        proofs={"dispatch_boundary"}, statuses={"started"}, details=ACTION_DETAILS,
        required_details={"executor"},
    ),
    "action_provider_response_with_claim": _contract(
        "claim", required={"planner_round_id", "plan_id", "action_id", "action_index",
                           "attempt_id", "attempt_no", "provider", "target_resource_id"},
        proofs={"provider_response"}, statuses={"completed", "failed", "cancelled"},
        outcomes={"acknowledged", "denied", "error", "outcome_uncertain", "cancelled"},
        details=ACTION_DETAILS, required_details={"executor"},
    ),
    "action_verification_with_claim": _contract(
        "claim", required={"planner_round_id", "plan_id", "action_id", "action_index",
                           "provider", "target_resource_id"},
        proofs={"verification_result"}, statuses={"completed", "failed", "cancelled"},
        verifications=VERIFICATION_STATUSES, details=ACTION_DETAILS,
        required_details={"executor"},
    ),
    "action_completed_with_claim": _contract(
        "claim", required={"planner_round_id", "plan_id", "action_id", "action_index",
                           "provider", "target_resource_id"},
        proofs={"action_result"}, statuses={"completed", "failed", "cancelled"},
        outcomes={"success", "failed", "partial", "outcome_uncertain", "cancelled", "skipped"},
        details=ACTION_DETAILS, required_details={"executor"},
    ),
    "relation_bound_to_plan": _contract(
        "relation", required={"planner_round_id", "plan_id"}, proofs={"validated_binding"},
    ),
    "claim_lifecycle_changed": _contract(
        "claim", required={"state_after", "reason_code"}, proofs={"atomic_lifecycle"},
        details=LIFECYCLE_DETAILS, required_details={"change_kind", "changed_fields"},
    ),
}

EVENT_KINDS = frozenset(EVENT_CONTRACTS)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,255}$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_SECRET_KEYS = {
    "token", "accesstoken", "refreshtoken", "apikey", "authorization", "authheader",
    "password", "passwd", "passwort", "secret", "clientsecret", "cookie", "setcookie",
    "credential", "credentials", "localkey",
}
_FORBIDDEN_DETAIL_KEYS = {
    "prompt", "messages", "response", "modelresponse", "providerresponse", "body", "headers",
    "usercontent", "usertext", "claimtext", "displaytext", "rawpayload", "payload",
}


def _forbidden_detail_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
    if normalized in _FORBIDDEN_DETAIL_KEYS:
        return True
    if normalized.endswith((
        "providerresponse", "modelresponse", "rawpayload", "usercontent", "usertext",
        "claimtext", "displaytext", "completiontext", "modeloutput",
    )):
        return True
    return normalized.startswith("prompt") and normalized.endswith(
        ("text", "content", "body", "messages", "payload")
    )


class TelemetryContractError(ValueError):
    pass


class TelemetryDedupeConflict(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identifier(value, field: str, *, required: bool = False) -> str | None:
    if value is None or value == "":
        if required:
            raise TelemetryContractError(f"{field} is required")
        return None
    text = str(value)
    if not _IDENTIFIER.fullmatch(text):
        raise TelemetryContractError(f"{field} is not a bounded technical identifier")
    return text


def _timestamp(value, field: str) -> str:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TelemetryContractError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise TelemetryContractError(f"{field} must include a timezone")
    return text


def _secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
    return (
        normalized in _SECRET_KEYS
        or normalized.endswith("token")
        or normalized.endswith("accesstoken")
        or any(marker in normalized for marker in (
            "apikey", "authorization", "authheader", "password", "passwd", "passwort",
            "secret", "cookie", "credential", "localkey",
        ))
    )


def _safe_url(text: str) -> str:
    try:
        parsed = urlsplit(text)
    except ValueError:
        return text
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return text
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        return text
    if port:
        host += f":{port}"
    return urlunsplit((parsed.scheme.casefold(), host, parsed.path, "", ""))


def _redact_detail(value, *, key: str = "", depth: int = 0, budget=None):
    if _secret_key(key):
        return "[REDACTED]"
    if budget is None:
        budget = [0]
    if depth > MAX_DETAIL_DEPTH:
        raise TelemetryContractError("details exceed the maximum depth")
    if isinstance(value, dict):
        if len(value) > MAX_DETAIL_ITEMS:
            raise TelemetryContractError("details contain too many object fields")
        budget[0] += len(value)
        if budget[0] > MAX_DETAIL_TOTAL_ITEMS:
            raise TelemetryContractError("details contain too many total items")
        result = {}
        for child_key, child in value.items():
            if not isinstance(child_key, str):
                raise TelemetryContractError("detail keys must be strings")
            safe_key = child_key
            if len(safe_key) > 80:
                raise TelemetryContractError("detail key is too long")
            if _forbidden_detail_key(safe_key):
                raise TelemetryContractError(f"detail field is not permitted: {safe_key}")
            result[safe_key] = _redact_detail(
                child, key=safe_key, depth=depth + 1, budget=budget,
            )
        return result
    if isinstance(value, list):
        if len(value) > MAX_DETAIL_ITEMS:
            raise TelemetryContractError("details contain too many list items")
        budget[0] += len(value)
        if budget[0] > MAX_DETAIL_TOTAL_ITEMS:
            raise TelemetryContractError("details contain too many total items")
        return [
            _redact_detail(child, key=key, depth=depth + 1, budget=budget)
            for child in value
        ]
    if isinstance(value, str):
        redacted = redact_sensitive(value)
        cleaned = _safe_url(redacted)
        if len(cleaned) > MAX_DETAIL_STRING:
            raise TelemetryContractError("detail string is too long")
        if cleaned == "[REDACTED]":
            return cleaned
        try:
            parsed = urlsplit(redacted)
            is_url = parsed.scheme.casefold() in {"http", "https"} and bool(parsed.netloc)
        except ValueError:
            is_url = False
        if not is_url and not _IDENTIFIER.fullmatch(cleaned):
            raise TelemetryContractError("detail strings must be technical identifiers")
        return cleaned
    if isinstance(value, float) and not math.isfinite(value):
        raise TelemetryContractError("details contain a non-finite number")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TelemetryContractError("details contain an unsupported value")


def sanitize_details(event_kind: str, details, *, max_bytes: int = DEFAULT_DETAIL_BYTES) -> dict:
    contract = EVENT_CONTRACTS[event_kind]
    if details is None:
        details = {}
    if not isinstance(details, dict):
        raise TelemetryContractError("details must be an object")
    if any(not isinstance(key, str) for key in details):
        raise TelemetryContractError("detail keys must be strings")
    unknown = set(details) - set(contract["details"])
    if unknown:
        raise TelemetryContractError(f"detail field is not allowlisted: {sorted(unknown)[0]}")
    safe = _redact_detail(details)
    missing = set(contract["required_details"]) - set(safe)
    if missing:
        raise TelemetryContractError(
            f"required detail is missing for {event_kind}: {sorted(missing)[0]}"
        )
    encoded = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > int(max_bytes):
        raise TelemetryContractError("details exceed the byte budget")
    return safe


def _canonical_digest(value: dict) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _dedupe_key(event: dict) -> str:
    identity = {
        "v": EVENT_CONTRACT_VERSION,
        "trace_id": event["trace_id"], "event_kind": event["event_kind"],
        "operation_id": event["operation_id"], "producer": event["producer"],
        "proof_level": event["proof_level"], "turn_id": event.get("turn_id"),
        "planner_round_id": event.get("planner_round_id"), "plan_id": event.get("plan_id"),
        "attempt_id": event.get("attempt_id"),
        "claim_id": event.get("claim_id"), "relation_id": event.get("relation_id"),
        "llm_call_id": event.get("llm_call_id"), "action_id": event.get("action_id"),
        "consumer": event.get("consumer"), "tool_event_id": event.get("tool_event_id"),
        "compiler_evaluation_id": event.get("compiler_evaluation_id"),
        "learning_decision_id": event.get("learning_decision_id"),
        "context_block_id": event.get("context_block_id"),
        "ordinal": event.get("ordinal"),
    }
    return _canonical_digest(identity)


def validate_event(raw: dict, *, max_detail_bytes: int = DEFAULT_DETAIL_BYTES) -> dict:
    if not isinstance(raw, dict):
        raise TelemetryContractError("event must be an object")
    allowed = {
        "trace_id", "event_kind", "occurred_at", "operation_id", "parent_event_id", "turn_id",
        "planner_round_id", "plan_id", "llm_call_id", "attempt_id", "attempt_no", "consumer",
        "action_id", "action_index", "tool_event_id", "compiler_evaluation_id", "claim_id",
        "relation_id", "learning_decision_id", "producer", "proof_level", "event_status",
        "outcome_status", "verification_status", "provider", "target_resource_id", "state_before",
        "state_after", "reason_code", "context_block_id", "context_manifest_digest", "ordinal",
        "details",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise TelemetryContractError(f"unknown event field: {sorted(unknown)[0]}")
    kind = str(raw.get("event_kind") or "")
    if kind not in EVENT_CONTRACTS:
        raise TelemetryContractError("event_kind is not published")
    contract = EVENT_CONTRACTS[kind]
    event = {key: raw.get(key) for key in allowed if key != "details"}
    for field in (
        "trace_id", "operation_id", "parent_event_id", "turn_id", "planner_round_id", "plan_id",
        "llm_call_id", "attempt_id", "consumer", "action_id", "tool_event_id",
        "compiler_evaluation_id", "claim_id", "relation_id", "learning_decision_id", "producer",
        "provider", "target_resource_id", "state_before", "state_after", "reason_code",
        "context_block_id",
    ):
        event[field] = _identifier(
            event.get(field), field, required=field in {"trace_id", "operation_id", "producer"},
        )
    event["event_kind"] = kind
    if not raw.get("occurred_at"):
        raise TelemetryContractError("occurred_at is required")
    event["occurred_at"] = _timestamp(raw["occurred_at"], "occurred_at")
    event["proof_level"] = str(raw.get("proof_level") or "")
    event["event_status"] = str(raw.get("event_status") or "")
    event["outcome_status"] = str(raw["outcome_status"]) if raw.get("outcome_status") else None
    event["verification_status"] = (
        str(raw["verification_status"]) if raw.get("verification_status") else None
    )
    if event["proof_level"] not in contract["proofs"]:
        raise TelemetryContractError("proof_level is invalid for event_kind")
    if event["event_status"] not in contract["statuses"]:
        raise TelemetryContractError("event_status is invalid for event_kind")
    if bool(contract["outcomes"]) != bool(event["outcome_status"]):
        raise TelemetryContractError("outcome_status presence is invalid for event_kind")
    if event["outcome_status"] and event["outcome_status"] not in contract["outcomes"]:
        raise TelemetryContractError("outcome_status is invalid for event_kind")
    if bool(contract["verifications"]) != bool(event["verification_status"]):
        raise TelemetryContractError("verification_status presence is invalid for event_kind")
    if event["verification_status"] and event["verification_status"] not in contract["verifications"]:
        raise TelemetryContractError("verification_status is invalid for event_kind")
    subject = contract["subject"]
    if subject == "claim" and (not event["claim_id"] or event["relation_id"]):
        raise TelemetryContractError("claim event requires only claim_id")
    if subject == "relation" and (not event["relation_id"] or event["claim_id"]):
        raise TelemetryContractError("relation event requires only relation_id")
    if subject == "none" and (event["claim_id"] or event["relation_id"]):
        raise TelemetryContractError("technical event cannot declare a claim or relation subject")
    for field in contract["required"]:
        if event.get(field) is None:
            raise TelemetryContractError(f"{field} is required for {kind}")
    attempt_id, attempt_no = event.get("attempt_id"), raw.get("attempt_no")
    if (attempt_id is None) != (attempt_no is None):
        raise TelemetryContractError("attempt_id and attempt_no must occur together")
    if attempt_no is not None and (type(attempt_no) is not int or attempt_no < 1):
        raise TelemetryContractError("attempt_no must be a positive integer")
    event["attempt_no"] = attempt_no
    for field in ("action_index", "ordinal"):
        value = raw.get(field)
        if value is not None and (type(value) is not int or value < 0):
            raise TelemetryContractError(f"{field} must be a non-negative integer")
        event[field] = value
    digest = raw.get("context_manifest_digest")
    if digest is not None and not _DIGEST.fullmatch(str(digest)):
        raise TelemetryContractError("context_manifest_digest must be a SHA-256 digest")
    event["context_manifest_digest"] = str(digest) if digest is not None else None
    if kind == "claim_lifecycle_changed" and event["state_before"] == event["state_after"]:
        raise TelemetryContractError("lifecycle event must change state")
    event["details"] = sanitize_details(kind, raw.get("details"), max_bytes=max_detail_bytes)
    return event


class MemoryRuntimeRecorder:
    """Idempotent writer with short transactions and optional fail-open behavior."""

    def __init__(self, database, *, enabled: bool = False,
                 contract_version: str = EVENT_CONTRACT_VERSION,
                 max_detail_bytes: int = DEFAULT_DETAIL_BYTES):
        if contract_version != EVENT_CONTRACT_VERSION:
            raise TelemetryContractError("unsupported telemetry contract version")
        self.database = database
        self.enabled = bool(enabled)
        self.contract_version = contract_version
        self.max_detail_bytes = int(max_detail_bytes)
        self._diagnostics = []
        self._lock = threading.Lock()

    def diagnostics(self) -> list[dict]:
        with self._lock:
            return deepcopy(self._diagnostics)

    def _diagnose(self, operation: str, exc: Exception) -> None:
        item = {
            "operation": operation,
            "error_class": type(exc).__name__,
            "message": redact_sensitive(str(exc))[:500],
            "at": _now(),
        }
        with self._lock:
            self._diagnostics.append(item)
            del self._diagnostics[:-32]

    def create_trace(self, *, trace_id: str | None = None, conversation_id: str | None = None,
                     started_at: str | None = None, connection=None, best_effort: bool = False) -> str | None:
        if not self.enabled:
            return None
        try:
            trace_id = _identifier(trace_id or str(uuid.uuid4()), "trace_id", required=True)
            conversation_id = _identifier(conversation_id, "conversation_id")
            started_at = _timestamp(started_at or _now(), "started_at")
            values = (trace_id, conversation_id, started_at, self.contract_version)
            if connection is not None:
                self._insert_trace(connection, values)
            else:
                with self.database.connect() as current:
                    current.execute("BEGIN IMMEDIATE")
                    self._insert_trace(current, values)
            return trace_id
        except Exception as exc:
            if not best_effort:
                raise
            self._diagnose("create_trace", exc)
            return None

    @staticmethod
    def _insert_trace(connection, values) -> None:
        try:
            connection.execute(
                "INSERT INTO memory_runtime_traces(id,conversation_id,started_at,telemetry_version) VALUES (?,?,?,?)",
                values,
            )
        except sqlite3.IntegrityError as exc:
            row = connection.execute(
                "SELECT id,conversation_id,started_at,telemetry_version FROM memory_runtime_traces WHERE id=?",
                (values[0],),
            ).fetchone()
            if row is None:
                raise
            if tuple(row) != values:
                raise TelemetryDedupeConflict("trace identity conflicts with persisted content") from exc

    def record_event(self, event: dict, *, connection=None, best_effort: bool = False) -> dict | None:
        result = self.record_events([event], connection=connection, best_effort=best_effort)
        return result[0] if result else None

    def record_events(self, events: list[dict], *, connection=None,
                      best_effort: bool = False) -> list[dict]:
        if not self.enabled:
            return []
        try:
            if not isinstance(events, list) or not events:
                raise TelemetryContractError("events must be a non-empty list")
            prepared = [self._prepare_event(event) for event in events]
            if connection is not None:
                connection.execute("SAVEPOINT memory_runtime_batch")
                try:
                    result = [self._insert_event(connection, item) for item in prepared]
                    connection.execute("RELEASE SAVEPOINT memory_runtime_batch")
                    return result
                except Exception:
                    connection.execute("ROLLBACK TO SAVEPOINT memory_runtime_batch")
                    connection.execute("RELEASE SAVEPOINT memory_runtime_batch")
                    raise
            with self.database.connect() as current:
                current.execute("BEGIN IMMEDIATE")
                return [self._insert_event(current, item) for item in prepared]
        except Exception as exc:
            if not best_effort:
                raise
            self._diagnose("record_events", exc)
            return []

    def record_trace_events(self, events: list[dict], *, trace_id: str,
                            conversation_id: str | None = None,
                            started_at: str | None = None,
                            best_effort: bool = False) -> list[dict]:
        """Persist one bounded runtime batch and its trace atomically.

        A pre-existing trace is reused as the causal root.  Its original
        metadata remains authoritative, which lets independent optional
        producers share a turn trace without racing over its start time.
        """
        if not self.enabled:
            return []
        try:
            trace_id = _identifier(trace_id, "trace_id", required=True)
            conversation_id = _identifier(conversation_id, "conversation_id")
            started_at = _timestamp(started_at or _now(), "started_at")
            if not isinstance(events, list) or not events:
                raise TelemetryContractError("events must be a non-empty list")
            prepared = [self._prepare_event(event) for event in events]
            with self.database.connect(lifecycle_audit=False) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT id FROM memory_runtime_traces WHERE id=?", (trace_id,),
                ).fetchone()
                if row is None:
                    self._insert_trace(connection, (
                        trace_id, conversation_id, started_at, self.contract_version,
                    ))
                return [self._insert_event(connection, item) for item in prepared]
        except Exception as exc:
            if not best_effort:
                raise
            self._diagnose("record_trace_events", exc)
            return []

    def _prepare_event(self, raw: dict) -> dict:
        event = validate_event(raw, max_detail_bytes=self.max_detail_bytes)
        event["recorded_at"] = _now()
        event["details_json"] = json.dumps(
            event.pop("details"), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        event["dedupe_key"] = _dedupe_key(event)
        event["id"] = str(uuid.uuid5(EVENT_ID_NAMESPACE, event["dedupe_key"]))
        event["record_digest"] = _canonical_digest({
            key: value for key, value in event.items() if key not in {"recorded_at", "record_digest"}
        })
        return event

    @staticmethod
    def _insert_event(connection, event: dict) -> dict:
        columns = (
            "id", "trace_id", "event_kind", "occurred_at", "recorded_at", "operation_id",
            "parent_event_id", "turn_id", "planner_round_id", "plan_id", "llm_call_id",
            "attempt_id", "attempt_no", "consumer", "action_id", "action_index", "tool_event_id",
            "compiler_evaluation_id", "claim_id", "relation_id", "learning_decision_id", "producer",
            "proof_level", "event_status", "outcome_status", "verification_status", "provider",
            "target_resource_id", "state_before", "state_after", "reason_code", "context_block_id",
            "context_manifest_digest", "ordinal", "details_json", "dedupe_key", "record_digest",
        )
        values = tuple(event.get(column) for column in columns)
        try:
            connection.execute(
                f"INSERT INTO memory_runtime_events({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                values,
            )
        except sqlite3.IntegrityError as exc:
            row = connection.execute(
                "SELECT id,record_digest FROM memory_runtime_events WHERE dedupe_key=?",
                (event["dedupe_key"],),
            ).fetchone()
            if row is None:
                raise
            if row[0] != event["id"] or row[1] != event["record_digest"]:
                raise TelemetryDedupeConflict(
                    "dedupe key conflicts with different event content"
                ) from exc
        return {"id": event["id"], "dedupe_key": event["dedupe_key"]}


def _cursor_encode(occurred_at: str, identifier: str, binding: str) -> str:
    raw = json.dumps(
        {"v": 1, "occurred_at": occurred_at, "id": identifier, "binding": binding},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cursor_decode(value: str, binding: str) -> tuple[str, str]:
    try:
        padded = str(value) + "=" * (-len(str(value)) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid telemetry cursor") from exc
    if payload.get("v") != 1 or payload.get("binding") != binding:
        raise ValueError("telemetry cursor does not match the query")
    return str(payload["occurred_at"]), str(payload["id"])


class MemoryRuntimeEventReader:
    """Read-only, bounded keyset queries for later Brainwatch projection."""

    FILTER_COLUMNS = {
        "trace_id", "turn_id", "claim_id", "relation_id", "llm_call_id", "action_id",
        "operation_id", "planner_round_id", "plan_id", "attempt_id", "tool_event_id",
        "consumer", "event_kind", "proof_level", "event_status",
    }

    def __init__(self, database_or_path):
        path = getattr(database_or_path, "path", database_or_path)
        self.path = Path(path)

    def _connect(self):
        connection = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA query_only = ON")
        return connection

    @staticmethod
    def _timestamp(value, label: str) -> str:
        value = str(value or "").strip()
        if not value:
            return ""
        if len(value) > 64 or any(ord(character) < 32 for character in value):
            raise ValueError(f"invalid {label}")
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            datetime.fromisoformat(candidate)
        except ValueError:
            raise ValueError(f"invalid {label}") from None
        return value

    def events(self, *, limit: int = 50, cursor: str | None = None,
               timestamp_from: str = "", timestamp_to: str = "", order: str = "asc",
               event_kinds=(), **filters) -> dict:
        unknown = set(filters) - self.FILTER_COLUMNS
        if unknown:
            raise ValueError(f"unknown telemetry filter: {sorted(unknown)[0]}")
        if type(limit) is not int or not 1 <= limit <= QUERY_LIMIT:
            raise ValueError(f"limit must be between 1 and {QUERY_LIMIT}")
        if order not in {"asc", "desc"}:
            raise ValueError("order must be asc or desc")
        timestamp_from = self._timestamp(timestamp_from, "timestamp_from")
        timestamp_to = self._timestamp(timestamp_to, "timestamp_to")
        if timestamp_from and timestamp_to and timestamp_from > timestamp_to:
            raise ValueError("timestamp_from must not be after timestamp_to")
        if event_kinds:
            event_kinds = tuple(dict.fromkeys(str(value) for value in event_kinds))
            if not event_kinds or any(value not in EVENT_KINDS for value in event_kinds):
                raise ValueError("unknown event_kind")
            if "event_kind" in filters:
                raise ValueError("event_kind and event_kinds are mutually exclusive")
        for key, value in filters.items():
            if value is None or value == "":
                raise ValueError(f"{key} must not be empty")
            if key == "event_kind" and value not in EVENT_KINDS:
                raise ValueError("unknown event_kind")
            if key == "proof_level" and value not in PROOF_LEVELS:
                raise ValueError("unknown proof_level")
            if key == "event_status" and value not in EVENT_STATUSES:
                raise ValueError("unknown event_status")
            if len(str(value)) > 512 or any(ord(character) < 32 for character in str(value)):
                raise ValueError(f"invalid {key}")
        binding = _canonical_digest({
            "filters": filters, "event_kinds": event_kinds,
            "timestamp_from": timestamp_from, "timestamp_to": timestamp_to, "order": order,
        })
        clauses, parameters = [], []
        for key in sorted(filters):
            clauses.append(f"{key}=?")
            parameters.append(str(filters[key]))
        if event_kinds:
            clauses.append("event_kind IN (" + ",".join("?" for _ in event_kinds) + ")")
            parameters.extend(event_kinds)
        if timestamp_from:
            clauses.append("occurred_at>=?")
            parameters.append(timestamp_from)
        if timestamp_to:
            clauses.append("occurred_at<=?")
            parameters.append(timestamp_to)
        if cursor:
            occurred_at, identifier = _cursor_decode(cursor, binding)
            operator = ">" if order == "asc" else "<"
            clauses.append(f"(occurred_at{operator}? OR (occurred_at=? AND id{operator}?))")
            parameters.extend([occurred_at, occurred_at, identifier])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        direction = "ASC" if order == "asc" else "DESC"
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM memory_runtime_events" + where
                + f" ORDER BY occurred_at {direction},id {direction} LIMIT ?", (*parameters, limit + 1),
            ).fetchall()
        query_has_more = len(rows) > limit
        rows = rows[:limit]
        items, returned_rows = [], []
        for row in rows:
            item = self._project(row)
            candidate = {"items": [*items, item]}
            if len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) > QUERY_RESPONSE_BYTES:
                break
            items.append(item)
            returned_rows.append(row)
        has_more = query_has_more or len(returned_rows) < len(rows)
        next_cursor = (
            _cursor_encode(returned_rows[-1]["occurred_at"], returned_rows[-1]["id"], binding)
            if has_more and returned_rows else None
        )
        return {"items": items, "page": {
            "limit": limit, "has_more": has_more, "next_cursor": next_cursor,
        }}

    @staticmethod
    def _project(row) -> dict:
        item = dict(row)
        try:
            details = json.loads(item.pop("details_json"))
        except (TypeError, ValueError):
            details = {"_invalid_json": True}
        item["details"] = _redact_detail(details)
        return item

    def event(self, event_id: str) -> dict | None:
        event_id = str(event_id or "").strip()
        if not event_id or len(event_id) > 512 or any(ord(character) < 32 for character in event_id):
            raise ValueError("invalid event id")
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM memory_runtime_events WHERE id=? LIMIT 1", (event_id,),
            ).fetchone()
        return self._project(row) if row is not None else None

    def ingested_events(self, turn_id: str, *, cursor: str | None = None,
                        limit: int = 50, tail: bool = False) -> dict:
        """Read append-only events by SQLite insertion sequence.

        This cursor intentionally does not use occurred_at: a producer may
        persist an older occurrence after a newer one, and live consumers
        still need to observe that late write exactly once.
        """
        turn_id = str(turn_id or "").strip()
        if not turn_id or len(turn_id) > 512 or any(ord(char) < 32 for char in turn_id):
            raise ValueError("invalid turn_id")
        if type(limit) is not int or not 1 <= limit <= QUERY_LIMIT:
            raise ValueError(f"limit must be between 1 and {QUERY_LIMIT}")
        binding = _canonical_digest({"stream": "rowid", "turn_id": turn_id})
        sequence = 0
        if cursor:
            raw_sequence, _ = _cursor_decode(cursor, binding)
            if not raw_sequence.isdigit():
                raise ValueError("invalid telemetry ingestion cursor")
            sequence = int(raw_sequence)
        with closing(self._connect()) as connection:
            if tail and not cursor:
                row = connection.execute(
                    "SELECT rowid,id FROM memory_runtime_events WHERE turn_id=? "
                    "ORDER BY rowid DESC LIMIT 1", (turn_id,),
                ).fetchone()
                sequence = int(row["rowid"]) if row is not None else 0
                identifier = str(row["id"]) if row is not None else ""
                return {"items": [], "page": {
                    "limit": limit, "has_more": False,
                    "poll_cursor": _cursor_encode(str(sequence), identifier, binding),
                    "cursor_basis": "append_only_rowid",
                }}
            rows = connection.execute(
                "SELECT rowid AS ingestion_sequence,* FROM memory_runtime_events "
                "WHERE turn_id=? AND rowid>? ORDER BY rowid ASC LIMIT ?",
                (turn_id, sequence, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = []
        for row in rows:
            item = self._project(row)
            item.pop("ingestion_sequence", None)
            items.append(item)
        if rows:
            sequence = int(rows[-1]["ingestion_sequence"])
            identifier = str(rows[-1]["id"])
        else:
            identifier = ""
        return {"items": items, "page": {
            "limit": limit, "has_more": has_more,
            "poll_cursor": _cursor_encode(str(sequence), identifier, binding),
            "cursor_basis": "append_only_rowid",
        }}

    def for_trace(self, trace_id: str, **kwargs) -> dict:
        return self.events(trace_id=trace_id, **kwargs)

    def for_turn(self, turn_id: str, **kwargs) -> dict:
        return self.events(turn_id=turn_id, **kwargs)

    def for_claim(self, claim_id: str, **kwargs) -> dict:
        return self.events(claim_id=claim_id, **kwargs)

    def for_relation(self, relation_id: str, **kwargs) -> dict:
        return self.events(relation_id=relation_id, **kwargs)

    def for_llm_call(self, llm_call_id: str, **kwargs) -> dict:
        return self.events(llm_call_id=llm_call_id, **kwargs)

    def for_action(self, action_id: str, **kwargs) -> dict:
        return self.events(action_id=action_id, **kwargs)
