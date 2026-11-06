from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .learning_contract import CLAIM_KINDS, DECISIONS, EVIDENCE_CONTRACT, EVIDENCE_SOURCES, PROVENANCE_CONTRACT, SCOPE_PATTERN, parse_learning_json
from .memory import redact_sensitive
from .memory_lifecycle import lifecycle_operation


POLICY_VERSION = "memory-v2-shadow-v1.6"
PRODUCTION_POLICY_VERSION = "memory-v2-production-v1"
PROMPT_VERSION = "shadow-learning-decision-v10-semantic-formulations"
CONTRACT_VERSION = "shadow-mutation-contract-v3-provenance"
NORMALIZER_VERSION = "shadow-normalizer-v3-instruction-confirmation"
_SHADOW_NAMESPACE = uuid.UUID("db39cb55-bd5a-464a-aee2-ad4b99b2cbd9")
_DECISIONS = DECISIONS | {'shadow_error'}
_POSITIVE = _DECISIONS - {"no_persist", "undetermined", "shadow_error"}
_KINDS = CLAIM_KINDS
_LIFECYCLES = {"candidate", "active", "retired", "invalid"}
_RELATIONS = {"supersedes", "contradicts", "refines"}
_EVIDENCE_SOURCES = EVIDENCE_SOURCES
_SECRET_KEY = re.compile(r"token|authorization|password|secret|api[_-]?key", re.I)
_SCOPE = re.compile(SCOPE_PATTERN)


def _source_excerpt(text: str, source: str) -> str | None:
    """Locate unchanged source wording, tolerating whitespace formatting only."""
    words = str(text).split()
    if not words:
        return None
    match = re.search(r"\s+".join(re.escape(word) for word in words), source)
    return match.group(0) if match else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _input_provenance(snapshot):
    return {key: snapshot[key] for key in ("conversation_source", "scheduled_execution") if snapshot.get(key)}


def _schema_field_errors(error):
    """Return structural locations, never echo the rejected instance/full schema."""
    if error.context:
        return [item for child in error.context for item in _schema_field_errors(child)]
    item = {'path': '/' + '/'.join(str(part).replace('~', '~0').replace('/', '~1')
                                 for part in error.absolute_path), 'keyword': error.validator}
    if error.validator == 'required':
        item['message'] = error.message
    elif error.validator in {'type', 'pattern', 'const'}:
        item['expected'] = error.validator_value
    return [item]


def _stable_id(kind: str, value: str) -> str:
    return str(uuid.uuid5(_SHADOW_NAMESPACE, f"{kind}:{value}"))


def _pointer_failure_structure(value, pointer: str) -> dict:
    """Describe the exact structural point where an RFC6901 pointer stops."""
    tokens = pointer.split('/')[1:] if pointer.startswith('/') else []
    current = value
    resolved = ''
    for index, encoded_token in enumerate(tokens):
        token = encoded_token.replace('~1', '/').replace('~0', '~')
        if isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            children = list(current) if isinstance(current, dict) else list(range(len(current))) if isinstance(current, list) else []
            return {
                'resolved_parent_pointer': resolved,
                'unresolved_tokens': tokens[index:],
                'parent_type': type(current).__name__,
                'available_children': [{
                    'key': child,
                    'pointer': resolved + '/' + str(child).replace('~', '~0').replace('/', '~1'),
                } for child in children],
            }
        resolved += '/' + encoded_token
    return {'resolved_pointer': resolved, 'value': _audit_value(current)}


def _productive_lifecycle_origin(arguments: dict) -> dict:
    pipeline = arguments["self"]
    snapshot = arguments["snapshot"]
    turn_id = str(snapshot["turn_id"])
    decision_id = _stable_id(
        "productive-decision",
        ":".join((turn_id, pipeline.policy_version, pipeline.prompt_version, pipeline.model_version)),
    )
    return {
        "trace_id": turn_id,
        "turn_id": turn_id,
        "conversation_id": snapshot.get("conversation_id"),
        "learning_decision_id": decision_id,
        "operation_id": f"productive-learning:{decision_id}",
        "reason_code": str(arguments["proposal"].get("reason_code") or "productive_learning"),
    }


def _tokens(text: str) -> set[str]:
    return {item for item in re.findall(r"[^\W_]{3,}", str(text).casefold(), re.UNICODE)}


def _contains_value(value, expected: str) -> bool:
    if isinstance(value, dict):
        return any(_contains_value(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_value(item, expected) for item in value)
    return str(value) == expected


def _dict_with_reference(value, expected: str) -> list[dict]:
    found = []
    if isinstance(value, dict):
        if any(str(item) == expected for item in value.values() if not isinstance(item, (dict, list))):
            found.append(value)
        for item in value.values():
            found.extend(_dict_with_reference(item, expected))
    elif isinstance(value, list):
        for item in value:
            found.extend(_dict_with_reference(item, expected))
    return found


def _safe_value(value, *, key: str = ""):
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _safe_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_value(item, key=key) for item in value[:50]]
    if isinstance(value, str):
        return redact_sensitive(value)[:2000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_sensitive(str(value))[:2000]


def _audit_value(value, *, key=""):
    """Redact diagnostics without silently truncating proposals or evidence."""
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _audit_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_audit_value(v) for v in value]
    return redact_sensitive(value) if isinstance(value, str) else value


def _is_context_window_error(exc: Exception) -> bool:
    """Recognize the model server's factual context-window rejection."""
    seen = set()
    current = exc
    messages = []
    codes = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        messages.append(str(current).casefold())
        code = str(getattr(current, "provider_code", "") or "").casefold()
        if code:
            codes.add(code)
        current = current.__cause__
    technical = " | ".join(messages)
    return bool(codes & {
        "exceed_context_size_error", "context_length_exceeded", "working_context_limit",
    }) or any(marker in technical for marker in (
        "request exceeds the context window",
        "exceeds the available context size",
        "context_length_exceeded",
    ))


class ShadowLearningCancelled(RuntimeError):
    pass


class LearningProgressError(RuntimeError):
    """A bounded learning attempt exhausted its navigation budget, not its evidence."""
    def __init__(self, reason, **evidence):
        self.response_evidence = {'reason': reason, **evidence}
        super().__init__(reason)


class _Cancellation:
    def __init__(self, event: threading.Event):
        self.event = event

    def checkpoint(self) -> None:
        if self.event.is_set():
            raise ShadowLearningCancelled("interactive_turn_priority")

    begin_commit = checkpoint


