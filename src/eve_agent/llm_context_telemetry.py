"""Optional proof of Memory-v2 claims crossing concrete LLM boundaries.

The sidecar contains technical identities only.  It is tied to the actual
Python message and content objects so a replaced context cannot inherit claim
provenance merely because its text happens to look similar.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .provenance import new_id


_TECHNICAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,255}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _technical(value) -> str | None:
    text = str(value or "")
    return text if _TECHNICAL_ID.fullmatch(text) else None


@dataclass(frozen=True)
class ContextClaim:
    claim_id: str
    compiler_evaluation_id: str
    ordinal: int


@dataclass(frozen=True)
class ContextBlock:
    context_block_id: str
    message_index: int
    block_role: str
    message_ref: dict
    content_ref: object
    claims: tuple[ContextClaim, ...]


@dataclass
class LLMContextSidecar:
    trace_id: str
    planner_round_id: str
    llm_call_id: str
    consumer: str
    conversation_id: str | None
    turn_id: str | None
    messages_ref: list[dict]
    blocks: tuple[ContextBlock, ...]
    context_manifest_digest: str
    assembled_at: str = field(default_factory=_now)
    assembly_emitted: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def validates(self, messages) -> bool:
        if messages is not self.messages_ref:
            return False
        for block in self.blocks:
            if block.message_index >= len(messages):
                return False
            message = messages[block.message_index]
            if message is not block.message_ref:
                return False
            if message.get("role") != block.block_role:
                return False
            if message.get("content") is not block.content_ref:
                return False
        return True


@dataclass
class LLMAttemptObservation:
    trace_id: str
    conversation_id: str | None
    sidecar: LLMContextSidecar | None
    messages_ref: list[dict] | None
    metrics: dict
    events: list[dict] = field(default_factory=list)


class LLMContextTelemetry:
    """Record every transported Memory identity without affecting an LLM call."""

    def __init__(self, recorder):
        self.recorder = recorder

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.recorder, "enabled", False))

    def assemble(self, *, messages: list[dict], blocks: list[dict], trace_id: str,
                 planner_round_id: str, llm_call_id: str, consumer: str,
                 conversation_id: str | None = None,
                 turn_id: str | None = None) -> LLMContextSidecar | None:
        if not self.enabled:
            return None
        technical = {
            "trace_id": _technical(trace_id),
            "planner_round_id": _technical(planner_round_id),
            "llm_call_id": _technical(llm_call_id),
            "consumer": _technical(consumer),
        }
        if any(value is None for value in technical.values()):
            return None
        prepared: list[ContextBlock] = []
        manifest_blocks = []
        for raw_block in blocks:
            index = raw_block.get("message_index")
            if type(index) is not int or index < 0 or index >= len(messages):
                continue
            message = messages[index]
            if not isinstance(message, dict):
                continue
            role = _technical(message.get("role"))
            if role is None:
                continue
            claims = []
            for ordinal, raw_claim in enumerate(raw_block.get("claims") or []):
                claim_id = _technical(raw_claim.get("claim_id"))
                evaluation_id = _technical(raw_claim.get("compiler_evaluation_id"))
                if claim_id and evaluation_id:
                    claims.append(ContextClaim(claim_id, evaluation_id, ordinal))
            if not claims:
                continue
            block_id = new_id()
            prepared.append(ContextBlock(
                context_block_id=block_id,
                message_index=index,
                block_role=role,
                message_ref=message,
                content_ref=message.get("content"),
                claims=tuple(claims),
            ))
            manifest_blocks.append({
                "context_block_id": block_id,
                "message_index": index,
                "block_role": role,
                "claims": [{
                    "claim_id": claim.claim_id,
                    "compiler_evaluation_id": claim.compiler_evaluation_id,
                    "ordinal": claim.ordinal,
                } for claim in claims],
            })
        if not prepared:
            return None
        manifest = {
            "version": 1,
            "trace_id": technical["trace_id"],
            "planner_round_id": technical["planner_round_id"],
            "llm_call_id": technical["llm_call_id"],
            "consumer": technical["consumer"],
            "blocks": manifest_blocks,
        }
        digest = hashlib.sha256(json.dumps(
            manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")).hexdigest()
        return LLMContextSidecar(
            trace_id=technical["trace_id"],
            planner_round_id=technical["planner_round_id"],
            llm_call_id=technical["llm_call_id"],
            consumer=technical["consumer"],
            conversation_id=_technical(conversation_id),
            turn_id=_technical(turn_id),
            messages_ref=messages,
            blocks=tuple(prepared),
            context_manifest_digest=digest,
        )

    @staticmethod
    def _claim_event(sidecar: LLMContextSidecar, block: ContextBlock,
                     claim: ContextClaim, event_kind: str, proof_level: str,
                     *, attempt_id: str | None = None,
                     attempt_no: int | None = None,
                     occurred_at: str | None = None) -> dict:
        event = {
            "trace_id": sidecar.trace_id,
            "event_kind": event_kind,
            "occurred_at": occurred_at or _now(),
            "operation_id": sidecar.llm_call_id,
            "turn_id": sidecar.turn_id,
            "planner_round_id": sidecar.planner_round_id,
            "llm_call_id": sidecar.llm_call_id,
            "consumer": sidecar.consumer,
            "compiler_evaluation_id": claim.compiler_evaluation_id,
            "claim_id": claim.claim_id,
            "producer": "llm.context.telemetry",
            "proof_level": proof_level,
            "event_status": "completed",
            "context_block_id": block.context_block_id,
            "context_manifest_digest": sidecar.context_manifest_digest,
            "ordinal": claim.ordinal,
            "details": {
                "message_index": block.message_index,
                "block_role": block.block_role,
                "manifest_claim_count": sum(len(item.claims) for item in sidecar.blocks),
            },
        }
        if attempt_id is not None:
            event.update(attempt_id=attempt_id, attempt_no=attempt_no)
        return event

    def begin_attempt(self, messages, metrics: dict,
                      sidecar: LLMContextSidecar | None = None) -> LLMAttemptObservation | None:
        if not self.enabled:
            return None
        valid_sidecar = (
            isinstance(sidecar, LLMContextSidecar)
            and sidecar.llm_call_id == metrics.get("llm_call_id")
            and sidecar.trace_id == metrics.get("trace_id")
            and sidecar.consumer == metrics.get("role")
            and sidecar.validates(messages)
        )
        sidecar = sidecar if valid_sidecar else None
        trace_id = sidecar.trace_id if sidecar else _technical(metrics.get("trace_id")) or new_id()
        observation = LLMAttemptObservation(
            trace_id=trace_id,
            conversation_id=sidecar.conversation_id if sidecar else None,
            sidecar=sidecar,
            messages_ref=messages if isinstance(messages, list) else None,
            metrics=metrics,
        )
        if sidecar is None:
            return observation
        with sidecar.lock:
            if not sidecar.assembly_emitted:
                for block in sidecar.blocks:
                    for claim in block.claims:
                        observation.events.append(self._claim_event(
                            sidecar, block, claim,
                            "claim_added_to_prompt_context", "assembled_context",
                            occurred_at=sidecar.assembled_at,
                        ))
                sidecar.assembly_emitted = True
        for block in sidecar.blocks:
            for claim in block.claims:
                observation.events.append(self._claim_event(
                    sidecar, block, claim,
                    "claim_received_by_llm_client", "client_boundary",
                    attempt_id=metrics["attempt_id"], attempt_no=metrics["attempt_no"],
                ))
        return observation

    def serialized(self, observation: LLMAttemptObservation | None, messages) -> None:
        if observation is None:
            return
        sidecar = observation.sidecar
        if sidecar is None or not sidecar.validates(messages):
            return
        metrics = observation.metrics
        for block in sidecar.blocks:
            for claim in block.claims:
                observation.events.append(self._claim_event(
                    sidecar, block, claim,
                    "claim_serialized_for_transport", "transport_payload",
                    attempt_id=metrics["attempt_id"], attempt_no=metrics["attempt_no"],
                ))

    @staticmethod
    def _transport_event(observation: LLMAttemptObservation, metrics: dict) -> dict:
        success = metrics.get("status") == "success"
        cancelled = metrics.get("status") == "cancelled"
        response_received = bool(metrics.get("response_received"))
        http_result = metrics.get("http_status") is not None
        kind = "llm_transport_result" if success or response_received or http_result else "transport_failed"
        status = "completed" if success else "cancelled" if cancelled else "failed"
        outcome = "success" if success else "cancelled" if cancelled else "error"
        details = {}
        for key in (
            "http_status", "prompt_tokens", "completion_tokens", "total_tokens",
            "ttft_ms", "duration_ms", "streaming",
        ):
            value = metrics.get(key)
            if value is not None and isinstance(value, (str, int, float, bool)):
                details[key] = value
        for key in ("model", "finish_reason", "error_class"):
            value = _technical(metrics.get(key))
            if value is not None:
                details[key] = value
        details["metrics"] = {
            "serialized": bool(metrics.get("serialized")),
            "transport_started": bool(metrics.get("transport_started")),
            "response_received": bool(metrics.get("response_received")),
            "timed_out": bool(metrics.get("timed_out")),
            "cancelled": bool(metrics.get("cancelled")),
        }
        event = {
            "trace_id": observation.trace_id,
            "event_kind": kind,
            "occurred_at": _now(),
            "operation_id": metrics["llm_call_id"],
            "turn_id": _technical(metrics.get("turn_id")),
            "planner_round_id": _technical(metrics.get("planner_round_id")),
            "llm_call_id": metrics["llm_call_id"],
            "attempt_id": metrics["attempt_id"],
            "attempt_no": metrics["attempt_no"],
            "consumer": _technical(metrics.get("role")),
            "producer": "llm.transport.telemetry",
            "proof_level": "transport_result",
            "event_status": status,
            "outcome_status": outcome,
            "details": details,
        }
        return event

    def finish_attempt(self, observation: LLMAttemptObservation | None, metrics: dict) -> None:
        if observation is None:
            return
        try:
            observation.events.append(self._transport_event(observation, metrics))
            self.recorder.record_trace_events(
                observation.events,
                trace_id=observation.trace_id,
                conversation_id=observation.conversation_id,
                best_effort=True,
            )
        except Exception as exc:
            diagnose = getattr(self.recorder, "_diagnose", None)
            if callable(diagnose):
                diagnose("llm_context_telemetry", exc)
