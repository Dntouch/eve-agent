"""Technical causal identities carried beside runtime payloads.

The sidecars in this module deliberately contain identifiers only.  They are
never serialized into model messages or provider request bodies and do not
authorize any runtime decision.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re
import uuid


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,255}$")


def _identifier(value: str, field: str) -> str:
    value = str(value)
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid technical provenance identifier: {field}")
    return value


def new_id() -> str:
    """Return one opaque identifier compatible with the Phase-5B contract."""
    return uuid.uuid4().hex


@dataclass(frozen=True)
class PlanningProvenance:
    """Stable identity for one actual runtime decision round."""

    trace_id: str
    planner_round_id: str

    def __post_init__(self) -> None:
        _identifier(self.trace_id, "trace_id")
        _identifier(self.planner_round_id, "planner_round_id")

    @classmethod
    def create(cls, trace_id: str) -> "PlanningProvenance":
        return cls(trace_id=_identifier(trace_id, "trace_id"), planner_round_id=new_id())

    def as_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "planner_round_id": self.planner_round_id,
        }

    def create_plan(self, action_count: int) -> "PlanProvenance":
        if type(action_count) is not int or action_count < 0:
            raise ValueError("Invalid provenance action count")
        plan_id = new_id()
        return PlanProvenance(
            trace_id=self.trace_id,
            planner_round_id=self.planner_round_id,
            plan_id=plan_id,
            actions=tuple(
                ActionProvenance(
                    trace_id=self.trace_id,
                    planner_round_id=self.planner_round_id,
                    plan_id=plan_id,
                    action_id=new_id(),
                    action_index=index,
                )
                for index in range(action_count)
            ),
        )


@dataclass(frozen=True)
class ActionProvenance:
    """Stable identity of one concrete action inside a structured plan."""

    trace_id: str
    planner_round_id: str
    plan_id: str
    action_id: str
    action_index: int
    tool_event_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("trace_id", "planner_round_id", "plan_id", "action_id"):
            _identifier(getattr(self, field), field)
        if type(self.action_index) is not int or self.action_index < 0:
            raise ValueError("Invalid provenance action index")
        if self.tool_event_id is not None:
            _identifier(self.tool_event_id, "tool_event_id")

    def as_dict(self) -> dict:
        result = {
            "trace_id": self.trace_id,
            "planner_round_id": self.planner_round_id,
            "plan_id": self.plan_id,
            "action_id": self.action_id,
            "action_index": self.action_index,
        }
        if self.tool_event_id is not None:
            result["tool_event_id"] = self.tool_event_id
        return result


@dataclass(frozen=True)
class PlanProvenance:
    """Identity sidecar for a plan and its positionally bound actions."""

    trace_id: str
    planner_round_id: str
    plan_id: str
    actions: tuple[ActionProvenance, ...]
    tool_event_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("trace_id", "planner_round_id", "plan_id"):
            _identifier(getattr(self, field), field)
        if self.tool_event_id is not None:
            _identifier(self.tool_event_id, "tool_event_id")
        if any(action.action_index != index for index, action in enumerate(self.actions)):
            raise ValueError("Plan provenance actions are not positionally bound")
        if any(
            action.trace_id != self.trace_id
            or action.planner_round_id != self.planner_round_id
            or action.plan_id != self.plan_id
            for action in self.actions
        ):
            raise ValueError("Action provenance belongs to a different plan")

    def reserve_tool_event(self, tool_event_id: str | None = None) -> "PlanProvenance":
        reserved = _identifier(tool_event_id or new_id(), "tool_event_id")
        if self.tool_event_id is not None and self.tool_event_id != reserved:
            raise ValueError("Tool event identity is already reserved")
        return replace(
            self,
            tool_event_id=reserved,
            actions=tuple(replace(action, tool_event_id=reserved) for action in self.actions),
        )

    def action(self, action_index: int) -> ActionProvenance:
        if type(action_index) is not int or not 0 <= action_index < len(self.actions):
            raise ValueError("Action provenance index is out of range")
        return self.actions[action_index]

    def validate_action_count(self, action_count: int) -> None:
        if action_count != len(self.actions):
            raise ValueError("Plan provenance does not match the action batch")

    def as_dict(self) -> dict:
        result = {
            "trace_id": self.trace_id,
            "planner_round_id": self.planner_round_id,
            "plan_id": self.plan_id,
            "actions": [action.as_dict() for action in self.actions],
        }
        if self.tool_event_id is not None:
            result["tool_event_id"] = self.tool_event_id
        return result