class ShadowLearningPipeline:
    """Evaluate completed turns without mutating claims, evidence, or relations."""

    def __init__(self, database, llm=None, diagnostics=None, *, policy_version: str = POLICY_VERSION):
        self.database = database
        self.llm = llm
        self.diagnostics = diagnostics
        self.policy_version = str(policy_version)
        self.prompt_version = PROMPT_VERSION
        self.model_version = str(getattr(llm, "model", "") or "")
        self._state_lock = threading.RLock()
        self._evaluation_lock = threading.Lock()
        self._active_cancel: threading.Event | None = None
        self._priority_generation = 0

    def prioritize_interactive_turn(self) -> None:
        """Ask an in-flight streamed shadow evaluation to yield to user work."""
        with self._state_lock:
            self._priority_generation += 1
            if self._active_cancel is not None:
                self._active_cancel.set()

    def priority_token(self) -> int:
        """Capture the interactive generation when deferred work is queued."""
        with self._state_lock:
            return self._priority_generation

    def evaluate_turn(self, turn_id: str, expected_priority_generation: int | None = None) -> dict:
        started = time.perf_counter()
        attempted_llm = False
        event = threading.Event()
        self._evaluation_lock.acquire()
        with self._state_lock:
            self._active_cancel = event
        try:
            snapshot_started = time.perf_counter()
            snapshot = self._snapshot(str(turn_id))
            snapshot_ms = (time.perf_counter() - snapshot_started) * 1000
            existing = self._existing(str(turn_id))
            if existing:
                return existing
            with self._state_lock:
                stale = (expected_priority_generation is not None
                         and expected_priority_generation != self._priority_generation)
            if stale:
                return self._persist(
                    snapshot, self._undetermined("interactive_priority", clarification=False),
                    "deterministic", {"llm_calls": 0, "visible_latency_added_ms": 0}, started,
                )

            gate_started = time.perf_counter()
            deterministic = self._deterministic_gate(snapshot)
            gate_ms = (time.perf_counter() - gate_started) * 1000
            llm_ms = 0.0
            matching_ms = 0.0
            normalization_ms = 0.0
            if deterministic is not None:
                proposal = deterministic
                method = "deterministic"
                llm_calls = 0
            elif self.llm is None or not hasattr(self.llm, "analyze_shadow_learning"):
                proposal = self._undetermined("model_unavailable", clarification=False)
                method, llm_calls = "deterministic", 0
            else:
                event.clear()
                candidates_started = time.perf_counter()
                candidates = self._claim_candidates(self._candidate_context(snapshot))
                matching_ms = (time.perf_counter() - candidates_started) * 1000
                context = self._model_context(snapshot, candidates)
                llm_started = time.perf_counter()
                attempted_llm = True
                cancellation = _Cancellation(event)
                cancellable = getattr(self.llm, "cancellable", None)
                if cancellable:
                    with cancellable(cancellation):
                        raw = self.llm.analyze_shadow_learning(context)
                else:
                    cancellation.checkpoint()
                    raw = self.llm.analyze_shadow_learning(context)
                    cancellation.checkpoint()
                llm_ms = (time.perf_counter() - llm_started) * 1000
                normalization_started = time.perf_counter()
                proposal = self._validate_proposal(raw, snapshot, candidates)
                normalization_ms = (time.perf_counter() - normalization_started) * 1000
                method, llm_calls = "llm", 1

            metrics = {
                "snapshot_ms": round(snapshot_ms, 3), "capture_gate_ms": round(gate_ms, 3),
                "claim_matching_ms": round(matching_ms, 3), "llm_ms": round(llm_ms, 3),
                "normalization_ms": round(normalization_ms, 3),
                "llm_calls": llm_calls, "visible_latency_added_ms": 0,
            }
            return self._persist(snapshot, proposal, method, metrics, started)
        except ShadowLearningCancelled:
            snapshot = locals().get("snapshot")
            if snapshot is None:
                return {"turn_id": str(turn_id), "decision_type": "undetermined", "reason_code": "interactive_priority"}
            return self._persist(
                snapshot, self._undetermined("interactive_priority", clarification=False),
                "hybrid", {"llm_calls": 1, "visible_latency_added_ms": 0}, started,
            )
        except Exception as exc:
            snapshot = locals().get("snapshot")
            if snapshot is None:
                self._diagnostic(exc, str(turn_id), "snapshot")
                return {"turn_id": str(turn_id), "decision_type": "shadow_error", "reason_code": type(exc).__name__}
            self._diagnostic(exc, str(turn_id), "evaluation")
            return self._persist(
                snapshot,
                {
                    "decision_type": "shadow_error", "memory_worthy": None,
                    "reason_code": "evaluation_error", "uncertainty": None,
                    "clarification_recommended": False, "claim": None,
                    "evidence": [], "matched_claim_ids": [], "relations": [],
                    "details": {"stage": "evaluation", "error_class": type(exc).__name__,
                                "message": str(exc), "raw_response": _audit_value(getattr(exc, 'raw_response', None))},
                },
                "llm" if attempted_llm else "deterministic",
                {"llm_calls": int(attempted_llm), "visible_latency_added_ms": 0}, started,
            )
        finally:
            with self._state_lock:
                if self._active_cancel is event:
                    self._active_cancel = None
            self._evaluation_lock.release()

    def _snapshot(self, turn_id: str) -> dict:
        with self.database.connect() as connection:
            turn = connection.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()
            if turn is None:
                raise KeyError("Turn wurde nicht gefunden")
            user = connection.execute("SELECT * FROM messages WHERE id=?", (turn["user_message_id"],)).fetchone()
            assistant = connection.execute("SELECT * FROM messages WHERE id=?", (turn["assistant_message_id"],)).fetchone()
            tools = connection.execute(
                "SELECT * FROM conversation_tool_events WHERE message_id=? ORDER BY ordinal",
                (turn["assistant_message_id"],),
            ).fetchall()
            retrievals = connection.execute(
                "SELECT memory_id,method,score FROM turn_memory_retrievals WHERE turn_id=? ORDER BY position",
                (turn_id,),
            ).fetchall()
            legacy = connection.execute(
                "SELECT id,category,status FROM memory_items WHERE source_message_id=? ORDER BY id",
                (turn["user_message_id"],),
            ).fetchall()
            failure_rows = connection.execute(
                "SELECT event_type,details_json FROM audit_events WHERE conversation_id=? "
                "AND event_type IN ('turn_failure','turn_retry') AND created_at<=? ORDER BY id",
                (turn["conversation_id"],turn["created_at"]),
            ).fetchall()
            episodes = connection.execute(
                "SELECT details_json FROM audit_events WHERE event_type='learning_episode' "
                "AND conversation_id=? AND json_extract(details_json,'$.turn_id')=? ORDER BY id",
                (turn['conversation_id'], turn_id),
            ).fetchall()
            dialog = connection.execute(
                "SELECT role,content,metadata_json FROM messages WHERE conversation_id=? AND ordinal<? "
                "ORDER BY ordinal",
                (turn["conversation_id"], user["ordinal"]),
            ).fetchall() if user else []
            prior = connection.execute(
                "SELECT MAX(created_at) FROM turns WHERE conversation_id=? AND created_at<?",
                (turn["conversation_id"],turn["created_at"]),
            ).fetchone()[0]
        reports, retries = {}, {}
        for row in failure_rows:
            item=json.loads(row["details_json"])
            (reports if row["event_type"] == "turn_failure" else retries)[item["turn_id"]]=item
        linked, visited = [], set()
        current = turn_id
        while current in retries and current not in visited:
            visited.add(current)
            link=retries[current]
            source=reports.get(link["source_turn_id"])
            if source:
                linked.append({"failure":source,"correction":link["correction"],"explicit_retry":True})
            current=link["source_turn_id"]
        if not linked:
            linked=[{"failure":report,"correction":None,"explicit_retry":False}
                    for report in reports.values() if not prior or report["created_at"]>prior]
        assistant_meta = json.loads(assistant["metadata_json"] or "{}") if assistant else {}
        user_meta = json.loads(user["metadata_json"] or "{}") if user else {}
        dialog_context=[];skip_event_answer=False
        for row in dialog:
            metadata=json.loads(row['metadata_json'] or '{}')
            source=metadata.get('conversation_source')
            if isinstance(source,dict) and isinstance(source.get('mcp_wakeup'),dict):
                skip_event_answer=True
                continue
            if skip_event_answer and row['role']=='assistant':
                skip_event_answer=False
                continue
            skip_event_answer=False
            dialog_context.append({"role":row["role"],
                                   "content":redact_sensitive(str(row["content"])),
                                   **_input_provenance(metadata),"context_only":True})
        return {
            "dialog_context": dialog_context,
            "failure_episodes": linked,
            "episode_source_turn_ids": list(dict.fromkeys(source for episode in episodes
                for source in json.loads(episode[0])['source_turn_ids'])),
            "working_memory": assistant_meta.get("working_memory"),
            "turn_id": turn_id, "conversation_id": str(turn["conversation_id"]),
            "user_message_id": str(turn["user_message_id"]),
            "assistant_message_id": str(turn["assistant_message_id"]) if turn["assistant_message_id"] else None,
            "user_content": redact_sensitive(str(user["content"] if user else "")),
            "conversation_source": user_meta.get("conversation_source"),
            "scheduled_execution": user_meta.get("scheduled_execution"),
            "assistant_content": redact_sensitive(str(assistant["content"] if assistant else "")),
            "route": str(assistant_meta.get("route") or "unknown"),
            "created_at": str(turn["created_at"]),
            "tools": [dict(item) for item in tools],
            "turn_state_details": assistant_meta.get("turn_state_details") or {},
            "retrievals": [dict(item) for item in retrievals],
            "legacy_writes": [dict(item) for item in legacy],
        }

    def _existing(self, turn_id: str) -> dict | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT * FROM memory_shadow_learning_decisions
                   WHERE turn_id=? AND policy_version=? AND prompt_version=? AND model_version=?""",
                (turn_id, self.policy_version, self.prompt_version, self.model_version),
            ).fetchone()
        return dict(row) if row else None

    def _deterministic_gate(self, snapshot: dict) -> dict | None:
        if not snapshot["user_content"].strip():
            return self._no_persist("no_user_observation")
        source = snapshot.get("conversation_source")
        if isinstance(source, dict) and isinstance(source.get("mcp_wakeup"), dict):
            return self._no_persist("integration_event")
        return None

    @staticmethod
    def _no_persist(reason: str) -> dict:
        return {
            "decision_type": "no_persist", "memory_worthy": False, "reason_code": reason,
            "uncertainty": 0.0, "clarification_recommended": False, "claim": None,
            "evidence": [], "matched_claim_ids": [], "relations": [],
            "details": {"contract_version": CONTRACT_VERSION, "normalizer_version": NORMALIZER_VERSION},
        }

    @staticmethod
    def _undetermined(reason: str, *, clarification: bool) -> dict:
        return {
            "decision_type": "undetermined", "memory_worthy": None, "reason_code": reason,
            "uncertainty": 1.0, "clarification_recommended": clarification, "claim": None,
            "evidence": [], "matched_claim_ids": [], "relations": [],
            "details": {"contract_version": CONTRACT_VERSION, "normalizer_version": NORMALIZER_VERSION},
        }

    @staticmethod
    def _candidate_context(snapshot):
        # Candidate discovery only; history never adds evidence authority.
        return "\n".join([item["content"] for item in snapshot.get("dialog_context", [])]
                         + [snapshot["user_content"]])

    def _claim_candidates(self, text: str) -> list[dict]:
        query_tokens = _tokens(text)
        if not query_tokens:
            return []
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT id,claim_kind,scope,canonical_key,slot_key,display_text,lifecycle,payload_json,
                          valid_from,valid_until,verification_policy
                   FROM memory_claims
                   WHERE scope NOT IN ('semantic_links','semantic_actions','semantic_similarity_relations','semantic_language_relations')
                   ORDER BY updated_at DESC,id"""
            ).fetchall()
        candidates = []
        for row in rows:
            tokens = _tokens(" ".join(str(row[key] or "") for key in (
                "display_text", "canonical_key", "slot_key", "payload_json",
            )))
            score = len(tokens & query_tokens) / max(1, len(tokens | query_tokens))
            if score:
                item = dict(row)
                item["similarity"] = round(score, 4)
                candidates.append(item)
        return sorted(candidates, key=lambda item: item["similarity"], reverse=True)[:5]

    def _execution_trace(self, snapshot):
        """Chronological DB receipts, without inferring a correction or its cause."""
        work = snapshot.get('working_memory') or {}
        turn_id = work.get('work_turn_id')
        if not turn_id:
            return []
        with self.database.connect(lifecycle_audit=False) as connection:
            rows = connection.execute(
                'SELECT t.*,rq.structured_value_json AS request_json,rs.structured_value_json AS result_json '
                'FROM memory_work_calls t '
                'JOIN memory_work_objects oq ON oq.id=t.request_id '
                'JOIN memory_observations rq ON rq.id=oq.observation_id '
                'LEFT JOIN memory_work_objects os ON os.id=t.result_id '
                'LEFT JOIN memory_observations rs ON rs.id=os.observation_id '
                'JOIN memory_work_turns wt ON wt.id=t.turn_id '
                'WHERE t.turn_id=? AND wt.conversation_id=? ORDER BY t.created_at,t.id',
                (turn_id, snapshot['conversation_id']),
            ).fetchall()
        trace, previous = [], None
        include_payload = not bool(snapshot.get('tools'))
        for row in rows:
            result = json.loads(row['result_json']) if row['result_json'] else None
            receipt = {'call_reference': row['id'], 'previous_call_reference': previous,
                'capability': row['capability'], 'operation': row['operation'],
                'dispatch_status': row['status'], 'request_reference': row['request_id'],
                'result_reference': row['result_id'], 'result_content_in_context': False,
                'task_success_assessed': False}
            if include_payload:
                receipt.update({
                    'input': _audit_value(json.loads(row['request_json'])),
                    'result_metadata': _audit_value({key: value for key, value in result.items()
                        if key not in {'content', 'resources', 'response'}})
                        if isinstance(result, dict) else None,
                })
            else:
                receipt.update({
                    'payload_in_context': False,
                    'payload_source': 'tool_events',
                })
            trace.append(receipt)
            previous = row['id']
        return trace

    def _revision_feedback(self, turn_id):
        """Load the last rejected attempt as data, never as supporting evidence."""
        with self.database.connect(lifecycle_audit=False) as connection:
            row = connection.execute(
                "SELECT id,structured_value_json FROM memory_observations "
                "WHERE turn_id=? AND external_ref LIKE 'learning_attempt:%' "
                "AND json_extract(metadata_json,'$.kind')='learning_attempt' "
                "ORDER BY created_at DESC,rowid DESC LIMIT 1", (turn_id,),
            ).fetchone()
        if row is None:
            return None
        attempt = json.loads(row['structured_value_json'])
        rejected = attempt.get('proposal') or {}
        original = rejected.get('details', {}).get('raw_proposal')
        field_errors = []
        if isinstance(original, dict):
            for index, evidence in enumerate(original.get('evidence') or []):
                if not isinstance(evidence, dict):
                    continue
                required = (['observed_value'] if evidence.get('result_pointer') is not None else ['property', 'external_reference']) if evidence.get('source_type') == 'provider_result' else []
                missing = [key for key in required if key not in evidence or (key != 'observed_value' and not evidence[key])]
                if missing:
                    field_errors.append({'path': '/evidence/' + str(index), 'missing_fields': missing})
            if attempt.get('reason_code') == 'result_evidence_pointer_not_found':
                provider_evidence = [
                    (index, evidence) for index, evidence in enumerate(original.get('evidence') or [])
                    if isinstance(evidence, dict)
                    and evidence.get('source_type') == 'provider_result'
                    and isinstance(evidence.get('result_pointer'), str)
                    and evidence.get('source_id')
                ]
                source_ids = [str(evidence['source_id']) for _, evidence in provider_evidence]
                tool_results = {}
                if source_ids:
                    placeholders = ','.join('?' for _ in source_ids)
                    with self.database.connect(lifecycle_audit=False) as connection:
                        tool_results = {str(item['id']): json.loads(item['result_json'] or '{}')
                            for item in connection.execute(
                                f'SELECT id,result_json FROM conversation_tool_events WHERE id IN ({placeholders})',
                                source_ids,
                            )}
                from .working_memory import WorkingMemoryStore
                for index, evidence in provider_evidence:
                    result = tool_results.get(str(evidence['source_id']))
                    if result is None:
                        continue
                    try:
                        WorkingMemoryStore.pointer(result, evidence['result_pointer'])
                    except (KeyError, IndexError, TypeError, ValueError):
                        field_errors.append({
                            'path': f'/evidence/{index}/result_pointer',
                            'code': 'pointer_not_found_in_original_tool_result',
                            'requested_pointer': evidence['result_pointer'],
                            'source_id': str(evidence['source_id']),
                            'structure_at_failure': _pointer_failure_structure(
                                result, evidence['result_pointer'],
                            ),
                        })
        return {'mode': 'revision', 'attempt_observation_id': row['id'],
                'context_only': True, 'reason_code': attempt.get('reason_code'),
                'requested_operation': 'revise_rejected_proposal',
                'field_errors': field_errors,
                'previous_proposal': original, 'previous_proposal_status': 'rejected_not_evidence',
                'validation_result': {**rejected, 'details': {key: value for key, value in
                    (rejected.get('details') or {}).items() if key != 'raw_proposal'}}, 'source_context': 'current_turn',
                'persistence_requires_validation': True}

    def _model_context(self, snapshot: dict, candidates: list[dict], *, include_episode=True, include_rejected_proposal=True) -> dict:
        # Exact provenance links: completed direct writes are observations, not proposals.
        with self.database.connect() as connection:
            direct_revisions = [json.loads(row[0]) for row in connection.execute(
                "SELECT metadata_json FROM memory_learning_decisions WHERE method='direct_revision' "
                "AND json_extract(metadata_json,'$.source_turn_reference')=? ORDER BY created_at",
                (snapshot['turn_id'],))]
        tools = []
        for item in snapshot["tools"]:
            raw_input = json.loads(item["input_json"] or "{}")
            raw_result = json.loads(item["result_json"] or "{}")
            result_object = raw_result if isinstance(raw_result, dict) else {}
            response = result_object.get("response") or {}
            if not isinstance(response, dict):
                response = {}
            body = response.get("body")
            outcome = {"http_status": response.get("status"),
                       "result_count": (len(body) if isinstance(body, list)
                                        else len(raw_result) if isinstance(raw_result, list)
                                        else result_object.get("total_matches")),
                       "body": {key:body[key] for key in ("result","message","error") if key in body}
                               if isinstance(body, dict) else None,
                       "success": response.get("success"), "error": response.get("error")}
            request = result_object.get("request") or {}
            if not isinstance(request, dict):
                request = {}
            if isinstance(raw_result, dict):
                result_metadata = {key: value for key, value in raw_result.items()
                                   if key not in {'content', 'resources', 'response'}}
                observed_fields = [{"source_type": "provider_result", "source_id": item["id"],
                    "result_pointer": '/' + key.replace('~', '~0').replace('/', '~1'),
                    "observed_value": value}
                    for key, value in raw_result.items()
                    if key not in {'content', 'resources', 'response'} and not isinstance(value, (dict, list))
                    and not _SECRET_KEY.search(key) and _audit_value(value) == value]
            else:
                result_metadata = {
                    "root_type": type(raw_result).__name__,
                    "item_count": len(raw_result) if isinstance(raw_result, list) else None,
                }
                observed_fields = []
            tools.append({
                "evidence_reference": {"source_type": "provider_result", "source_id": item["id"]},
                "observed_outcome": _audit_value(outcome),
                "request": _audit_value({key: request.get(key) for key in ("path","method","command")}),
                "id": item["id"], "tool": item["tool"], "status": item["status"],
                "input": _audit_value(raw_input),
                "result_evidence": {"source_type": "provider_result", "source_id": item["id"],
                    "root": "original_tool_result", "selection": "result_pointer + observed_value",
                    "observed_fields": observed_fields},
                "result": _audit_value(result_metadata),
                "material": {'reference': result_object.get('reference'),
                             'content_in_learning_context': False,
                             'content_type': type(result_object.get('content')).__name__,
                             'result_type': type(raw_result).__name__},
            })
        context = {
            "policy_version": self.policy_version, "prompt_version": self.prompt_version,
            "contract_version": CONTRACT_VERSION, "normalizer_version": NORMALIZER_VERSION,
            "failure_episodes": _audit_value(snapshot.get("failure_episodes", [])),
            "working_memory_references": _audit_value(snapshot.get("working_memory")),
            **({"applied_memory_revisions": _audit_value(direct_revisions)} if direct_revisions else {}),
            "execution_trace": self._execution_trace(snapshot),
            "failure_learning_policy": {
                "runtime_reports_are_observations_not_causal_proof": True,
                "unknown_causes_must_not_be_stored_as_facts": True,
                "assistant_claims_are_not_verified_outcomes": True,
                "model_authored_checkpoints_are_not_verified_facts": True,
            },
            "turn_id": snapshot["turn_id"], "route": snapshot["route"],
            "user_message": {"id": snapshot["user_message_id"], "content": snapshot["user_content"],
                **_audit_value(_input_provenance(snapshot)),
                **({"source_role": "system", "input_kind": "scheduled", "fresh_human_message": False}
                   if snapshot.get("scheduled_execution") else {}),
                "evidence_reference": {"source_type": "user_message", "source_id": snapshot["user_message_id"]}},
            "evidence_contract": EVIDENCE_CONTRACT, "provenance_contract": PROVENANCE_CONTRACT,
            "dialog_context": snapshot.get("dialog_context", []),
            "assistant_context": {"id": snapshot["assistant_message_id"], "content": snapshot["assistant_content"],
                                  "source_role": "assistant", "context_only": True},
            "tool_events": tools, "retrieved_memory_ids": [x["memory_id"] for x in snapshot["retrievals"]],
            "claim_candidates": [{
                "id": item["id"], "kind": item["claim_kind"], "scope": item["scope"],
                "canonical_key": item["canonical_key"], "slot_key": item["slot_key"],
                "display_text": item["display_text"], "lifecycle": item["lifecycle"],
                "payload": _audit_value(json.loads(item["payload_json"] or "{}")),
                "valid_from": item["valid_from"], "valid_until": item["valid_until"],
                "verification_policy": item["verification_policy"], "similarity": item["similarity"],
            } for item in candidates],
        }

        if getattr(self, 'conversation_semantics', None) is not None:
            context['semantic_learning'] = self.conversation_semantics.context(snapshot)
        feedback = self._revision_feedback(snapshot['turn_id'])
        if feedback:
            original = feedback.get('previous_proposal') or {}
            allowed_claim_ids = [item['id'] for item in candidates]
            requested_claim_ids = original.get('matched_claim_ids') or []
            invalid_claim_ids = [item for item in requested_claim_ids
                                 if item not in allowed_claim_ids]
            feedback['claim_references'] = {
                'scope': 'current_turn_only',
                'allowed_claim_ids': allowed_claim_ids,
            }
            if invalid_claim_ids:
                feedback['field_errors'].append({
                    'path': '/matched_claim_ids',
                    'code': 'claim_not_published_for_current_turn',
                    'invalid_values': invalid_claim_ids,
                    'allowed_values': allowed_claim_ids,
                })
            tool_metadata = {tool['id']: tool['result'] for tool in tools}
            feedback['provider_bindings'] = []
            for evidence in original.get('evidence') or []:
                if not isinstance(evidence, dict) or evidence.get('source_type') != 'provider_result':
                    continue
                metadata = tool_metadata.get(evidence.get('source_id'), {})
                feedback['provider_bindings'].append({
                    'source_id': evidence.get('source_id'),
                    'requested_property': evidence.get('property'),
                    'requested_external_reference': evidence.get('external_reference'),
                    'direct_result_evidence': {'source_type': 'provider_result', 'source_id': evidence.get('source_id'),
                        'root': 'original_tool_result', 'fields': ['result_pointer', 'observed_value']},
                    'published_string_values': {key: value for key, value in metadata.items()
                                                if isinstance(value, str)},
                    'published_properties': list(metadata),
                })
            claim = original.get('claim')
            claim = claim if isinstance(claim, dict) else {}
            payload = claim.get('payload')
            payload = payload if isinstance(payload, dict) else {}
            if payload.get('epistemic_kind') == 'user_instruction':
                feedback['instruction_provenance'] = {
                    'required_authority': 'user_direct',
                    'requires_verbatim_current_user_text': True,
                    'display_text_occurs_verbatim': _source_excerpt(claim.get('display_text') or '', snapshot['user_content']) is not None}
                provenance = feedback['instruction_provenance']
                if not provenance['display_text_occurs_verbatim']:
                    feedback['field_errors'].append({
                        'path': '/claim/display_text', 'code': 'not_verbatim_current_user_text',
                        'source_reference': context['user_message']['evidence_reference']})
                if original.get('authority') != 'user_direct':
                    feedback['field_errors'].append({'path': '/authority',
                        'code': 'user_instruction_requires_user_direct'})
                if not provenance['display_text_occurs_verbatim'] or original.get('authority') != 'user_direct':
                    feedback['field_errors'].append({'path': '/claim/payload/epistemic_kind',
                        'code': 'user_instruction_provenance_not_established',
                        'related_paths': ['/authority', '/claim/display_text', '/evidence']})
            feedback['previous_proposal_in_context'] = include_rejected_proposal
            if not include_rejected_proposal:
                feedback.pop('previous_proposal', None)
            context['learning_revision'] = _audit_value(feedback)

        if include_episode and snapshot.get('episode_source_turn_ids'):
            context['learning_episode'] = {'context_only': True, 'turns': []}
            for turn_id in snapshot['episode_source_turn_ids']:
                source = self._model_context(self._snapshot(turn_id), [], include_episode=False)
                context['learning_episode']['turns'].append({
                    'turn_id': turn_id, 'user_context': source['user_message']['content'],
                    'assistant_context': source['assistant_context'],
                    'tool_events': [{key: value for key, value in tool.items() if key not in {'evidence_reference', 'result_evidence'}}
                                    for tool in source['tool_events']],
                    'working_memory_references': source['working_memory_references'],
                    'execution_trace': source['execution_trace'],
                })
        return context

    def _validate_proposal(self, raw: dict, snapshot: dict, candidates: list[dict]) -> dict:
        general = self._validate_general_proposal(raw, snapshot, candidates)
        semantics = getattr(self, 'conversation_semantics', None)
        if semantics is None or not isinstance(raw, dict):
            return general
        result = deepcopy(general)
        try:
            available = semantics.context(snapshot)['available']
            if available and ('semantic_formulation' not in raw
                    or not isinstance(raw.get('semantic_learning_reason'), str)
                    or not raw['semantic_learning_reason'].strip()):
                raise ValueError('semantic_learning_decision_missing')
            semantic = semantics.validate(snapshot, raw.get('semantic_formulation'))
            if semantic is not None:
                result['semantic_formulation'] = semantic
            if raw.get('semantic_learning_reason'):
                result['semantic_learning_reason'] = raw['semantic_learning_reason']
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            result = self._undetermined(str(getattr(exc, 'message', exc))[:1000], clarification=False)
            result['general_proposal'] = general
            result['semantic_learning_error'] = result['reason_code']
            result['details']['raw_proposal'] = _audit_value(raw)
        return result

    def _validate_general_proposal(self, raw: dict, snapshot: dict, candidates: list[dict]) -> dict:
        episodes = snapshot.get("failure_episodes") or []
        result = self._validate_proposal_contract(raw, snapshot, candidates)
        if result["decision_type"] == "undetermined":
            result["details"]["raw_proposal"] = _audit_value(raw)
        if not episodes or result["decision_type"] in {"no_persist", "undetermined"}:
            return result
        # Context is not new evidence. A report cannot elevate a hypothesis,
        # nor append it to an existing active fact via the exact-match path.
        claim = result.get("claim")
        corrections = {item.get("correction") for item in episodes if item.get("explicit_retry")}
        if any(not item.get("explicit_retry") for item in episodes):
            corrections.add(snapshot["user_content"])
        if (claim and raw.get("authority") == "user_direct"
                and claim.get("display_text") in corrections
                and result["decision_type"] == "create_active"):
            instruction = claim["display_text"]
            claim["display_text"] = "Benutzer-Korrekturhinweis (keine bestätigte Fehlerursache): " + instruction
            claim["payload"]["epistemic_kind"] = "user_instruction"
            claim["payload"]["instruction"] = instruction
            return result
        if claim and result["decision_type"] in {"create_active", "create_candidate", "create_competing_claim"}:
            result["decision_type"] = "create_candidate"
            claim["lifecycle"] = "candidate"
            result["matched_claim_ids"] = []
            result["relations"] = []
            result['details'].pop('old_claim_transition', None)
            result["details"]["failure_learning_guard"] = "unverified_lesson_candidate_only"
            return result
        result = self._undetermined("failure_lesson_requires_independent_evidence", clarification=False)
        result["details"]["raw_proposal"] = _audit_value(raw)
        return result

    def _validate_proposal_contract(self, raw: dict, snapshot: dict, candidates: list[dict]) -> dict:
        """Normalize one semantic decision, then enforce its atomic contract."""
        if not isinstance(raw, dict):
            return self._undetermined("invalid_model_output", clarification=False)
        decision = str(raw.get("decision_type") or "")
        if decision not in _DECISIONS or decision == "shadow_error":
            return self._undetermined("invalid_decision_type", clarification=False)

        candidate_by_id = {str(item["id"]): item for item in candidates}
        matched_ids = raw.get("matched_claim_ids") or []
        if not isinstance(matched_ids, list):
            return self._undetermined("invalid_claim_reference", clarification=False)
        matched_ids = [str(item) for item in matched_ids]
        if any(item not in candidate_by_id for item in matched_ids):
            return self._undetermined("invalid_claim_reference", clarification=False)

        evidence = self._validated_evidence(raw.get("evidence") or [], snapshot)
        if isinstance(evidence, str):
            return self._undetermined(evidence, clarification=False)

        uncertainty = raw.get("uncertainty")
        try:
            uncertainty = float(uncertainty) if uncertainty is not None else None
        except (TypeError, ValueError):
            return self._undetermined("invalid_uncertainty", clarification=False)
        if uncertainty is not None and not 0 <= uncertainty <= 1:
            return self._undetermined("invalid_uncertainty", clarification=False)

        base = {
            "decision_type": decision,
            "memory_worthy": bool(raw.get("memory_worthy")) if raw.get("memory_worthy") is not None else None,
            "reason_code": str(raw.get("reason_code") or "model_classification")[:120],
            "uncertainty": uncertainty,
            "clarification_recommended": bool(raw.get("clarification_recommended", False)),
            "claim": None, "evidence": [], "matched_claim_ids": matched_ids, "relations": [],
            "details": {
                "authority": raw.get("authority"), "temporal_class": raw.get("temporal_class"),
                "change_type": raw.get("change_type"), "contract_version": CONTRACT_VERSION,
                "normalizer_version": NORMALIZER_VERSION,
            },
        }
        if decision == "no_persist":
            base.update(memory_worthy=False, matched_claim_ids=[])
            return base
        if decision == "undetermined":
            base.update(memory_worthy=None, evidence=[], relations=[])
            return base
        base["memory_worthy"] = True

        if decision in {"append_supporting_evidence", "append_contradicting_evidence"}:
            if len(matched_ids) != 1:
                return self._undetermined("append_requires_single_target", clarification=False)
            if not evidence:
                return self._undetermined("append_requires_evidence", clarification=False)
            stance = "supports" if decision == "append_supporting_evidence" else "contradicts"
            base["evidence"] = [self._evidence_projection(item, stance, matched_ids[0]) for item in evidence]
            base["relations"] = []
            return base

        if raw.get("authority") == "model_inference" and decision == "create_active":
            decision = "create_candidate"
            base["decision_type"] = decision
        claim = self._normalize_new_claim(raw.get("claim"), decision, raw.get("authority"), evidence, snapshot)
        if isinstance(claim, str):
            return self._undetermined(claim, clarification=claim in {"missing_proposed_claim", "invalid_claim_identity"})

        exact, slot_ids = self._structural_matches(claim)
        if (exact and decision == 'create_active' and raw.get('authority') == 'user_direct'
                and claim['payload'].get('epistemic_kind') == 'user_instruction'):
            with self.database.connect() as connection:
                previous = connection.execute('SELECT lifecycle FROM memory_claims WHERE id=?', (exact,)).fetchone()
            if previous and previous['lifecycle'] == 'candidate':
                # Preserve the inferred candidate as history. Honor an explicit,
                # source-validated activation as a new confirmed instruction.
                claim['canonical_key'] += ':confirmed:' + _stable_id('instruction-confirmation', snapshot['turn_id'])
                base.update(claim=claim, matched_claim_ids=[exact],
                    evidence=[self._evidence_projection(item, 'supports', 'new_claim') for item in evidence],
                    relations=[{'relation_type': 'supersedes', 'target_claim_id': exact}])
                base['details']['old_claim_transition'] = {
                    'claim_id': exact, 'proposed_lifecycle': 'retired', 'basis': 'user_instruction_confirmation'}
                return base
        if exact and decision in {"create_active", "create_candidate", "append_supporting_evidence"}:
            if not evidence:
                return self._undetermined("append_requires_evidence", clarification=False)
            base.update(
                decision_type="append_supporting_evidence", claim=None,
                evidence=[self._evidence_projection(item, "supports", exact) for item in evidence],
                matched_claim_ids=[exact], relations=[],
            )
            return base
        if decision == "create_active" and slot_ids:
            decision = "create_competing_claim"
            base["decision_type"] = decision
            matched_ids = slot_ids
            claim["lifecycle"] = "candidate"

        if decision in {"create_active", "create_competing_claim", "refine_claim", "supersede_claim"} and not evidence:
            return self._undetermined("new_claim_requires_evidence", clarification=False)
        if decision == "create_competing_claim":
            competing = matched_ids or slot_ids
            if not competing:
                return self._undetermined("competing_claim_requires_slot_target", clarification=False)
            if any(candidate_by_id[item]["scope"] != claim["scope"] for item in competing if item in candidate_by_id):
                return self._undetermined("scope_mismatch", clarification=False)
            claim["lifecycle"] = "candidate"
            base.update(
                claim=claim, matched_claim_ids=competing, relations=[],
                evidence=[self._evidence_projection(item, "supports", "new_claim") for item in evidence],
            )
            return base
        if decision == "supersede_claim":
            if len(matched_ids) != 1:
                return self._undetermined("supersession_requires_single_target", clarification=False)
            target = candidate_by_id[matched_ids[0]]
            if target["scope"] != claim["scope"] or target["slot_key"] != claim.get("slot_key"):
                return self._undetermined("supersession_target_mismatch", clarification=False)
            if exact:
                if exact != matched_ids[0]:
                    return self._undetermined("supersession_identity_conflict", clarification=False)
                # A superseding claim is a new historical record. Some models
                # use the slot identity as canonical_key as well; make that
                # revision identity structurally distinct without interpreting
                # the payload or changing the stable slot relation.
                revision_material = json.dumps(
                    claim.get("payload") or {}, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"),
                )
                claim["canonical_key"] += ":revision:" + _stable_id(
                    "supersession-canonical", revision_material,
                ).split("-", 1)[0]
            change_type = raw.get("change_type")
            if change_type not in {"correction", "temporal_change"}:
                return self._undetermined("supersession_change_semantics_missing", clarification=False)
            user_evidence = [item for item in evidence if item["source_type"] == "user_message"]
            if not user_evidence:
                return self._undetermined("supersession_requires_user_evidence", clarification=False)
            projected = [self._evidence_projection(item, "supports", "new_claim") for item in evidence]
            old_transition = {"claim_id": matched_ids[0], "proposed_lifecycle": "retired"}
            if change_type == "correction":
                projected.extend(self._evidence_projection(item, "contradicts", matched_ids[0]) for item in user_evidence)
                old_transition["basis"] = "contradiction"
            else:
                old_transition.update(basis="validity_end", valid_until=claim.get("valid_from"))
            base["details"]["old_claim_transition"] = old_transition
            base.update(
                claim=claim, evidence=projected, matched_claim_ids=matched_ids,
                relations=[{"relation_type": "supersedes", "target_claim_id": matched_ids[0]}],
            )
            return base
        if decision == "refine_claim":
            if len(matched_ids) != 1:
                return self._undetermined("refinement_requires_single_target", clarification=False)
            target = candidate_by_id[matched_ids[0]]
            if target["scope"] != claim["scope"]:
                return self._undetermined("scope_mismatch", clarification=False)
            if exact:
                if exact != matched_ids[0]:
                    return self._undetermined('refinement_identity_conflict', clarification=False)
                revision_material = json.dumps({
                    'display_text': claim.get('display_text'),
                    'payload': claim.get('payload') or {},
                }, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                claim['canonical_key'] += ':refinement:' + _stable_id(
                    'refinement-canonical', revision_material,
                ).split('-', 1)[0]
            claim['lifecycle'] = target['lifecycle']
            base.update(
                claim=claim,
                evidence=[self._evidence_projection(item, "supports", "new_claim") for item in evidence],
                relations=[{"relation_type": "refines", "target_claim_id": matched_ids[0]}],
            )
            base["details"]["old_claim_transition"] = {
                "claim_id": matched_ids[0], "proposed_lifecycle": target["lifecycle"], "basis": "refinement",
            }
            return base

        base.update(
            decision_type=decision, claim=claim, matched_claim_ids=[], relations=[],
            evidence=[self._evidence_projection(item, "supports", "new_claim") for item in evidence],
        )
        return base

    def _validated_evidence(self, evidence, snapshot: dict) -> list[dict] | str:
        if not isinstance(evidence, list):
            return "invalid_evidence_shape"
        tools = {str(item["id"]): item for item in snapshot["tools"]}
        validated = []
        for raw in evidence:
            if not isinstance(raw, dict) or raw.get("source_type") not in _EVIDENCE_SOURCES:
                return "non_evidence_source"
            # Nullable unused selector fields carry no direct-result selection.
            # A string pointer (including the root) keeps null as an actual value.
            if raw.get('result_pointer') is None and raw.get('observed_value') is None:
                raw = {key: value for key, value in raw.items() if key not in {'result_pointer', 'observed_value'}}
            item = {
                "source_type": raw["source_type"], "source_id": str(raw.get("source_id") or ""),
                "stance": str(raw.get("stance") or "supports"),
                "property": raw.get("property"), "external_reference": raw.get("external_reference"),
            }
            if 'result_pointer' in raw:
                item['result_pointer'] = raw['result_pointer']
                if 'observed_value' in raw:
                    item['observed_value'] = raw['observed_value']
            if item["source_type"] == "user_message":
                if 'result_pointer' in raw or 'observed_value' in raw:
                    return 'result_evidence_requires_tool_source'
                if item["source_id"] != snapshot["user_message_id"]:
                    return "invented_message_reference"
            else:
                tool = tools.get(item["source_id"])
                if tool is None:
                    return "invented_tool_reference"
                if 'result_pointer' in raw:
                    if 'observed_value' not in raw:
                        return 'result_evidence_missing_value'
                    pointer = raw['result_pointer']
                    if not isinstance(pointer, str) or (pointer and not pointer.startswith('/')) or re.search(r'~(?![01])', pointer):
                        return 'result_evidence_invalid_pointer'
                    from .working_memory import WorkingMemoryStore
                    try:
                        original = json.loads(tool['result_json'] or '{}')
                        value = WorkingMemoryStore.pointer(original, pointer)
                    except (KeyError, IndexError, TypeError, ValueError):
                        return 'result_evidence_pointer_not_found'
                    try:
                        matches = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) == json.dumps(raw['observed_value'], sort_keys=True, ensure_ascii=False, allow_nan=False)
                    except (TypeError, ValueError):
                        matches = False
                    if not matches:
                        return 'result_evidence_value_mismatch'
                else:
                    if 'observed_value' in raw:
                        return 'result_evidence_missing_pointer'
                    if not item["property"] or not item["external_reference"]:
                        return "provider_evidence_not_property_specific"
                    if not self._provider_evidence_observed(tool, str(item["property"]), str(item["external_reference"])):
                        return "provider_evidence_not_observed"
            validated.append(item)
        return validated

    @staticmethod
    def _provider_evidence_observed(tool: dict, property_name: str, external_reference: str) -> bool:
        try:
            result = json.loads(tool["result_json"] or "{}")
        except (TypeError, ValueError):
            return False
        if not _contains_value(result, external_reference):
            return False
        if property_name in {"existence", "resource_exists", "entity_id", "external_reference"}:
            return True
        return any(property_name in item for item in _dict_with_reference(result, external_reference))

    @staticmethod
    def _evidence_projection(item: dict, stance: str, target_claim_id: str) -> dict:
        projected = dict(item)
        projected["stance"] = stance
        projected["target_claim_id"] = target_claim_id
        return projected

    def _normalize_new_claim(self, raw_claim, decision: str, authority, evidence: list[dict], snapshot: dict):
        if not isinstance(raw_claim, dict):
            return "missing_proposed_claim"
        claim = dict(raw_claim)
        if claim.get("kind") not in _KINDS:
            return "invalid_claim_shape"
        for key in ("scope", "canonical_key"):
            if not isinstance(claim.get(key), str) or not claim[key].strip():
                return "invalid_claim_identity"
        raw_scope = claim["scope"].strip()
        if re.fullmatch(r"[A-Za-z0-9._:-]+", raw_scope):
            claim["scope"] = raw_scope.casefold().replace("_", "-")
        if not _SCOPE.fullmatch(claim["scope"]):
            return "invalid_scope"
        if claim["canonical_key"].startswith("legacy:"):
            return "reserved_claim_namespace"
        payload = claim.get("payload") or {}
        if not isinstance(payload, dict):
            return "invalid_claim_payload"
        if payload.get('applicability') not in (None, 'query', 'always'):
            return 'invalid_instruction_applicability'
        if payload.get('applicability') == 'always' and payload.get('epistemic_kind') != 'user_instruction':
            return 'global_instruction_requires_user_grounding'
        if payload.get('epistemic_kind') == 'user_instruction':
            instruction = str(claim.get('display_text') or '')
            excerpt = _source_excerpt(instruction, snapshot['user_content'])
            if (authority != 'user_direct' or excerpt is None
                    or not any(item['source_type'] == 'user_message'
                               and item['source_id'] == snapshot['user_message_id'] for item in evidence)):
                return 'user_instruction_not_grounded_verbatim'
            claim['display_text'] = excerpt
        if claim["kind"] == "provider_binding":
            required = ("provider", "subject", "property", "external_reference")
            if not all(isinstance(payload.get(key), str) and payload[key].strip() for key in required):
                return "provider_binding_semantics_incomplete"
            provider_evidence = [item for item in evidence if item["source_type"] == "provider_result" and "result_pointer" not in item and item.get("external_reference") and item.get("property")]
            user_evidence = [item for item in evidence if item["source_type"] == "user_message"]
            if not provider_evidence or not user_evidence:
                return "provider_binding_requires_separate_sources"
            if not any(item["external_reference"] == payload["external_reference"] for item in provider_evidence):
                return "provider_binding_reference_mismatch"
            tool_by_id = {str(item["id"]): item for item in snapshot["tools"]}
            if not any(str(tool_by_id[item["source_id"]]["tool"]) == payload["provider"] for item in provider_evidence):
                return "provider_binding_provider_mismatch"
            anchor_tokens = _tokens(snapshot["user_content"] + " " + " ".join(
                str(item["external_reference"]) for item in provider_evidence
            ))
            subject_tokens = {token for token in _tokens(payload["subject"]) if len(token) >= 4}
            scope_tokens = {
                token for token in _tokens(claim["scope"].split(":", 1)[-1])
                if len(token) >= 4
            }
            if not subject_tokens or not (subject_tokens & anchor_tokens):
                return "provider_binding_subject_not_grounded"
            if claim["scope"].startswith(("device:", "provider:")) and scope_tokens and not (scope_tokens & anchor_tokens):
                return "provider_binding_scope_not_grounded"
            parts = [payload[key].strip().casefold() for key in required]
            claim["canonical_key"] = "provider_binding:" + ":".join(parts)
            claim["slot_key"] = "provider_binding:" + ":".join(parts[:3])
            payload["scope"] = claim["scope"]
            claim["verification_policy"] = "configuration"
        elif claim["kind"] == "alias":
            if not all(isinstance(payload.get(key), str) and payload[key].strip() for key in ("alias", "target")):
                return "claim_key_payload_mismatch"
            if not claim["canonical_key"].startswith("alias:"):
                return "claim_key_payload_mismatch"
        elif not claim["canonical_key"].startswith("v2:"):
            return "claim_key_payload_mismatch"
        claim["display_text"] = redact_sensitive(str(claim.get("display_text") or ""))[:1000]
        claim["payload"] = _safe_value(payload)
        for field in ("valid_from", "valid_until"):
            value = claim.get(field)
            if value is not None:
                try:
                    datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                except ValueError:
                    return "invalid_time_value"
        lifecycle = {
            "create_active": "active", "create_candidate": "candidate",
            "create_competing_claim": "candidate", "supersede_claim": "active",
        }.get(decision)
        if lifecycle:
            claim["lifecycle"] = lifecycle
        elif decision == 'refine_claim' and claim.get('lifecycle') is None:
            # The target supplies this structural value after reference
            # validation; Qwen does not need to repeat it.
            pass
        elif claim.get("lifecycle") not in {"active", "candidate"}:
            return "invalid_claim_shape"
        return claim

    def _structural_matches(self, claim: dict) -> tuple[str | None, list[str]]:
        with self.database.connect() as connection:
            exact = connection.execute(
                """SELECT id FROM memory_claims
                   WHERE scope=? AND claim_kind=? AND canonical_key=?""",
                (claim["scope"], claim["kind"], claim["canonical_key"]),
            ).fetchone()
            slots = connection.execute(
                """SELECT id FROM memory_claims
                   WHERE scope=? AND claim_kind=? AND slot_key=? AND slot_key IS NOT NULL""",
                (claim["scope"], claim["kind"], claim.get("slot_key")),
            ).fetchall() if claim.get("slot_key") else []
        return (str(exact["id"]) if exact else None, [str(item["id"]) for item in slots])

    def _persist(self, snapshot: dict, proposal: dict, method: str, metrics: dict, started: float) -> dict:
        write_started = time.perf_counter()
        user_observation_id = _stable_id("user-observation", snapshot["user_message_id"])
        decision_id = _stable_id(
            "decision", ":".join((snapshot["turn_id"], self.policy_version, self.prompt_version, self.model_version))
        )
        claim = proposal.get("claim") or {}
        evidence = proposal.get("evidence") or []
        positive = proposal["decision_type"] in _POSITIVE
        legacy_stored = bool(snapshot["legacy_writes"])
        if legacy_stored and not positive:
            comparison = "legacy_stored_v2_no_persist"
        elif not legacy_stored and positive:
            comparison = "legacy_missed_v2_persist"
        elif legacy_stored and positive:
            comparison = "both_persist"
        elif proposal["decision_type"] == "no_persist":
            comparison = "both_no_persist"
        else:
            comparison = "not_compared"
        metrics = dict(metrics)
        metrics["shadow_duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
        with self.database.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO memory_observations
                   (id,source_role,source_type,message_id,excerpt,structured_value_json,
                    observed_at,scope,metadata_json,created_at)
                   VALUES (?,?,'user_message',?,?,?,?,?,?,?)""",
                (user_observation_id, 'system' if snapshot.get('scheduled_execution') else 'user',
                 snapshot["user_message_id"], snapshot["user_content"][:240],
                 json.dumps({"content_location": "messages.content"}, ensure_ascii=False),
                 snapshot["created_at"], "conversation:" + snapshot["conversation_id"],
                 json.dumps(_input_provenance(snapshot), ensure_ascii=False), _now()),
            )
            tool_observations = []
            tool_by_id = {str(item["id"]): item for item in snapshot["tools"]}
            for item in evidence:
                if item.get("source_type") != "provider_result":
                    continue
                tool = tool_by_id[item["source_id"]]
                observation_id = _stable_id("tool-observation", str(tool["id"]))
                connection.execute(
                    """INSERT OR IGNORE INTO memory_observations
                       (id,source_role,source_type,tool_event_id,structured_value_json,
                        observed_at,scope,metadata_json,created_at)
                       VALUES (?,'provider','provider_result',?,?,?,?,?,?)""",
                    (observation_id, tool["id"], json.dumps({
                        "property": item["property"], "external_reference": item["external_reference"],
                        **({"result_pointer": item["result_pointer"], "observed_value": item["observed_value"]} if "result_pointer" in item else {}),
                        "status": tool["status"], "result_location": "conversation_tool_events.result_json",
                    }, ensure_ascii=False), tool["created_at"], "provider:" + str(tool["tool"]),
                     json.dumps({"property_specific": True}), _now()),
                )
                tool_observations.append(observation_id)
            metrics["db_write_ms"] = 0
            connection.execute(
                """INSERT OR IGNORE INTO memory_shadow_learning_decisions
                   (id,turn_id,primary_observation_id,decision_type,memory_worthy,
                    proposed_claim_kind,proposed_scope,proposed_canonical_key,proposed_slot_key,
                    proposed_lifecycle,proposed_payload_json,proposed_evidence_json,
                    matched_claims_json,proposed_relations_json,valid_from,valid_until,
                    method,policy_version,prompt_version,model_version,uncertainty,reason_code,
                    clarification_recommended,legacy_comparison,metrics_json,details_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (decision_id, snapshot["turn_id"], user_observation_id, proposal["decision_type"],
                 None if proposal.get("memory_worthy") is None else int(proposal["memory_worthy"]),
                 claim.get("kind"), claim.get("scope"), claim.get("canonical_key"), claim.get("slot_key"),
                 claim.get("lifecycle"), json.dumps({
                     "display_text": claim.get("display_text"), "payload": claim.get("payload") or {},
                     "verification_policy": claim.get("verification_policy"),
                 }, ensure_ascii=False), json.dumps(evidence, ensure_ascii=False),
                 json.dumps(proposal.get("matched_claim_ids") or []),
                 json.dumps(proposal.get("relations") or []), claim.get("valid_from"), claim.get("valid_until"),
                 method, self.policy_version, self.prompt_version, self.model_version,
                 proposal.get("uncertainty"), proposal["reason_code"],
                 int(proposal.get("clarification_recommended", False)), comparison,
                 json.dumps(metrics, ensure_ascii=False), json.dumps(proposal.get("details") or {}, ensure_ascii=False),
                 _now()),
            )
            connection.execute(
                """INSERT OR IGNORE INTO memory_shadow_decision_observations
                   (decision_id,observation_id,evidence_eligible,role) VALUES (?,?,1,'trigger')""",
                (decision_id, user_observation_id),
            )
            for observation_id in tool_observations:
                connection.execute(
                    """INSERT OR IGNORE INTO memory_shadow_decision_observations
                       (decision_id,observation_id,evidence_eligible,role) VALUES (?,?,1,'support')""",
                    (decision_id, observation_id),
                )
            metrics["db_write_ms"] = round((time.perf_counter() - write_started) * 1000, 3)
            connection.execute(
                "UPDATE memory_shadow_learning_decisions SET metrics_json=? WHERE id=?",
                (json.dumps(metrics, ensure_ascii=False), decision_id),
            )
        return {"id": decision_id, "turn_id": snapshot["turn_id"], **proposal, "method": method, "metrics": metrics}

    def report(self, *, all_policy_versions: bool = False) -> dict:
        where = "" if all_policy_versions else " WHERE policy_version=? AND prompt_version=? AND model_version=?"
        params = () if all_policy_versions else (self.policy_version, self.prompt_version, self.model_version)
        with self.database.connect() as connection:
            totals = dict(connection.execute(
                "SELECT decision_type,count(*) FROM memory_shadow_learning_decisions" + where
                + " GROUP BY decision_type", params,
            ).fetchall())
            rows = connection.execute(
                "SELECT id,turn_id,method,metrics_json,legacy_comparison "
                "FROM memory_shadow_learning_decisions" + where, params,
            ).fetchall()
            decision_ids = [str(row["id"]) for row in rows]
            if decision_ids:
                placeholders = ",".join("?" for _ in decision_ids)
                observations = int(connection.execute(
                    "SELECT count(DISTINCT observation_id) FROM memory_shadow_decision_observations "
                    f"WHERE decision_id IN ({placeholders})", decision_ids,
                ).fetchone()[0])
            else:
                observations = 0
        metrics = [json.loads(row["metrics_json"] or "{}") for row in rows]
        durations = [float(item.get("shadow_duration_ms", 0)) for item in metrics]
        unique_turns = len({str(row["turn_id"]) for row in rows})
        return {
            "turns_evaluated": len(rows), "decisions": totals,
            "llm_evaluations": sum(1 for row in rows if row["method"] in {"llm", "hybrid"}),
            "deterministic_decisions": sum(1 for row in rows if row["method"] == "deterministic"),
            "average_shadow_duration_ms": round(sum(durations) / len(durations), 3) if durations else 0,
            "user_visible_latency_added_ms": 0,
            "observations": observations,
            "observations_per_turn": round(observations / unique_turns, 3) if unique_turns else 0,
            "legacy_comparison": dict((key, sum(1 for row in rows if row["legacy_comparison"] == key))
                                      for key in {row["legacy_comparison"] for row in rows}),
        }

    def _diagnostic(self, exc: Exception, turn_id: str, stage: str) -> None:
        if self.diagnostics:
            try:
                self.diagnostics.record(
                    "shadow_learning", stage, "error", "Shadow-Learning-Auswertung fehlgeschlagen",
                    exception=exc, correlation=turn_id,
                )
            except (OSError, ValueError):
                pass


class ProductiveLearningPipeline(ShadowLearningPipeline):
    """Apply the validated Phase-2 contract atomically to Memory-v2 truth."""

    def __init__(self, database, llm=None, diagnostics=None, *, semantic_links=None):
        super().__init__(database, llm, diagnostics, policy_version=PRODUCTION_POLICY_VERSION)
        from .conversation_semantics import ConversationSemantics
        self.conversation_semantics = ConversationSemantics(database, semantic_links)

    def prioritize_interactive_turn(self) -> None:
        # The durable job remains pending, while an in-flight model inference
        # yields immediately to the interactive turn. No partial proposal has
        # reached the transactional persistence boundary at this point.
        super().prioritize_interactive_turn()

    def accept_turn(self, turn_id: str) -> dict:
        now = _now()
        with self.database.connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO memory_learning_jobs
                   (turn_id,status,accepted_at,updated_at) VALUES (?,'pending',?,?)""",
                (str(turn_id), now, now),
            )
            row = connection.execute(
                "SELECT * FROM memory_learning_jobs WHERE turn_id=?", (str(turn_id),)
            ).fetchone()
        return dict(row)

    def accept_episode(self, turn_id: str, source_turn_ids: list[str]) -> dict:
        """Attach explicitly selected earlier turns as context, not new claim evidence."""
        if not isinstance(source_turn_ids, list) or not source_turn_ids or not all(
                isinstance(item, str) and item for item in source_turn_ids):
            raise ValueError('Belegte Quellvorgänge fehlen')
        sources = list(dict.fromkeys(source_turn_ids))
        with self.database.connect(lifecycle_audit=False) as connection:
            connection.execute('BEGIN IMMEDIATE')
            target = connection.execute('SELECT conversation_id,created_at FROM turns WHERE id=?', (turn_id,)).fetchone()
            if target is None:
                raise KeyError('Lernauftrag wurde nicht gefunden')
            for source_id in sources:
                row = connection.execute('SELECT created_at FROM turns WHERE id=?', (source_id,)).fetchone()
                if row is None or source_id == turn_id or row[0] > target['created_at']:
                    raise ValueError('Quellvorgang fehlt oder liegt nicht vor dem Lernauftrag')
            prior = connection.execute("SELECT details_json FROM audit_events WHERE event_type='learning_episode' "
                "AND json_extract(details_json,'$.turn_id')=? ORDER BY id", (turn_id,)).fetchall()
            existing_sources = {source for row in prior for source in json.loads(row[0])['source_turn_ids']}
            if set(sources).issubset(existing_sources):
                return {'turn_id': turn_id, 'source_turn_ids': sources, 'idempotent': True}
            job = connection.execute('SELECT status FROM memory_learning_jobs WHERE turn_id=?', (turn_id,)).fetchone()
            if job and job[0] != 'pending':
                raise ValueError('Belege vor Beginn der Lernauswertung übergeben')
            connection.execute('INSERT INTO audit_events(conversation_id,event_type,actor,summary,details_json,created_at) '
                "VALUES (?,'learning_episode','user',?,?,?)", (target['conversation_id'],
                'Ausgewählte Lernfolge übergeben', json.dumps({'turn_id': turn_id, 'source_turn_ids': sources}), _now()))
            connection.execute("INSERT OR IGNORE INTO memory_learning_jobs(turn_id,status,accepted_at,updated_at) "
                               "VALUES (?,'pending',?,?)", (turn_id, _now(), _now()))
        return {'turn_id': turn_id, 'source_turn_ids': sources, 'status': 'pending'}

    def pending_turns(self) -> list[str]:
        now = _now()
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE memory_learning_jobs SET status='pending',updated_at=? WHERE status='running'",
                (now,),
            )
            rows = connection.execute(
                "SELECT turn_id FROM memory_learning_jobs WHERE status='pending' AND reviewed_at IS NULL ORDER BY accepted_at"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def queued_turns(self, limit: int) -> list[str]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT turn_id FROM memory_learning_jobs
                   WHERE status='pending' AND reviewed_at IS NULL ORDER BY accepted_at LIMIT ?""",
                (max(1, int(limit)),),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def job_counts(self) -> dict[str, int]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT CASE WHEN reviewed_at IS NOT NULL THEN 'reviewed' ELSE status END status,"
                "count(*) amount FROM memory_learning_jobs GROUP BY 1"
            ).fetchall()
        return {str(row["status"]): int(row["amount"]) for row in rows}

    def productive_outcome_counts(self) -> dict[str, int]:
        """Count applied jobs only when their persisted evidence is traceable to the turn."""
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT
                       count(DISTINCT j.turn_id) applied_turns,
                       count(DISTINCT CASE WHEN e.id IS NOT NULL THEN j.turn_id END) evidenced_turns,
                       count(DISTINCT e.id) evidence_records,
                       count(DISTINCT CASE WHEN e.id IS NOT NULL THEN e.claim_id END) evidenced_claims
                   FROM memory_learning_jobs j
                   LEFT JOIN memory_learning_decision_claims dc ON dc.decision_id=j.decision_id
                   LEFT JOIN memory_evidence e ON e.claim_id=dc.claim_id AND e.source_turn_id=j.turn_id
                   WHERE j.status='applied'"""
            ).fetchone()
        applied = int(row["applied_turns"] or 0)
        evidenced = int(row["evidenced_turns"] or 0)
        return {
            "applied_turns": applied,
            "evidenced_turns": evidenced,
            "applied_without_evidence": max(0, applied - evidenced),
            "evidence_records": int(row["evidence_records"] or 0),
            "evidenced_claims": int(row["evidenced_claims"] or 0),
        }

    def learning_jobs(self, status: str, *, limit: int = 40, offset: int = 0) -> dict:
        """Return the persisted provenance chain behind conversation-learning results."""
        allowed = {"pending", "running", "applied", "evidenced", "inconsistent", "no_persist", "failed", "reviewed"}
        status = str(status or "evidenced")
        if status not in allowed:
            raise ValueError("Unbekannter Gesprächslernen-Status")
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        evidence_exists = """EXISTS (
            SELECT 1 FROM memory_learning_decision_claims proof_dc
            JOIN memory_evidence proof_e ON proof_e.claim_id=proof_dc.claim_id
            WHERE proof_dc.decision_id=j.decision_id AND proof_e.source_turn_id=j.turn_id
        )"""
        if status == "evidenced":
            predicate, parameters = f"j.status='applied' AND {evidence_exists}", []
        elif status == "inconsistent":
            predicate, parameters = f"j.status='applied' AND NOT {evidence_exists}", []
        elif status == "reviewed":
            predicate, parameters = "j.reviewed_at IS NOT NULL", []
        else:
            predicate, parameters = "j.status=? AND j.reviewed_at IS NULL", [status]
        with self.database.connect(lifecycle_audit=False) as connection:
            total = int(connection.execute(
                f"SELECT count(*) FROM memory_learning_jobs j WHERE {predicate}", parameters,
            ).fetchone()[0])
            rows = connection.execute(
                f"""SELECT j.*,t.conversation_id,t.created_at turn_created_at,
                           t.completed_at turn_completed_at,t.knowledge_flow_json,c.title conversation_title,
                           user_message.content user_content,assistant_message.content assistant_content,
                           assistant_message.metadata_json assistant_metadata_json,
                           d.decision_type,d.method,d.rationale,d.uncertainty,
                           d.policy_version,d.model_version,d.created_at decision_created_at,d.metadata_json decision_metadata_json
                    FROM memory_learning_jobs j
                    JOIN turns t ON t.id=j.turn_id
                    LEFT JOIN conversations c ON c.id=t.conversation_id
                    LEFT JOIN messages user_message ON user_message.id=t.user_message_id
                    LEFT JOIN messages assistant_message ON assistant_message.id=t.assistant_message_id
                    LEFT JOIN memory_learning_decisions d ON d.id=j.decision_id
                    WHERE {predicate}
                    ORDER BY COALESCE(j.completed_at,j.started_at,j.accepted_at) DESC,j.turn_id
                    LIMIT ? OFFSET ?""",
                [*parameters, limit, offset],
            ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                decision_metadata = json.loads(item.pop('decision_metadata_json') or '{}')
                assistant_details = json.loads(item.pop('assistant_metadata_json') or '{}').get('turn_state_details', {})
                item['semantic_learning'] = decision_metadata.get('semantic_learning') or assistant_details.get('semantic_learning')
                item['general_learning'] = decision_metadata.get('general_learning') or assistant_details.get('general_learning')
                flow = json.loads(item.pop("knowledge_flow_json") or "{}")
                origins = {stage.get("details", {}).get("decision_origin")
                           for stage in flow.get("stages", []) if isinstance(stage, dict)}
                item["llm_usage"] = {
                    "execution": "yes" if "native_tool" in origins else
                    "no" if "semantic_replay" in origins else "unknown",
                    "learning": "yes" if item.get("method") in {"llm", "llm_batch", "hybrid"}
                    else "no" if item.get("method") == "deterministic" else "unknown",
                }
                turn_details = next((stage.get("details", {}) for stage in flow.get("stages", [])
                                     if stage.get("kind") == "turn_state"), {})
                item["execution_path"] = turn_details.get("semantic_reuse") if "semantic_replay" in origins else None
                if item.get("reviewed_at"):
                    item["original_status"] = item["status"]
                    item["status"] = "reviewed"
                decision_id = item.get("decision_id")
                claims = []
                if decision_id:
                    claim_rows = connection.execute(
                        """SELECT c.* FROM memory_learning_decision_claims dc
                           JOIN memory_claims c ON c.id=dc.claim_id
                           WHERE dc.decision_id=? ORDER BY c.created_at,c.id""",
                        (decision_id,),
                    ).fetchall()
                    for claim_row in claim_rows:
                        claim = dict(claim_row)
                        claim["payload"] = json.loads(claim.pop("payload_json") or "{}")
                        evidence_rows = connection.execute(
                            """SELECT id,stance,evidence_type,source_message_id,source_turn_id,
                                      tool_event_id,source_ref,excerpt,payload_json,observed_at,created_at
                               FROM memory_evidence
                               WHERE claim_id=? AND source_turn_id=? ORDER BY created_at,id""",
                            (claim["id"], item["turn_id"]),
                        ).fetchall()
                        claim["evidence"] = []
                        for evidence_row in evidence_rows:
                            evidence = dict(evidence_row)
                            evidence["payload"] = json.loads(evidence.pop("payload_json") or "{}")
                            claim["evidence"].append(evidence)
                        claims.append(claim)
                evidence_ids = [evidence["id"] for claim in claims for evidence in claim["evidence"]]
                relations = []
                if evidence_ids:
                    placeholders = ",".join("?" for _ in evidence_ids)
                    relations = [dict(value) for value in connection.execute(
                        f"""SELECT r.id,r.from_claim_id,r.to_claim_id,r.relation_type,r.evidence_id,r.created_at,
                                   source.display_text from_display_text,target.display_text to_display_text
                            FROM memory_relations r
                            LEFT JOIN memory_claims source ON source.id=r.from_claim_id
                            LEFT JOIN memory_claims target ON target.id=r.to_claim_id
                            WHERE r.evidence_id IN ({placeholders})
                            ORDER BY r.created_at,r.id""",
                        evidence_ids,
                    ).fetchall()]
                if item["status"] in {"failed", "reviewed"}:
                    attempt = connection.execute(
                        "SELECT structured_value_json FROM memory_observations WHERE turn_id=? "
                        "AND external_ref LIKE 'learning_attempt:%' ORDER BY created_at DESC LIMIT 1",
                        (item['turn_id'],)).fetchone()
                    item['latest_attempt'] = json.loads(attempt[0]) if attempt else None
                item["claims"] = claims
                # Bind execution records to this turn's answer, never to neighbouring turns.
                tool_rows = connection.execute(
                    "SELECT e.* FROM conversation_tool_events e JOIN turns t "
                    "ON t.assistant_message_id=e.message_id WHERE t.id=? ORDER BY e.ordinal",
                    (item["turn_id"],),
                ).fetchall()
                item["tool_events"] = []
                for tool_row in tool_rows:
                    tool = dict(tool_row)
                    tool["input"] = json.loads(tool.pop("input_json") or "{}")
                    tool["result"] = json.loads(tool.pop("result_json") or "{}")
                    item["tool_events"].append(tool)
                item["recognized_actions"] = []
                target_ids = sorted({claim["payload"].get("learned_claim_id") for claim in claims
                                     if isinstance(claim["payload"].get("learned_claim_id"), str)})
                target_ids = sorted(set(target_ids) | {claim['payload']['action_representation_id'] for claim in claims
                    if isinstance(claim['payload'].get('action_representation_id'), str)})
                if isinstance(turn_details.get("semantic_link_id"), str):
                    target_ids = sorted(set(target_ids) | {turn_details["semantic_link_id"]})
                for target_id in target_ids:
                    target = connection.execute(
                        "SELECT id,display_text,payload_json,lifecycle FROM memory_claims WHERE id=?",
                        (target_id,),
                    ).fetchone()
                    if target:
                        action = dict(target)
                        action["payload"] = json.loads(action.pop("payload_json") or "{}")
                        item["recognized_actions"].append(action)
                item["relations"] = relations
                item["evidence_count"] = sum(len(claim["evidence"]) for claim in claims)
                items.append(item)
        return {
            "status": status,
            "total": total,
            "offset": offset,
            "limit": limit,
            "items": items,
            "page": {"has_more": offset + len(items) < total, "next_offset": offset + len(items)},
        }

    def retry_failed(self) -> int:
        now = _now()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """UPDATE memory_learning_jobs
                   SET status='pending',error_class=NULL,started_at=NULL,completed_at=NULL,updated_at=?
                   WHERE status='failed' AND reviewed_at IS NULL""",
                (now,),
            )
        return int(cursor.rowcount)

    def review_turn(self, turn_id: str, note: str = "", *, reopen: bool = False) -> dict:
        """Close a real failure without asserting learning success or deleting evidence."""
        if not isinstance(turn_id, str) or not turn_id.strip() or not isinstance(note, str):
            raise ValueError('Turn-ID und Prüfnotiz müssen Zeichenketten sein')
        with self.database.connect(lifecycle_audit=False) as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT j.*,t.conversation_id FROM memory_learning_jobs j '
                            'JOIN turns t ON t.id=j.turn_id WHERE j.turn_id=?', (turn_id,)).fetchone()
            if row is None:
                raise ValueError('Lernauftrag wurde nicht gefunden')
            if row['status'] != 'failed':
                raise ValueError('Nur fehlgeschlagene Lernaufträge können geprüft werden')
            if bool(row['reviewed_at']) == (not reopen):
                return {'turn_id': turn_id, 'status': 'failed' if reopen else 'reviewed', 'idempotent': True}
            now = _now()
            c.execute('UPDATE memory_learning_jobs SET reviewed_at=?,review_note=?,updated_at=? WHERE turn_id=?',
                      (None if reopen else now, '' if reopen else note.strip(), now, turn_id))
            c.execute('INSERT INTO audit_events(conversation_id,event_type,actor,summary,details_json,created_at) '
                      'VALUES (?,?,?,?,?,?)', (row['conversation_id'], 'learning_review_reopened' if reopen else 'learning_reviewed',
                      'user', 'Lernfehler wieder geöffnet' if reopen else 'Lernfehler als geprüft abgeschlossen',
                      json.dumps({'turn_id': turn_id, 'error_class': row['error_class'],
                                  'note': note.strip(), 'previous_reviewed_at': row['reviewed_at'],
                                  'previous_review_note': row['review_note']}, ensure_ascii=False), now))
        return {'turn_id': turn_id, 'status': 'failed' if reopen else 'reviewed'}

    def retry_turn(self, turn_id: str, *, reopen_review: bool = False) -> dict:
        """Requeue a failed attempt, including an old rejection mislabeled no_persist.

        Genuine completed decisions are retained. No claim, proposal or source
        meaning is reconstructed from words here.
        An explicit reopen_review combines reopening and requeueing in one
        transaction, retaining the previous review in the audit history.
        """
        if not isinstance(turn_id, str) or not turn_id.strip():
            raise ValueError('Eine Turn-ID ist erforderlich')
        with self.database.connect(lifecycle_audit=False) as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT j.*,t.conversation_id,d.metadata_json FROM memory_learning_jobs j '
                'JOIN turns t ON t.id=j.turn_id LEFT JOIN memory_learning_decisions d ON d.id=j.decision_id '
                'WHERE j.turn_id=?', (turn_id,)).fetchone()
            if row is None:
                raise ValueError('Lernauftrag wurde nicht gefunden')
            if row['reviewed_at'] and not reopen_review:
                raise ValueError('Geprüften Lernauftrag zuerst wieder öffnen')
            metadata = json.loads(row['metadata_json'] or '{}')
            legacy_rejection = (row['status'] == 'no_persist' and
                                metadata.get('proposal_decision_type') in {'undetermined', 'shadow_error'})
            if row['status'] != 'failed' and not legacy_rejection:
                raise ValueError('Nur fehlgeschlagene oder früher als no_persist verbuchte Ablehnungen erneut ausführen')
            if row['reviewed_at']:
                c.execute('INSERT INTO audit_events(conversation_id,event_type,actor,summary,details_json,created_at) '
                    "VALUES (?,'learning_review_reopened','user',?,?,?)", (row['conversation_id'],
                    'Lernfehler für erneutes Lernen wieder geöffnet', json.dumps({
                        'turn_id': turn_id, 'error_class': row['error_class'],
                        'previous_reviewed_at': row['reviewed_at'],
                        'previous_review_note': row['review_note']}, ensure_ascii=False), _now()))
            c.execute('INSERT INTO audit_events(conversation_id,event_type,actor,summary,details_json,created_at) '
                "VALUES (?,'learning_retry','system',?,?,?)", (row['conversation_id'],
                'Fehlgeschlagenen Lernauftrag erneut eingereiht', json.dumps({
                    'turn_id': turn_id, 'previous_status': row['status'], 'previous_decision_id': row['decision_id'],
                    'previous_error': row['error_class'] or metadata.get('reason_code')}, ensure_ascii=False), _now()))
            c.execute("UPDATE memory_learning_jobs SET status='pending',decision_id=NULL,error_class=NULL,"
                "started_at=NULL,completed_at=NULL,reviewed_at=NULL,review_note='',updated_at=? WHERE turn_id=?", (_now(), turn_id))
        return {'turn_id': turn_id, 'status': 'pending'}

    def _analyze_context_batch(self, contexts, cancellation, cancellable):
        """Evaluate every complete context, splitting only after a real server rejection."""
        calls = 0

        def analyze(group):
            nonlocal calls
            cancellation.checkpoint()
            measure = getattr(self.llm, 'conversation_learning_context_budget', None)
            if callable(measure):
                budget = measure(group)
                if isinstance(budget, dict) and budget.get('fits') is False:
                    if len(group) > 1:
                        middle = len(group) // 2
                        left_items, left_failures = analyze(group[:middle])
                        right_items, right_failures = analyze(group[middle:])
                        return left_items + right_items, left_failures + right_failures
                    try:
                        calls += 1
                        response = self._analyze_context_via_working_memory(group[0], cancellation)
                    except ShadowLearningCancelled:
                        raise
                    except Exception as fallback_error:
                        self._diagnostic(fallback_error, group[0]['turn_id'], 'working_memory_learning')
                        return [], [{'turn_id': group[0]['turn_id'], 'error': fallback_error}]
                    items = response.get('turns') if isinstance(response, dict) else None
                    if (not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict)
                            or items[0].get('turn_id') != group[0]['turn_id']
                            or not isinstance(items[0].get('proposal'), dict)):
                        error = ValueError('invalid_working_memory_learning_response')
                        self._diagnostic(error, group[0]['turn_id'], 'working_memory_learning')
                        return [], [{'turn_id': group[0]['turn_id'], 'error': error}]
                    return items, []
            calls += 1
            try:
                if cancellable:
                    with cancellable(cancellation):
                        response = self.llm.analyze_conversation_learning(group)
                else:
                    response = self.llm.analyze_conversation_learning(group)
                    cancellation.checkpoint()
            except Exception as exc:
                if len(group) > 1 and _is_context_window_error(exc):
                    middle = len(group) // 2
                    left_items, left_failures = analyze(group[:middle])
                    right_items, right_failures = analyze(group[middle:])
                    return left_items + right_items, left_failures + right_failures
                if len(group) == 1 and _is_context_window_error(exc):
                    try:
                        response = self._analyze_context_via_working_memory(
                            group[0], cancellation,
                        )
                    except ShadowLearningCancelled:
                        raise
                    except Exception as fallback_error:
                        self._diagnostic(fallback_error, group[0]['turn_id'], 'working_memory_learning')
                        return [], [{'turn_id': group[0]['turn_id'], 'error': fallback_error}]
                    items = response.get("turns") if isinstance(response, dict) else None
                    if (not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict)
                            or items[0].get('turn_id') != group[0]['turn_id']
                            or not isinstance(items[0].get('proposal'), dict)):
                        error = ValueError('invalid_working_memory_learning_response')
                        self._diagnostic(error, group[0]['turn_id'], 'working_memory_learning')
                        return [], [{'turn_id': group[0]['turn_id'], 'error': error}]
                    return items, []
                from .llm import EmptyModelResponseError, LearningResponseError, LocalLLMOutputLimitError
                if isinstance(exc, ShadowLearningCancelled):
                    raise
                if len(group) > 1 and isinstance(exc, (EmptyModelResponseError, LocalLLMOutputLimitError)):
                    # Reduce a failed generation's workload, never repeat the same
                    # request or split unrelated transport/provider failures.
                    middle = len(group) // 2
                    left_items, left_failures = analyze(group[:middle])
                    right_items, right_failures = analyze(group[middle:])
                    return left_items + right_items, left_failures + right_failures
                if len(group) > 1 and isinstance(exc, LearningResponseError):
                    # Repair a broken group envelope with one request per turn.
                    items, failures = [], []
                    for context in group:
                        found, failed = analyze([context])
                        items.extend(found)
                        failures.extend(failed)
                    return items, failures
                self._diagnostic(exc, group[0]['turn_id'], 'batch_analysis')
                return [], [{'turn_id': context['turn_id'], 'error': exc} for context in group]
            items = response.get("turns") if isinstance(response, dict) else None
            from .llm import LearningResponseError
            if not isinstance(items, list):
                error = LearningResponseError('invalid_batch_cardinality', response)
                return [], [{'turn_id': context['turn_id'], 'error': error} for context in group]
            expected = {context['turn_id'] for context in group}
            by_turn = {turn_id: [] for turn_id in expected}
            for item in items:
                if isinstance(item, dict) and isinstance(item.get('turn_id'), str) and item['turn_id'] in expected:
                    by_turn[item['turn_id']].append(item)
            valid, missing = [], []
            for context in group:
                matches = by_turn[context['turn_id']]
                if len(matches) == 1 and isinstance(matches[0].get('proposal'), dict):
                    valid.append(matches[0])
                else:
                    missing.append(context)
            failures = []
            for context in missing:
                if len(group) > 1:
                    found, failed = analyze([context])
                    valid.extend(found)
                    failures.extend(failed)
                else:
                    error = LearningResponseError('invalid_batch_turn_response', response)
                    failures.append({'turn_id': context['turn_id'], 'error': error})
            return valid, failures

        items, failures = analyze(list(contexts))
        return {"turns": items, "failures": failures}, calls

    @staticmethod
    def _working_memory_tools():
        """Publish the existing structural work-memory contract without task semantics."""
        from .working_memory import contract
        allowed = {'status', 'list', 'inspect', 'read', 'save', 'checkpoint', 'reset_context'}
        capability = contract()
        tools, bindings = [], {}
        for operation, details in capability['operations'].items():
            if operation not in allowed:
                continue
            name = 'working_memory__' + operation
            schema = dict(details.get('parameters_schema') or {})
            schema.setdefault('type', 'object')
            schema.setdefault('properties', {})
            Draft202012Validator.check_schema(schema)
            tools.append({'type': 'function', 'function': {
                'name': name,
                'description': str(details.get('description') or capability['description']),
                'parameters': schema,
            }})
            bindings[name] = {
                'capability': 'working_memory', 'operation': operation,
                'effect': str(details.get('effect') or 'read'), 'schema': schema,
            }
        return {'working_memory': capability}, tools, bindings

    @staticmethod
    def _working_learning_entry(context, reference):
        """Exact small fields and explicit addresses; the full source stays intact."""
        root = '/text/turns/0'
        entry = {'turn_id': context['turn_id'], 'original_reference': reference,
                 'original_pointer': root, 'inline': {}, 'sections': [], 'tool_index': [],
                 'originals_retained': True, 'overview_is_complete_evidence': False}
        remaining = 14000
        inline_fields = {'user_message', 'assistant_context', 'claim_candidates', 'learning_revision',
                         'evidence_contract', 'provenance_contract', 'failure_learning_policy',
                         'applied_memory_revisions', 'failure_episodes', 'dialog_context', 'semantic_learning'}
        for key, value in context.items():
            pointer = root + '/' + key.replace('~', '~0').replace('/', '~1')
            size = len(json.dumps(value, ensure_ascii=False))
            entry['sections'].append({'field': key, 'pointer': pointer, 'characters': size,
                                      'items': len(value) if isinstance(value, (dict, list)) else None})
            if key in inline_fields and size <= min(6000, remaining):
                entry['inline'][key] = value
                remaining -= size
        semantic = context.get('semantic_learning') or {}
        if semantic.get('available') and 'semantic_learning' not in entry['inline']:
            # Keep exact protocol references visible even if historical context
            # makes the complete semantic section too large. No text interpretation.
            compact = {key: semantic[key] for key in
                       ('available', 'current_formulation', 'goal_observation_refs') if key in semantic}
            compact['original_pointer'] = root + '/semantic_learning'
            for key in ('executions', 'action_candidates'):
                value = semantic.get(key)
                if len(json.dumps(value, ensure_ascii=False)) <= min(4000, remaining):
                    compact[key] = value
                else:
                    compact[key + '_pointer'] = root + '/semantic_learning/' + key
            size = len(json.dumps(compact, ensure_ascii=False))
            if size <= remaining:
                entry['inline']['semantic_learning'] = compact
                remaining -= size
        for index, tool in enumerate(context.get('tool_events', [])[:12]):
            item = {key: tool[key] for key in ('id', 'tool', 'status', 'evidence_reference') if key in tool}
            item['pointer'] = root + '/tool_events/' + str(index)
            for key in ('observed_outcome', 'result_evidence'):
                value = tool.get(key)
                size = len(json.dumps(value, ensure_ascii=False))
                if value is not None and size <= min(1200, remaining):
                    item[key] = value
                    remaining -= size
            entry['tool_index'].append(item)
        return entry

    def _analyze_context_via_working_memory(self, context, cancellation):
        """Let Qwen page arbitrarily large evidence through the shared DB work memory."""
        from .learning_contract import learning_response_format
        from .llm import (EmptyModelResponseError, LearningResponseError, OpenAICompatibleLLM,
                          LocalLLMContextLimitError, LocalLLMOutputLimitError,
                          LocalLLMStreamError)
        from .working_context import WorkingMemorySession

        request = getattr(self.llm, 'request_tool_turn', None)
        if not callable(request):
            raise RuntimeError('working_memory_tool_runtime_unavailable')
        snapshot = self._snapshot(context['turn_id'])
        agent = SimpleNamespace(
            memory=SimpleNamespace(database=self.database),
            conversation_id=snapshot['conversation_id'], llm=self.llm,
            telemetry=None, _working_memory_context=None,
        )
        stored_request = {'turns': [context]}
        session = WorkingMemorySession(
            agent, stored_request, [], 'conversation-learning:' + context['turn_id'],
            isolated=True, retention_class='temporary_learning',
        )
        # begin_turn already retained the complete original request. Seed every
        # fresh context with the compact entry, never the oversized source again.
        entry = self._working_learning_entry(context, session.request['reference'])
        session.input['text'] = entry
        capabilities, tools, bindings = self._working_memory_tools()
        state = {'loaded_capabilities': ['working_memory']}
        schema = learning_response_format(batch=True, contexts=[context])['json_schema']['schema']
        structured_semantics = bool((context.get('semantic_learning') or {}).get('available'))
        if structured_semantics:
            # Publish structure as a native tool, not a schema copied into prose.
            capabilities['learning'] = {'operations': {'submit': {'effect': 'write', 'parameters_schema': schema}}}
            state['loaded_capabilities'].append('learning')
            tools.append({'type': 'function', 'function': {'name': 'learning__submit',
                'description': 'Submit the model-assessed learning decision. Executes no provider action.',
                'parameters': schema}})
            bindings['learning__submit'] = {'capability': 'learning', 'operation': 'submit',
                                           'effect': 'write', 'schema': schema}

        def publish(_capabilities, _loaded):
            return tools, bindings

        completion_contract = ('Finish with learning__submit.' if structured_semantics else
            'Return exactly one JSON object matching this schema: ' + json.dumps(schema, ensure_ascii=False, separators=(',', ':')))
        core_prompt = (
            OpenAICompatibleLLM._conversation_learning_messages([])[0]['content'] + '\n'
            'Evaluate one completed turn for stable cross-conversation knowledge. '
            'The full unabridged learning context is stored in working_memory under the request_reference '
            'published in the runtime message. Inspect and read it with JSON pointers and pagination; '
            'save intermediate material or a checkpoint when useful. Do not infer omitted values. '
            'The user message contains exact inline fields and a section/tool index. '
            'The original turn is at original_reference, pointer /text/turns/0. '
            'Read specific section or tool pointers only when needed; do not read the entire root. '
            'Inline evidence is already available and need not be read again. '
            'Identical reads add no evidence. Finish with a grounded proposal or no_persist for transient content. '
            'This attempt is bounded to 24 model rounds and 48 tool calls; six calls without new material stop it. '
            'Use only claim and evidence IDs from this turn. ' + completion_contract
        )
        messages = [
            {'role': 'system', 'content': core_prompt},
            {'role': 'user', 'content': json.dumps({
                'request_reference': session.identity()['request_reference'],
                'access': 'working_memory.inspect/read',
            }, ensure_ascii=False, separators=(',', ':'))},
        ]
        first = True
        rounds = tool_count = stagnant = 0
        seen_selections = set()
        try:
            while True:
                cancellation.checkpoint()
                if rounds >= 24:
                    raise LearningProgressError('learning_model_round_budget', rounds=rounds,
                                                tool_calls=tool_count, turn_id=context['turn_id'])
                rounds += 1
                messages, tools, replaced = session.prepare(
                    messages, tools, capabilities, state, core_prompt, publish,
                    force=first,
                )
                first = False
                if replaced is not None:
                    bindings = replaced
                try:
                    cancellable = getattr(self.llm, 'cancellable', None)
                    with cancellable(cancellation) if callable(cancellable) else nullcontext():
                        message = request(
                            messages, tools,
                            getattr(self.llm, 'generation_max_tokens', getattr(self.llm, 'max_tokens', None)),
                            0.0, role='conversation_learning_working_memory',
                            **({'tool_choice': 'required'} if structured_semantics else {}),
                        )
                        cancellation.checkpoint()
                except EmptyModelResponseError:
                    raise
                except LocalLLMOutputLimitError:
                    # A context reset cannot repair an output cap. Preserve its
                    # real category and partial response for review/retry.
                    raise
                except (LocalLLMContextLimitError, LocalLLMStreamError) as exc:
                    if (isinstance(exc, LocalLLMStreamError)
                            and exc.provider_code not in {'exceed_context_size_error',
                                'context_length_exceeded', 'working_context_limit'}):
                        raise
                    session.recover(messages, exc)
                    continue
                session.archive_frame(message, kind='model_message')
                calls = message.get('tool_calls') or []
                if not calls:
                    raw = str(message.get('content') or '').strip()
                    try:
                        value = parse_learning_json(raw)
                    except json.JSONDecodeError as exc:
                        raise LearningResponseError(
                            'Gesprächslernen über Working Memory lieferte ungültiges JSON', raw,
                        ) from exc
                    if not isinstance(value, dict) or not isinstance(value.get('turns'), list):
                        raise LearningResponseError(
                            'Gesprächslernen über Working Memory lieferte keine Turn-Liste', raw,
                        )
                    session.finish('completed', {'status': 'completed', 'turn_id': context['turn_id']})
                    return value

                assistant_calls = []
                for call in calls:
                    assistant_calls.append({
                        'id': str(call.get('id') or uuid.uuid4().hex), 'type': 'function',
                        'function': {'name': str(call.get('name') or ''),
                                     'arguments': json.dumps(call.get('arguments') or {},
                                                             ensure_ascii=False,
                                                             separators=(',', ':'))},
                    })
                session.last_round_start = len(messages)
                messages.append({'role': 'assistant', 'content': message.get('content') or None,
                                 'tool_calls': assistant_calls})
                for call, assistant_call in zip(calls, assistant_calls, strict=True):
                    if tool_count >= 48:
                        raise LearningProgressError('learning_tool_call_budget', rounds=rounds,
                                                    tool_calls=tool_count, turn_id=context['turn_id'])
                    tool_count += 1
                    name = str(call.get('name') or '')
                    binding = bindings.get(name)
                    parameters = dict(call.get('arguments') or {})
                    work_call = session.store.start_call(
                        session.workspace_id, session.turn_id, assistant_call['id'],
                        binding['capability'] if binding else 'unknown',
                        binding['operation'] if binding else name,
                        binding['effect'] if binding else 'unknown', parameters,
                    )
                    try:
                        if binding is None:
                            result = {'status': 'rejected', 'error': 'unpublished_tool'}
                        else:
                            Draft202012Validator(binding['schema']).validate(parameters)
                            session.store.dispatch_call(session.workspace_id, work_call)
                            if binding['capability'] == 'learning' and binding['operation'] == 'submit':
                                session.store.finish_call(session.workspace_id, session.turn_id, work_call,
                                                          {'status': 'completed', 'proposal_submitted': True})
                                session.finish('completed', {'status': 'completed', 'turn_id': context['turn_id']})
                                return parameters
                            result = session.execute(binding['operation'], parameters)
                    except ValidationError as exc:
                        result = {'status': 'error', 'error_class': 'ValidationError',
                                  'message': 'schema_validation_failed', 'field_errors': _schema_field_errors(exc)}
                    except Exception as exc:
                        result = {'status': 'error', 'error_class': type(exc).__name__,
                                  'message': redact_sensitive(str(getattr(exc, 'message', exc))),
                                  **({'structure': exc.structure} if hasattr(exc, 'structure') else {})}
                    operation = binding['operation'] if binding else name
                    selection = json.dumps({'operation': operation, 'parameters': {
                        **({'pointer': '', 'offset': 0, 'limit': None, 'fields': None,
                            'where': None, 'filters': []} if operation == 'read' else {}),
                        **parameters}}, sort_keys=True, ensure_ascii=False)
                    failed = isinstance(result, dict) and result.get('status') in {'error', 'rejected'}
                    novel = operation in {'read', 'inspect', 'list', 'events'} and not failed and selection not in seen_selections
                    if novel:
                        seen_selections.add(selection)
                        stagnant = 0
                    else:
                        stagnant += 1
                    if isinstance(result, dict) and (not novel or stagnant >= 3):
                        result = {**result, 'learning_progress': {
                            'new_material': novel, 'calls_without_new_material': stagnant,
                            'remaining_tool_calls': 48 - tool_count,
                            'message': 'No new material. Use the section index or finish the proposal; do not repeat this call.'}}
                    descriptor = session.store.finish_call(
                        session.workspace_id, session.turn_id, work_call, result,
                    )
                    tool_message = {'role': 'tool', 'tool_call_id': assistant_call['id'],
                                    'content': json.dumps(result, ensure_ascii=False,
                                                          separators=(',', ':'), default=str)}
                    messages.append(tool_message)
                    session.tool_frame(
                        tool_message, descriptor,
                        readable=binding is not None and binding['operation'] in {'read', 'inspect', 'list', 'status'},
                        selection=parameters if binding is not None and binding['operation'] in {'read', 'inspect'} else None,
                    )
                    if stagnant >= 6:
                        raise LearningProgressError('learning_navigation_stalled', rounds=rounds,
                            tool_calls=tool_count, calls_without_new_material=stagnant,
                            last_operation=operation, last_parameters=parameters, turn_id=context['turn_id'])
        except ShadowLearningCancelled:
            session.finish('cancelled', {'reason': 'interactive_turn_priority'})
            raise
        except Exception as exc:
            session.finish('failed', {'error_class': type(exc).__name__,
                                      'message': redact_sensitive(str(exc))})
            raise

    def process_batch(self, turn_ids: list[str]) -> list[dict]:
        """Analyze a bounded set of turns with one cancellable model request."""
        ordered = list(dict.fromkeys(str(item) for item in turn_ids if item))
        if not ordered:
            return []
        for turn_id in ordered:
            self.accept_turn(turn_id)
        with self.database.connect() as connection:
            placeholders = ",".join("?" for _ in ordered)
            rows = connection.execute(
                f"SELECT turn_id,status,reviewed_at FROM memory_learning_jobs WHERE turn_id IN ({placeholders})",
                ordered,
            ).fetchall()
        terminal = {str(row["turn_id"]) for row in rows if row["status"] in {"applied", "no_persist"} or row["reviewed_at"]}
        active = [item for item in ordered if item not in terminal]
        if not active:
            return [{"turn_id": item, "status": "complete", "idempotent": True} for item in ordered]

        event = threading.Event()
        self._evaluation_lock.acquire()
        with self._state_lock:
            self._active_cancel = event
        attempted = list(active)
        preparation_failures = {}
        now = _now()
        try:
            with self.database.connect() as connection:
                connection.execute('BEGIN IMMEDIATE')
                placeholders = ','.join('?' for _ in active)
                reviewed = {row[0] for row in connection.execute(
                    f"SELECT turn_id FROM memory_learning_jobs WHERE reviewed_at IS NOT NULL AND turn_id IN ({placeholders})", active)}
                for turn_id in reviewed:
                    preparation_failures[turn_id] = {'turn_id': turn_id, 'status': 'reviewed', 'idempotent': True}
                active = [turn_id for turn_id in active if turn_id not in reviewed]
                if not active:
                    return [preparation_failures[turn_id] for turn_id in attempted]
                connection.executemany(
                    """UPDATE memory_learning_jobs
                       SET status='running',attempt_count=attempt_count+1,started_at=?,updated_at=?,error_class=NULL
                       WHERE turn_id=?""",
                    [(now, now, turn_id) for turn_id in active],
                )
            snapshots, candidates, contexts = [], [], []
            for turn_id in active:
                try:
                    snapshot = self._snapshot(turn_id)
                    turn_candidates = self._claim_candidates(self._candidate_context(snapshot))
                    context = self._model_context(
                        snapshot, turn_candidates, include_rejected_proposal=False,
                    )
                except Exception as exc:
                    failed_at = _now()
                    with self.database.connect() as connection:
                        connection.execute(
                            """UPDATE memory_learning_jobs
                               SET status='failed',error_class=?,completed_at=?,updated_at=?
                               WHERE turn_id=? AND status='running'""",
                            (type(exc).__name__, failed_at, failed_at, turn_id),
                        )
                    self._diagnostic(exc, turn_id, "batch_preparation")
                    preparation_failures[turn_id] = {
                        "turn_id": turn_id, "status": "failed", "application_status": "failed",
                        "reason_code": type(exc).__name__, "error_class": type(exc).__name__,
                    }
                    continue
                snapshots.append(snapshot)
                candidates.append(turn_candidates)
                contexts.append(context)
            active = [snapshot["turn_id"] for snapshot in snapshots]
            if not active:
                return [preparation_failures[turn_id] for turn_id in attempted]
            cancellation = _Cancellation(event)
            started = time.perf_counter()
            if self.llm is None:
                raise RuntimeError("model_unavailable")
            cancellable = getattr(self.llm, "cancellable", None)
            batch_calls = 0
            analysis_failures = {}
            if hasattr(self.llm, "analyze_conversation_learning"):
                raw_batch, batch_calls = self._analyze_context_batch(
                    contexts, cancellation, cancellable,
                )
                raw_items = raw_batch.get("turns") if isinstance(raw_batch, dict) else None
                failed_items = raw_batch.get('failures', []) if isinstance(raw_batch, dict) else []
            else:
                failed_items = []
                raw_items = []
                for context in contexts:
                    cancellation.checkpoint()
                    batch_calls += 1
                    raw_items.append({
                        "turn_id": context["turn_id"],
                        "proposal": self.llm.analyze_shadow_learning(context),
                    })
            failed_by_turn = {
                str(item.get('turn_id')): item.get('error')
                for item in failed_items if isinstance(item, dict) and item.get('turn_id')
            }
            if failed_by_turn:
                retained = []
                for snapshot, turn_candidates, context in zip(snapshots, candidates, contexts, strict=True):
                    error = failed_by_turn.get(snapshot['turn_id'])
                    if error is None:
                        retained.append((snapshot, turn_candidates, context))
                        continue
                    analysis_failures[snapshot['turn_id']] = self._persist_unresolved(snapshot, {
                        'decision_type': 'shadow_error', 'reason_code': type(error).__name__,
                        'details': {'error_class': type(error).__name__,
                                    'message': redact_sensitive(str(error)),
                                    'raw_response': _audit_value(getattr(error, 'raw_response', None)),
                                    'response_evidence': _audit_value(getattr(error, 'response_evidence', None)),
                                    'partial_response': _audit_value(getattr(error, 'partial_response', None)),
                                    'finish_reason': getattr(error, 'finish_reason', None)},
                    }, 'llm_batch', {'llm_calls': 1})
                snapshots = [item[0] for item in retained]
                candidates = [item[1] for item in retained]
                contexts = [item[2] for item in retained]
                active = [snapshot['turn_id'] for snapshot in snapshots]
                if not active:
                    completed = {**preparation_failures, **analysis_failures}
                    return [completed[turn_id] for turn_id in attempted]
            if not isinstance(raw_items, list) or len(raw_items) != len(active):
                raise ValueError("invalid_batch_cardinality")
            proposals = {}
            for item in raw_items:
                if not isinstance(item, dict) or not isinstance(item.get("proposal"), dict):
                    raise ValueError("invalid_batch_item")
                turn_id = str(item.get("turn_id") or "")
                if turn_id not in active or turn_id in proposals:
                    raise ValueError("invalid_batch_turn_reference")
                proposals[turn_id] = item["proposal"]
            if set(proposals) != set(active):
                raise ValueError("missing_batch_turn")
            llm_ms = (time.perf_counter() - started) * 1000
            validated = []
            for snapshot, turn_candidates in zip(snapshots, candidates, strict=True):
                try:
                    value = self._validate_proposal(proposals[snapshot["turn_id"]], snapshot, turn_candidates)
                except Exception as exc:
                    value = {
                        'decision_type': 'shadow_error', 'reason_code': type(exc).__name__,
                        'details': {'error_class': type(exc).__name__, 'message': redact_sensitive(str(exc)),
                                    'stage': 'validation', 'raw_proposal': _audit_value(proposals[snapshot['turn_id']])},
                    }
                validated.append(value)
            # A distinct revision phase, not a retry loop. Another rejection stays
            # durable/failed and can be resumed through the existing retry action.
            rejected_indices = [i for i, proposal in enumerate(validated)
                                if proposal['decision_type'] == 'undetermined'
                                and proposal.get('details', {}).get('raw_proposal') is not None]
            revision_calls = 0
            if rejected_indices and hasattr(self.llm, 'analyze_conversation_learning'):
                for i in rejected_indices:
                    cancellation.checkpoint()
                    self._persist_unresolved(snapshots[i], validated[i], 'llm_batch', {'llm_calls': 1})
                with self.database.connect() as connection:
                    connection.executemany(
                        "UPDATE memory_learning_jobs SET status='running',updated_at=? WHERE turn_id=?",
                        [(_now(), snapshots[i]['turn_id']) for i in rejected_indices])
                for i in rejected_indices:
                    try:
                        revision_context = self._model_context(snapshots[i], candidates[i])
                        revision_batch, calls = self._analyze_context_batch(
                            [revision_context], cancellation, cancellable,
                        )
                        revision_calls += calls
                        items = revision_batch['turns']
                        failures = revision_batch.get('failures', [])
                        if failures:
                            raise failures[0]['error']
                        if (len(items) != 1 or items[0].get('turn_id') != snapshots[i]['turn_id']
                                or not isinstance(items[0].get('proposal'), dict)):
                            raise ValueError('invalid_revision_batch')
                        proposals[snapshots[i]['turn_id']] = items[0]['proposal']
                        validated[i] = self._validate_proposal(items[0]['proposal'], snapshots[i], candidates[i])
                    except ShadowLearningCancelled:
                        raise
                    except Exception as exc:
                        validated[i] = {
                            'decision_type': 'shadow_error', 'reason_code': type(exc).__name__,
                            'details': {'error_class': type(exc).__name__, 'message': redact_sensitive(str(exc)),
                                        'stage': 'revision',
                                        'original_reason_code': validated[i]['reason_code'],
                                        'raw_response': _audit_value(getattr(exc, 'raw_response', None)),
                                        'response_evidence': _audit_value(getattr(exc, 'response_evidence', None)),
                                        'partial_response': _audit_value(getattr(exc, 'partial_response', None)),
                                        'finish_reason': getattr(exc, 'finish_reason', None)},
                        }
                llm_ms = (time.perf_counter() - started) * 1000
            cancellation.begin_commit()
            results = []
            for index, (snapshot, proposal) in enumerate(zip(snapshots, validated, strict=True)):
                try:
                    # Earlier turns in this batch may have changed exact identities.
                    # Refresh structural validation without another model decision.
                    if proposal['decision_type'] not in {'undetermined', 'shadow_error'}:
                        proposal = self._validate_proposal(proposals[snapshot['turn_id']], snapshot, candidates[index])
                    result = self._persist(
                        snapshot, proposal, "llm_batch",
                        {
                            "llm_calls": batch_calls + revision_calls if index == 0 else 0,
                            "batch_llm_calls": batch_calls + revision_calls if index == 0 else 0,
                            "revision_phase": index in rejected_indices,
                            "batch_size": len(active),
                            "batch_llm_ms": round(llm_ms, 3),
                            "visible_latency_added_ms": 0,
                        }, started,
                    )
                except ShadowLearningCancelled:
                    raise
                except Exception as exc:
                    self._diagnostic(exc, snapshot['turn_id'], 'batch_persistence')
                    result = self._persist_unresolved(snapshot, {
                        'decision_type': 'shadow_error', 'reason_code': type(exc).__name__,
                        'details': {'error_class': type(exc).__name__, 'message': redact_sensitive(str(exc)),
                                    'stage': 'persistence', 'raw_proposal': _audit_value(proposals[snapshot['turn_id']])},
                    }, 'llm_batch', {})
                results.append(result)
            completed = {item["turn_id"]: item for item in results}
            completed.update(preparation_failures)
            completed.update(analysis_failures)
            return [completed[turn_id] for turn_id in attempted]
        except ShadowLearningCancelled:
            paused_at = _now()
            with self.database.connect() as connection:
                connection.executemany(
                    """UPDATE memory_learning_jobs SET status='pending',error_class=NULL,updated_at=?
                       WHERE turn_id=? AND status='running'""",
                    [(paused_at, turn_id) for turn_id in active],
                )
            raise
        except Exception as exc:
            failed_at = _now()
            for snapshot in locals().get('snapshots', []):
                with self.database.connect(lifecycle_audit=False) as c:
                    status = c.execute('SELECT status FROM memory_learning_jobs WHERE turn_id=?',
                                       (snapshot['turn_id'],)).fetchone()
                if status and status[0] == 'running':
                    self._persist_unresolved(snapshot, {
                        'decision_type': 'shadow_error', 'reason_code': type(exc).__name__,
                        'details': {'error_class': type(exc).__name__, 'message': str(exc),
                                    'raw_response': _audit_value(getattr(exc, 'raw_response', locals().get('raw_batch')))},
                    }, 'llm_batch', {})
            with self.database.connect() as connection:
                connection.executemany(
                    """UPDATE memory_learning_jobs SET status='failed',error_class=?,completed_at=?,updated_at=?
                       WHERE turn_id=? AND status='running'""",
                    [(type(exc).__name__, failed_at, failed_at, turn_id) for turn_id in active],
                )
            raise
        finally:
            with self._state_lock:
                if self._active_cancel is event:
                    self._active_cancel = None
            self._evaluation_lock.release()

    def process_turn(self, turn_id: str) -> dict:
        self.accept_turn(turn_id)
        now = _now()
        with self.database.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute(
                "SELECT status,reviewed_at FROM memory_learning_jobs WHERE turn_id=?", (str(turn_id),)
            ).fetchone()
            if row and row['reviewed_at']:
                return {"turn_id": str(turn_id), "status": "reviewed", "idempotent": True}
            if row and row[0] in {"applied", "no_persist"}:
                return {"turn_id": str(turn_id), "status": str(row[0]), "idempotent": True}
            connection.execute(
                """UPDATE memory_learning_jobs SET status='running',attempt_count=attempt_count+1,
                   started_at=?,updated_at=?,error_class=NULL WHERE turn_id=?""",
                (now, now, str(turn_id)),
            )
        return super().evaluate_turn(str(turn_id), expected_priority_generation=None)

    def _existing(self, turn_id: str) -> dict | None:
        with self.database.connect() as connection:
            job = connection.execute(
                "SELECT * FROM memory_learning_jobs WHERE turn_id=?", (turn_id,)
            ).fetchone()
            if job and job['reviewed_at']:
                return {**dict(job), 'status': 'reviewed', 'idempotent': True}
            if not job or job["status"] not in {"applied", "no_persist"}:
                return None
            decision = connection.execute(
                "SELECT * FROM memory_learning_decisions WHERE id=?", (job["decision_id"],)
            ).fetchone()
        return dict(decision) if decision else dict(job)

    @lifecycle_operation(
        "memory.productive_learning", "productive_learning",
        extractor=_productive_lifecycle_origin,
    )
    def _persist(self, snapshot: dict, proposal: dict, method: str,
                 metrics: dict, started: float) -> dict:
        """Commit independently validated learning branches; retries keep committed work."""
        general = deepcopy(proposal.get('general_proposal', proposal))
        for key in ('semantic_formulation', 'semantic_learning_reason', 'semantic_learning_error', 'general_proposal'):
            general.pop(key, None)
        general_id = _stable_id('productive-decision', ':'.join((snapshot['turn_id'], self.policy_version,
                                                               self.prompt_version, self.model_version)))
        with self.database.connect(lifecycle_audit=False) as c:
            previous = c.execute("SELECT * FROM memory_learning_decisions WHERE id=? OR "
                "(json_extract(metadata_json,'$.turn_id')=? AND json_extract(metadata_json,'$.general_learning.status')='applied') "
                "ORDER BY created_at LIMIT 1", (general_id, snapshot['turn_id'])).fetchone()
        previous_meta = json.loads(previous['metadata_json']) if previous else {}
        if previous_meta.get('general_learning', {}).get('status') == 'applied':
            general_result = {'id': previous['id'], 'turn_id': snapshot['turn_id'],
                              'decision_type': previous_meta['general_learning'].get('decision_type', previous['decision_type']), 'application_status': 'applied',
                              'method': previous['method'], 'claim_id': None}
        else:
            try:
                general_result = self._persist_general(snapshot, general, method, metrics, started)
            except Exception as exc:
                failure = self._undetermined(type(exc).__name__, clarification=False)
                failure['decision_type'] = 'shadow_error'
                failure['details'].update(stage='persistence', error_class=type(exc).__name__)
                general_result = self._persist_unresolved(snapshot,
                    failure, method, metrics, update_job=False)
        general_status = {'status': general_result['application_status'],
                          'reason': general_result.get('reason_code'), 'decision_type': general_result['decision_type']}
        decision_id = general_result.get('id')
        # Checkpoint a completed general branch before trying semantic persistence.
        if decision_id:
            with self.database.connect() as c:
                row = c.execute('SELECT metadata_json FROM memory_learning_decisions WHERE id=?', (decision_id,)).fetchone()
                metadata = json.loads(row[0]); metadata['general_learning'] = general_status
                c.execute('UPDATE memory_learning_decisions SET metadata_json=? WHERE id=?',
                          (json.dumps(metadata, ensure_ascii=False), decision_id))
        semantic_result = None
        semantic_error = proposal.get('semantic_learning_error')
        record = proposal.get('semantic_formulation')
        try:
            session = self.conversation_semantics.session(snapshot)
            if record is not None:
                self.conversation_semantics.validate(snapshot, record, session=session)
                with self.database.connect() as c:
                    semantic_result = self.conversation_semantics.persist(snapshot, record, c, session=session)
            elif session is not None:
                with self.database.connect() as c:
                    semantic_result = self.conversation_semantics.existing(snapshot, c, session=session)
            if semantic_result is None and proposal.get('semantic_learning_reason') and not semantic_error:
                semantic_result = {'kind': 'not_reusable', 'reason': proposal['semantic_learning_reason']}
        except Exception as exc:
            semantic_error = str(getattr(exc, 'message', exc))[:1000]
        if semantic_error:
            semantic_result = {'kind': 'rejected', 'reason': semantic_error}
        failed = general_status['status'] == 'failed' or bool(semantic_error)
        decision_type = general_result['decision_type']
        semantic_claim = (semantic_result or {}).get('claim_id')
        if semantic_claim and (decision_type in {'no_persist', 'undetermined', 'shadow_error'}):
            decision_type = ('append_supporting_evidence' if semantic_result['kind'] == 'supporting_evidence'
                             else 'create_active' if semantic_result['release'] == 'active' else 'create_candidate')
        with self.database.connect() as c:
            # A semantic-only result still gets a decision receipt if the general branch failed.
            if decision_id is None and semantic_claim:
                decision_id = _stable_id('productive-semantic-decision', snapshot['turn_id'])
                c.execute('INSERT OR IGNORE INTO memory_learning_decisions '
                          '(id,decision_type,method,policy_version,model_version,rationale,metadata_json,created_at) '
                          'VALUES (?,?,?,?,?,?,?,?)',
                          (decision_id, decision_type, method, self.policy_version, self.model_version,
                           proposal.get('semantic_learning_reason'), '{}', _now()))
            if decision_id:
                metadata = json.loads(c.execute('SELECT metadata_json FROM memory_learning_decisions WHERE id=?',
                                               (decision_id,)).fetchone()[0])
                metadata.update(mode='productive', status='failed' if failed else 'applied',
                                turn_id=snapshot['turn_id'], general_learning=general_status)
                if semantic_result is not None:
                    metadata['semantic_learning'] = semantic_result
                c.execute('UPDATE memory_learning_decisions SET decision_type=?,metadata_json=? WHERE id=?',
                          (decision_type, json.dumps(metadata, ensure_ascii=False), decision_id))
                if semantic_claim:
                    c.execute('INSERT OR IGNORE INTO memory_learning_decision_claims VALUES (?,?)',
                              (decision_id, semantic_claim))
            message = c.execute('SELECT metadata_json FROM messages WHERE id=?', (snapshot['assistant_message_id'],)).fetchone()
            if message:
                metadata = json.loads(message[0]); details = metadata.setdefault('turn_state_details', {})
                details['general_learning'] = general_status
                if semantic_result is not None:
                    details['semantic_learning'] = semantic_result
                c.execute('UPDATE messages SET metadata_json=? WHERE id=?',
                          (json.dumps(metadata, ensure_ascii=False), snapshot['assistant_message_id']))
            c.execute('UPDATE memory_learning_jobs SET status=?,decision_id=?,error_class=?,completed_at=?,updated_at=? WHERE turn_id=?',
                      ('failed' if failed else 'no_persist' if decision_type == 'no_persist' else 'applied', decision_id,
                       semantic_error or (general_status['reason'] if failed else None), _now(), _now(), snapshot['turn_id']))
        return {**general_result, 'id': decision_id, 'decision_type': decision_type,
                'application_status': 'failed' if failed else 'applied', 'general_learning': general_status,
                'semantic_learning': semantic_result, 'claim_id': semantic_claim or general_result.get('claim_id')}

    def _persist_general(self, snapshot: dict, proposal: dict, method: str,
                 metrics: dict, started: float) -> dict:
        now = _now()
        turn_id = snapshot["turn_id"]
        feedback = self._revision_feedback(turn_id)
        if feedback:
            proposal = {**proposal, "details": {**proposal.get("details", {}),
                "revision_of_attempt": feedback["attempt_observation_id"]}}
        user_observation_id = _stable_id("productive-user-observation", snapshot["user_message_id"])
        decision_id = _stable_id(
            "productive-decision", ":".join((turn_id, self.policy_version, self.prompt_version, self.model_version))
        )
        original_type = str(proposal.get("decision_type") or "undetermined")
        if original_type in {"undetermined", "shadow_error"}:
            return self._persist_unresolved(snapshot, proposal, method, metrics, update_job=False)
        if original_type not in _POSITIVE | {"no_persist"}:
            rejected = self._undetermined("invalid_decision_type", clarification=False)
            rejected['details']['raw_proposal'] = _audit_value(proposal)
            return self._persist_unresolved(snapshot, rejected, method, metrics, update_job=False)
        failed = False
        decision_type = original_type
        claim = proposal.get("claim") or {}
        evidence = proposal.get("evidence") or []
        claim_id = _stable_id("productive-claim", decision_id) if claim else None
        observation_by_source = {snapshot["user_message_id"]: user_observation_id}
        metrics = {**metrics, "productive_duration_ms": round((time.perf_counter() - started) * 1000, 3)}
        try:
            with self.database.connect() as connection:
                # A completed direct correction wins over older queued learning.
                # Match only persisted identities/slots, never interpret wording.
                if decision_type in _POSITIVE:
                    connection.execute('BEGIN IMMEDIATE')
                    revisions = connection.execute(
                        "SELECT d.created_at,d.metadata_json,c.id,c.scope,c.slot_key,c.lifecycle "
                        "FROM memory_learning_decisions d JOIN memory_learning_decision_claims l ON l.decision_id=d.id "
                        "JOIN memory_claims c ON c.id=l.claim_id WHERE d.method='direct_revision' "
                        "AND json_extract(d.metadata_json,'$.action') IN ('correct','temporal_change','retract','refine') "
                        "AND c.lifecycle IN ('retired','invalid')"
                    ).fetchall()
                    matched = set(proposal.get('matched_claim_ids') or [])
                    for revision in revisions:
                        same_slot = bool(claim and claim.get('slot_key') and claim.get('slot_key') == revision['slot_key']
                                         and claim.get('scope') == revision['scope'])
                        stale_source = (snapshot['created_at'] <= revision['created_at'] or
                            json.loads(revision['metadata_json']).get('source_turn_reference') == turn_id)
                        if revision['id'] in matched or (same_slot and stale_source):
                            decision_type = 'no_persist'
                            claim_id, claim, evidence = None, {}, []
                            proposal = {**proposal, 'decision_type': 'no_persist', 'claim': None,
                                        'evidence': [], 'relations': [], 'matched_claim_ids': [],
                                        'reason_code': 'direct_revision_already_applied', 'details': {}}
                            break
                if claim_id and decision_type in {"create_active", "create_candidate"}:
                    # Reserve the writer before reading the identity. This is the
                    # same transaction as the eventual insert/evidence attachment.
                    if not connection.in_transaction:
                        connection.execute("BEGIN IMMEDIATE")
                    existing = connection.execute(
                        "SELECT id FROM memory_claims WHERE scope=? AND claim_kind=? AND canonical_key=?",
                        (claim["scope"], claim["kind"], claim["canonical_key"]),
                    ).fetchone()
                    if existing:
                        target = str(existing["id"])
                        decision_type = "append_supporting_evidence"
                        claim_id, claim = None, {}
                        evidence = [self._evidence_projection(item, "supports", target) for item in evidence]
                        proposal = {**proposal, "decision_type": decision_type, "claim": None,
                                    "matched_claim_ids": [target], "evidence": evidence, "relations": []}
                protected_targets = {
                    str(item) for item in proposal.get("matched_claim_ids") or [] if item
                }
                protected_targets.update(
                    str(item.get("target_claim_id")) for item in evidence
                    if item.get("target_claim_id") not in {None, "new_claim"}
                )
                protected_targets.update(
                    str(item.get("target_claim_id")) for item in proposal.get("relations") or []
                    if item.get("target_claim_id")
                )
                transition = (proposal.get("details") or {}).get("old_claim_transition") or {}
                if transition.get("claim_id"):
                    protected_targets.add(str(transition["claim_id"]))
                if not failed and decision_type in _POSITIVE:
                    self.database.assert_runtime_self_knowledge_writable(
                        connection, claim_ids=protected_targets, proposed_claim=claim,
                    )
                connection.execute(
                    """INSERT OR IGNORE INTO memory_observations
                       (id,source_role,source_type,message_id,turn_id,excerpt,structured_value_json,
                        observed_at,scope,metadata_json,created_at)
                       VALUES (?,?,'user_message',?,?,?,?,?,?,?,?)""",
                    (user_observation_id, 'system' if snapshot.get('scheduled_execution') else 'user',
                     snapshot["user_message_id"], turn_id,
                     snapshot["user_content"][:240],
                     json.dumps({"content_location": "messages.content"}, ensure_ascii=False),
                     snapshot["created_at"], "conversation:" + snapshot["conversation_id"],
                     json.dumps(_input_provenance(snapshot), ensure_ascii=False), now),
                )
                tools = {str(item["id"]): item for item in snapshot["tools"]}
                for item in evidence:
                    if item.get("source_type") != "provider_result":
                        continue
                    tool = tools[item["source_id"]]
                    selection = json.dumps({key: item.get(key) for key in
                        ('source_id', 'result_pointer', 'property', 'external_reference')}, sort_keys=True, ensure_ascii=False)
                    observation_id = _stable_id("productive-tool-observation", selection)
                    connection.execute(
                        """INSERT OR IGNORE INTO memory_observations
                           (id,source_role,source_type,turn_id,tool_event_id,structured_value_json,
                            observed_at,scope,metadata_json,created_at)
                           VALUES (?,'provider','provider_result',?,?,?,?,?,?,?)""",
                        (observation_id, turn_id, tool["id"], json.dumps({
                            "property": item["property"],
                            "external_reference": item["external_reference"],
                            **({"result_pointer": item["result_pointer"], "observed_value": item["observed_value"]} if "result_pointer" in item else {}),
                            "result_location": "conversation_tool_events.result_json",
                        }, ensure_ascii=False), tool["created_at"],
                         "provider:" + str(tool["tool"]),
                         json.dumps({"property_specific": True}), now),
                    )
                    observation_by_source[selection] = observation_id

                metadata = {
                    "mode": "productive", "status": "failed" if failed else "applied",
                    "general_learning": {"status": "failed" if failed else "applied", "decision_type": decision_type,
                                         "reason": proposal.get("reason_code")},
                    "turn_id": turn_id, "prompt_version": self.prompt_version,
                    "reason_code": proposal.get("reason_code"),
                    "proposal_decision_type": original_type,
                    "metrics": metrics,
                    "failure_episodes": _safe_value(snapshot.get("failure_episodes", [])),
                    "failure_learning_guard": (proposal.get("details") or {}).get("failure_learning_guard"),
                }
                connection.execute(
                    """INSERT OR IGNORE INTO memory_learning_decisions
                       (id,observation_id,decision_type,method,policy_version,model_version,
                        rationale,metadata_json,uncertainty,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (decision_id, user_observation_id, decision_type, method,
                     self.policy_version, self.model_version,
                     str(proposal.get("reason_code") or original_type),
                     json.dumps(metadata, ensure_ascii=False), proposal.get("uncertainty"), now),
                )

                if not failed and decision_type in _POSITIVE:
                    if claim_id:
                        connection.execute(
                            """INSERT INTO memory_claims
                               (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,
                                lifecycle,valid_from,valid_until,verification_policy,created_at,updated_at)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (claim_id, claim["kind"], claim["scope"], claim["canonical_key"],
                             claim.get("slot_key"), claim.get("display_text") or "",
                             json.dumps(claim.get("payload") or {}, ensure_ascii=False, sort_keys=True),
                             claim["lifecycle"], claim.get("valid_from"), claim.get("valid_until"),
                             claim.get("verification_policy") or "unknown", now, now),
                        )
                        connection.execute(
                            "INSERT INTO memory_learning_decision_claims(decision_id,claim_id) VALUES (?,?)",
                            (decision_id, claim_id),
                        )
                    created_evidence = []
                    for index, item in enumerate(evidence):
                        target = claim_id if item.get("target_claim_id") == "new_claim" else item.get("target_claim_id")
                        if not target:
                            continue
                        selection = (json.dumps({key: item.get(key) for key in
                            ('source_id', 'result_pointer', 'property', 'external_reference')}, sort_keys=True, ensure_ascii=False)
                            if item['source_type'] == 'provider_result' else item['source_id'])
                        observation_id = observation_by_source[selection]
                        evidence_id = _stable_id(
                            "productive-evidence", f"{decision_id}:{target}:{observation_id}:{item['stance']}:{index}"
                        )
                        tool_event_id = item["source_id"] if item["source_type"] == "provider_result" else None
                        connection.execute(
                            """INSERT INTO memory_evidence
                               (id,claim_id,observation_id,stance,evidence_type,source_message_id,
                                source_turn_id,tool_event_id,payload_json,observed_at,created_at)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?)
                               ON CONFLICT(claim_id,observation_id,evidence_type) DO NOTHING""",
                            (evidence_id, target, observation_id, item["stance"], item["source_type"],
                             snapshot["user_message_id"] if item["source_type"] == "user_message" else None,
                             turn_id, tool_event_id, json.dumps({
                                 "property": item.get("property"),
                                 "external_reference": item.get("external_reference"),
                                 **({"result_pointer": item["result_pointer"], "observed_value": item["observed_value"]} if "result_pointer" in item else {}),
                             }, ensure_ascii=False), snapshot["created_at"], now),
                        )
                        stored = connection.execute(
                            'SELECT id,stance FROM memory_evidence WHERE claim_id=? AND observation_id=? AND evidence_type=?',
                            (target, observation_id, item['source_type'])).fetchone()
                        if stored['stance'] != item['stance']:
                            raise ValueError('conflicting_evidence_stance_for_same_observation')
                        created_evidence.append(stored['id'])
                        connection.execute(
                            "INSERT OR IGNORE INTO memory_learning_decision_claims(decision_id,claim_id) VALUES (?,?)",
                            (decision_id, target),
                        )
                    for index, relation in enumerate(proposal.get("relations") or []):
                        relation_id = _stable_id("productive-relation", f"{decision_id}:{index}")
                        connection.execute(
                            """INSERT INTO memory_relations
                               (id,from_claim_id,to_claim_id,relation_type,evidence_id,created_at)
                               VALUES (?,?,?,?,?,?)""",
                            (relation_id, claim_id, relation["target_claim_id"], relation["relation_type"],
                             created_evidence[0] if created_evidence else None, now),
                        )
                    if not created_evidence:
                        raise ValueError("applied_learning_requires_persisted_evidence")
                    if transition:
                        connection.execute(
                            """UPDATE memory_claims SET lifecycle=?,valid_until=COALESCE(?,valid_until),updated_at=?
                               WHERE id=?""",
                            (transition["proposed_lifecycle"], transition.get("valid_until") or now,
                             now, transition["claim_id"]),
                        )

                # The coordinator finalizes the job after both branches have receipts.
        except Exception:
            with self.database.connect() as connection:
                connection.execute(
                    """UPDATE memory_learning_jobs SET status='failed',error_class=?,completed_at=?,updated_at=?
                       WHERE turn_id=?""",
                    ("integration_error", now, now, turn_id),
                )
            raise
        return {
            "id": decision_id, "turn_id": turn_id, **proposal, "method": method,
            "decision_type": decision_type,
            "metrics": metrics, "application_status": "failed" if failed else "applied",
            "claim_id": claim_id,
        }

    def _persist_unresolved(self, snapshot, proposal, method, metrics, *, update_job=True):
        """Keep rejected output as diagnostics, never as a successful no_persist."""
        identifier = str(uuid.uuid4())
        now = _now()
        reason = str(proposal.get('reason_code') or proposal['decision_type'])
        previous = self._revision_feedback(snapshot['turn_id'])
        payload = {'status': 'failed', 'reason_code': reason, 'method': method,
                   'revision_of_attempt': previous['attempt_observation_id'] if previous else None,
                   'policy_version': self.policy_version, 'prompt_version': self.prompt_version,
                   'model_version': self.model_version, 'proposal': _audit_value(proposal), 'metrics': metrics}
        with self.database.connect(lifecycle_audit=False) as c:
            c.execute('INSERT INTO memory_observations '
                '(id,source_role,source_type,turn_id,external_ref,structured_value_json,observed_at,scope,metadata_json,created_at) '
                "VALUES (?,'system','turn',?,?,?,?,?,?,?)", (identifier, snapshot['turn_id'],
                'learning_attempt:' + identifier, json.dumps(payload, ensure_ascii=False), now,
                'conversation:' + snapshot['conversation_id'],
                json.dumps({'kind': 'learning_attempt', 'status': 'failed'}), now))
            if update_job:
                c.execute("UPDATE memory_learning_jobs SET status='failed',decision_id=NULL,error_class=?,completed_at=?,updated_at=? WHERE turn_id=?",
                          (reason, now, now, snapshot['turn_id']))
            c.execute('INSERT INTO audit_events(conversation_id,event_type,actor,summary,details_json,created_at) '
                "VALUES (?,'learning_failure','system',?,?,?)", (snapshot['conversation_id'],
                'Lernvorschlag konnte nicht übernommen werden', json.dumps({'turn_id': snapshot['turn_id'],
                'reason_code': reason, 'attempt_observation_id': identifier}, ensure_ascii=False), now))
        return {'turn_id': snapshot['turn_id'], **proposal, 'method': method,
                'application_status': 'failed', 'attempt_observation_id': identifier, 'claim_id': None}
