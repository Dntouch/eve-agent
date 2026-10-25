"""Optional observation of real Memory-v2 retrieval boundaries."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .provenance import new_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MemoryRuntimeOperation:
    recorder: object
    trace_id: str
    operation_id: str
    compiler_evaluation_id: str
    consumer: str
    producer: str
    query_kind: str
    conversation_id: str | None = None
    turn_id: str | None = None
    planner_round_id: str | None = None
    started_at: str = field(default_factory=_now)
    events: list[dict] = field(default_factory=list)
    flushed: bool = False

    def _base(self, event_kind: str, proof_level: str, event_status: str,
              *, occurred_at: str | None = None) -> dict:
        return {
            "trace_id": self.trace_id,
            "event_kind": event_kind,
            "occurred_at": occurred_at or _now(),
            "operation_id": self.operation_id,
            "turn_id": self.turn_id,
            "planner_round_id": self.planner_round_id,
            "consumer": self.consumer,
            "producer": self.producer,
            "proof_level": proof_level,
            "event_status": event_status,
            "details": {"batch_size": len(self.events) + 1},
        }

    def start(self) -> None:
        self.events.extend((
            self._base("operation_started", "operation_boundary", "started",
                       occurred_at=self.started_at),
            {
                **self._base("claim_query_started", "operation_boundary", "started",
                             occurred_at=self.started_at),
                "details": {"query_kind": self.query_kind},
            },
        ))

    def compiler_claim(self, kind: str, claim_id: str, *, method: str,
                       requirement: str, token_cost: int, rank_score: float,
                       ordinal: int | None = None) -> None:
        event = {
            **self._base(kind, "compiler_evaluation", "completed"),
            "compiler_evaluation_id": self.compiler_evaluation_id,
            "claim_id": claim_id,
            "details": {
                "retrieval_method": method or "none",
                "token_cost": int(token_cost),
                "rank_score": float(rank_score),
                "requirement_class": requirement or "optional",
            },
        }
        if ordinal is not None:
            event["ordinal"] = ordinal
        self.events.append(event)

    def relation(self, relation_id: str, *, ordinal: int) -> None:
        self.events.append({
            **self._base("relation_traversed_for_retrieval", "relation_traversal", "completed"),
            "compiler_evaluation_id": self.compiler_evaluation_id,
            "relation_id": relation_id,
            "ordinal": ordinal,
        })

    def returned(self, claim_id: str, *, ordinal: int, method: str = "compiled_view") -> None:
        self.events.append({
            **self._base("claim_returned_to_consumer", "consumer_boundary", "completed"),
            "compiler_evaluation_id": self.compiler_evaluation_id,
            "claim_id": claim_id,
            "ordinal": ordinal,
            "details": {"retrieval_method": method},
        })

    def resolved(self, claim_id: str, *, kind: str = "claim_resolved",
                 result_count: int | None = None) -> None:
        details = {"query_kind": self.query_kind}
        if result_count is not None:
            details["result_count"] = int(result_count)
        self.events.append({
            **self._base(kind, "deterministic_resolution", "completed"),
            "claim_id": claim_id,
            "details": details,
        })

    def complete(self, *, result_count: int) -> None:
        self.events.append({
            **self._base("operation_completed", "operation_boundary", "completed"),
            "outcome_status": "success",
            "details": {},
        })
        self.flush()

    def abort(self, exc: BaseException, *, cancelled: bool = False) -> None:
        self.events.append({
            **self._base(
                "operation_aborted", "operation_boundary",
                "cancelled" if cancelled else "failed",
            ),
            "outcome_status": "cancelled" if cancelled else "failed",
            "details": {"error_class": type(exc).__name__},
        })
        self.flush()

    def flush(self) -> None:
        if self.flushed:
            return
        self.flushed = True
        try:
            self.recorder.record_trace_events(
                self.events, trace_id=self.trace_id, conversation_id=self.conversation_id,
                started_at=self.started_at, best_effort=True,
            )
        except Exception as exc:  # An optional observer never owns runtime success.
            diagnose = getattr(self.recorder, "_diagnose", None)
            if diagnose is not None:
                diagnose("record_trace_events", exc)


class MemoryRetrievalTelemetry:
    """Creates causal sidecars without querying or changing Memory selection."""

    def __init__(self, recorder):
        self.recorder = recorder

    @property
    def enabled(self) -> bool:
        return bool(self.recorder.enabled)

    def begin(self, *, consumer: str, producer: str, query_kind: str,
              trace_id: str | None = None, turn_id: str | None = None,
              planner_round_id: str | None = None,
              conversation_id: str | None = None) -> MemoryRuntimeOperation | None:
        if not self.enabled:
            return None
        operation = MemoryRuntimeOperation(
            recorder=self.recorder,
            trace_id=str(trace_id or new_id()), operation_id=new_id(),
            compiler_evaluation_id=new_id(), consumer=str(consumer),
            producer=str(producer), query_kind=str(query_kind),
            conversation_id=conversation_id, turn_id=turn_id,
            planner_round_id=planner_round_id,
        )
        operation.start()
        return operation

    def diagnostics(self) -> list[dict]:
        return self.recorder.diagnostics()
