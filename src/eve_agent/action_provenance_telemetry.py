"""Optional action telemetry for explicitly transported Memory-v2 identities."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .provenance import PlanProvenance, new_id


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,255}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(value) -> str | None:
    text = str(value or "")
    return text if _IDENTIFIER.fullmatch(text) else None


@dataclass(frozen=True)
class ActionClaimBinding:
    claim_id: str
    action_indexes: tuple[int, ...]
    source: str


@dataclass(frozen=True)
class ActionRelationBinding:
    relation_id: str
    source: str


@dataclass
class ActionMemorySidecar:
    provenance: PlanProvenance
    provider: str
    targets: tuple[str | None, ...]
    operations: tuple[str, ...]
    services: tuple[str | None, ...]
    claims: tuple[ActionClaimBinding, ...]
    relations: tuple[ActionRelationBinding, ...]
    trace_id: str
    turn_id: str | None = None
    conversation_id: str | None = None
    tool_event_id: str | None = None
    plan_persisted: bool = False
    attempts: dict[int, tuple[str, int]] = field(default_factory=dict)
    completed: set[tuple[str, int, str]] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def attach_tool_event(self, tool_event_id: str | None) -> None:
        technical = _id(tool_event_id)
        if technical is not None:
            self.tool_event_id = technical

    def claims_for(self, action_index: int) -> tuple[str, ...]:
        return tuple(
            item.claim_id for item in self.claims if action_index in item.action_indexes
        )


class ActionProvenanceTelemetry:
    """Persist short batches at validated plan and real executor boundaries."""

    def __init__(self, recorder):
        self.recorder = recorder

    @property
    def enabled(self) -> bool:
        return bool(getattr(self.recorder, "enabled", False))

    def build(self, *, provenance: PlanProvenance, plan: dict, claims: list[dict] | None,
              relations: list[dict] | None = None,
              provider: str, conversation_id: str | None = None,
              turn_id: str | None = None) -> ActionMemorySidecar | None:
        if not self.enabled or not isinstance(provenance, PlanProvenance):
            return None
        actions = plan.get("actions") if isinstance(plan, dict) else None
        if not isinstance(actions, list):
            return None
        provenance.validate_action_count(len(actions))
        provider_id = _id(provider)
        if provider_id is None:
            return None
        prepared = []
        seen = set()
        for raw in list(claims or []):
            claim_id = _id(raw.get("claim_id")) if isinstance(raw, dict) else None
            source = _id(raw.get("source")) if isinstance(raw, dict) else None
            indexes = raw.get("action_indexes") if isinstance(raw, dict) else None
            if indexes is None:
                indexes = list(range(len(actions)))
            if (
                claim_id is None or source is None or not isinstance(indexes, (list, tuple))
                or claim_id.startswith("composition:")
                or any(type(index) is not int or not 0 <= index < len(actions) for index in indexes)
            ):
                continue
            key = (claim_id, tuple(dict.fromkeys(indexes)))
            if key in seen:
                continue
            seen.add(key)
            prepared.append(ActionClaimBinding(claim_id, key[1], source))
        prepared_relations = []
        seen_relations = set()
        for raw in list(relations or []):
            relation_id = _id(raw.get("relation_id")) if isinstance(raw, dict) else None
            source = _id(raw.get("source")) if isinstance(raw, dict) else None
            if (
                relation_id is None or source is None
                or relation_id.startswith(("composition:", "hypothesis:"))
                or relation_id in seen_relations
            ):
                continue
            seen_relations.add(relation_id)
            prepared_relations.append(ActionRelationBinding(relation_id, source))
        if not prepared and not prepared_relations:
            return None
        targets = tuple(
            _id(action.get("entity_id")) if isinstance(action, dict) else None
            for action in actions
        )
        operations = tuple(
            (_id(action.get("type")) or "unknown") if isinstance(action, dict) else "unknown"
            for action in actions
        )
        services = tuple(
            _id(action.get("service")) if isinstance(action, dict) else None
            for action in actions
        )
        return ActionMemorySidecar(
            provenance=provenance,
            provider=provider_id,
            targets=targets,
            operations=operations,
            services=services,
            claims=tuple(prepared),
            relations=tuple(prepared_relations),
            trace_id=provenance.trace_id,
            turn_id=_id(turn_id),
            conversation_id=_id(conversation_id),
        )

    @staticmethod
    def _base(sidecar: ActionMemorySidecar, event_kind: str, proof: str,
              status: str, *, action_index: int | None = None,
              claim_id: str | None = None) -> dict:
        operation_id = sidecar.provenance.plan_id
        event = {
            "trace_id": sidecar.trace_id,
            "event_kind": event_kind,
            "occurred_at": _now(),
            "operation_id": operation_id,
            "turn_id": sidecar.turn_id,
            "planner_round_id": sidecar.provenance.planner_round_id,
            "plan_id": sidecar.provenance.plan_id,
            "claim_id": claim_id,
            "producer": "home_assistant.action.telemetry",
            "proof_level": proof,
            "event_status": status,
            "details": {},
        }
        if action_index is not None:
            action = sidecar.provenance.action(action_index)
            event.update(
                operation_id=action.action_id,
                action_id=action.action_id,
                action_index=action_index,
                provider=sidecar.provider,
                target_resource_id=sidecar.targets[action_index],
                tool_event_id=sidecar.tool_event_id,
            )
        return event

    def _persist(self, sidecar: ActionMemorySidecar, events: list[dict]) -> None:
        if not events:
            return
        try:
            self.recorder.record_trace_events(
                events,
                trace_id=sidecar.trace_id,
                conversation_id=sidecar.conversation_id,
                best_effort=True,
            )
        except Exception as exc:
            diagnose = getattr(self.recorder, "_diagnose", None)
            if callable(diagnose):
                diagnose("action_provenance_telemetry", exc)

    def plan_validated(self, sidecar: ActionMemorySidecar | None) -> None:
        if sidecar is None:
            return
        with sidecar.lock:
            if sidecar.plan_persisted:
                return
            sidecar.plan_persisted = True
        events = []
        for binding in sidecar.claims:
            events.append(self._base(
                sidecar, "claim_bound_to_plan", "validated_binding", "completed",
                claim_id=binding.claim_id,
            ))
            for action_index in binding.action_indexes:
                target = sidecar.targets[action_index]
                if target is None:
                    continue
                bound = self._base(
                    sidecar, "claim_bound_to_action", "validated_binding", "completed",
                    action_index=action_index, claim_id=binding.claim_id,
                )
                bound["details"] = self._details(sidecar, action_index)
                events.append(bound)
                verified = self._base(
                    sidecar, "claim_technical_verification", "provider_verification",
                    "completed", action_index=action_index, claim_id=binding.claim_id,
                )
                verified["verification_status"] = "verified"
                verified["details"] = self._details(sidecar, action_index)
                events.append(verified)
        for binding in sidecar.relations:
            relation = self._base(
                sidecar, "relation_bound_to_plan", "validated_binding", "completed",
            )
            relation["relation_id"] = binding.relation_id
            events.append(relation)
        self._persist(sidecar, events)

    @staticmethod
    def _details(sidecar: ActionMemorySidecar, action_index: int, **extra) -> dict:
        details = {
            "executor": "home_assistant",
            "operation": sidecar.operations[action_index],
        }
        if sidecar.services[action_index] is not None:
            details["service"] = sidecar.services[action_index]
        details.update({key: value for key, value in extra.items() if value is not None})
        return details

    def dispatch(self, sidecar: ActionMemorySidecar | None, action_index: int) -> str | None:
        if sidecar is None or not sidecar.claims_for(action_index):
            return None
        with sidecar.lock:
            previous = sidecar.attempts.get(action_index)
            attempt_no = previous[1] + 1 if previous else 1
            attempt_id = new_id()
            sidecar.attempts[action_index] = (attempt_id, attempt_no)
        events = []
        for claim_id in sidecar.claims_for(action_index):
            event = self._base(
                sidecar, "action_dispatch_attempted_with_claim", "dispatch_boundary",
                "started", action_index=action_index, claim_id=claim_id,
            )
            event.update(attempt_id=attempt_id, attempt_no=attempt_no)
            event["details"] = self._details(
                sidecar, action_index, dispatch_started=True,
            )
            events.append(event)
        self._persist(sidecar, events)
        return attempt_id

    def provider_response(self, sidecar: ActionMemorySidecar | None, action_index: int,
                          *, outcome: str, status: str, provider_status: str,
                          error_code: str | None = None) -> None:
        if sidecar is None:
            return
        attempt = sidecar.attempts.get(action_index)
        if attempt is None:
            return
        key = ("provider", action_index, attempt[0])
        with sidecar.lock:
            if key in sidecar.completed:
                return
            sidecar.completed.add(key)
        events = []
        for claim_id in sidecar.claims_for(action_index):
            event = self._base(
                sidecar, "action_provider_response_with_claim", "provider_response",
                status, action_index=action_index, claim_id=claim_id,
            )
            event.update(attempt_id=attempt[0], attempt_no=attempt[1], outcome_status=outcome)
            event["details"] = self._details(
                sidecar, action_index, provider_status=_id(provider_status),
                error_code=_id(error_code), dispatch_started=True,
            )
            events.append(event)
        self._persist(sidecar, events)

    def verification(self, sidecar: ActionMemorySidecar | None, action_index: int,
                     *, verification_status: str, status: str = "completed",
                     readback_attempts: int | None = None,
                     target_already_reached: bool | None = None,
                     error_code: str | None = None) -> None:
        if sidecar is None:
            return
        key = ("verification", action_index, verification_status)
        with sidecar.lock:
            if key in sidecar.completed:
                return
            sidecar.completed.add(key)
        events = []
        for claim_id in sidecar.claims_for(action_index):
            event = self._base(
                sidecar, "action_verification_with_claim", "verification_result",
                status, action_index=action_index, claim_id=claim_id,
            )
            event["verification_status"] = verification_status
            event["details"] = self._details(
                sidecar, action_index, readback_attempts=readback_attempts,
                target_already_reached=target_already_reached,
                error_code=_id(error_code),
            )
            events.append(event)
        self._persist(sidecar, events)

    def completed(self, sidecar: ActionMemorySidecar | None, action_index: int,
                  *, outcome: str, status: str, error_code: str | None = None,
                  target_already_reached: bool | None = None,
                  readback_attempts: int | None = None) -> None:
        if sidecar is None:
            return
        key = ("completed", action_index, outcome)
        with sidecar.lock:
            if key in sidecar.completed:
                return
            sidecar.completed.add(key)
        events = []
        for claim_id in sidecar.claims_for(action_index):
            event = self._base(
                sidecar, "action_completed_with_claim", "action_result", status,
                action_index=action_index, claim_id=claim_id,
            )
            event["outcome_status"] = outcome
            event["details"] = self._details(
                sidecar, action_index, error_code=_id(error_code),
                target_already_reached=target_already_reached,
                readback_attempts=readback_attempts,
            )
            events.append(event)
        self._persist(sidecar, events)
