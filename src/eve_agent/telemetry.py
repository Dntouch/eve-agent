from __future__ import annotations

import copy
import contextvars
import re
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from typing import Any

from .memory import redact_sensitive


_SECRET_KEYS = re.compile(r"^(?:token|access_token|api[_-]?key|authorization|password|secret)$", re.I)
_TECHNICAL_ID_KEYS = frozenset({
    "trace_id", "turn_id", "planner_round_id", "plan_id", "action_id",
    "tool_event_id", "llm_call_id", "attempt_id", "request_id",
})
_TECHNICAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._/@+-]{0,255}$")


def _safe(value: Any, *, key: str = "") -> Any:
    if _SECRET_KEYS.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _safe(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, str):
        if key in _TECHNICAL_ID_KEYS and _TECHNICAL_ID.fullmatch(value):
            return value
        return redact_sensitive(value)[:20_000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_sensitive(str(value))[:2_000]


class TurnTelemetry:
    """Bounded, passive turn traces. No trace data is consumed by EVE's logic."""

    def __init__(self, limit: int = 100):
        self._lock = threading.RLock()
        self._turns: deque[dict] = deque(maxlen=limit)
        self._active: dict[str, dict] = {}
        self._current_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            "eve_telemetry_turn_id", default=None,
        )

    def start(
        self, *, conversation_id: str | None, input_kind: str, turn_id: str | None = None,
        new_turn: bool = False,
    ) -> str:
        with self._lock:
            current_id = self._current_id.get()
            # Nested instrumentation joins the current request; a new user
            # request must not inherit a trace still awaiting postprocessing.
            if (not new_turn and current_id in self._active
                    and (turn_id is None or turn_id == current_id)):
                return current_id
            now = time.time()
            turn_id = turn_id or uuid.uuid4().hex
            self._active[turn_id] = {
                "id": turn_id,
                "conversation_id": conversation_id,
                "started_at": now,
                "started_monotonic": time.perf_counter(),
                "input_kind": input_kind,
                "status": "running",
                "route": None,
                "confidence": None,
                "model": None,
                "quantization": None,
                "summary": {},
                "steps": [],
                "llm_calls": [],
                "events": [],
            }
            self._current_id.set(turn_id)
            return turn_id

    def active_id(self) -> str | None:
        turn_id = self._current_id.get()
        with self._lock:
            return turn_id if turn_id in self._active else None

    def _current(self) -> dict | None:
        turn_id = self._current_id.get()
        return self._active.get(turn_id) if turn_id else None

    @contextmanager
    def bind(self, turn_id: str):
        """Correlate work in another thread with an existing active turn."""
        token = self._current_id.set(turn_id)
        try:
            yield
        finally:
            self._current_id.reset(token)

    def elapsed_ms(self) -> float | None:
        """Return time since turn start for passive timeline correlation."""
        with self._lock:
            active = self._current()
            if active is None:
                return None
            return (time.perf_counter() - active["started_monotonic"]) * 1000

    def event(
        self,
        component: str,
        operation: str,
        *,
        status: str = "ok",
        duration_ms: float | None = None,
        start_ms: float | None = None,
        details: Any = None,
    ) -> None:
        with self._lock:
            active = self._current()
            if active is None:
                return
            end_ms = (time.perf_counter() - active["started_monotonic"]) * 1000
            item = {
                "component": component,
                "operation": operation,
                "status": status,
                "start_ms": round(
                    start_ms if start_ms is not None else max(0.0, end_ms - (duration_ms or 0.0)),
                    2,
                ),
                "end_ms": round(end_ms, 2),
            }
            if duration_ms is not None:
                item["duration_ms"] = round(duration_ms, 2)
            if details is not None:
                item["details"] = _safe(details)
            active["steps"].append(item)

    def llm_call(self, metrics: dict) -> None:
        with self._lock:
            active = self._current()
            if active is None:
                return
            safe = _safe(metrics)
            if metrics.get("request_id"):
                safe["turn_id"] = active["id"]
            end_ms = (time.perf_counter() - active["started_monotonic"]) * 1000
            duration_ms = float(metrics.get("duration_ms") or 0.0)
            safe.setdefault("start_ms", round(max(0.0, end_ms - duration_ms), 2))
            safe.setdefault("end_ms", round(end_ms, 2))
            active["llm_calls"].append(safe)
            active["model"] = metrics.get("model")
            quantization = re.search(r"(?i)(?:^|[-_.])((?:Q|IQ)\d(?:_[A-Z0-9]+)*)", str(metrics.get("model", "")))
            if quantization:
                active["quantization"] = quantization.group(1).upper()

    def route(self, name: str) -> None:
        with self._lock:
            active = self._current()
            if active:
                active["route"] = name

    def session_lifecycle(self, **details: Any) -> None:
        """Attach passive lifecycle diagnostics to the turn selected by the agent."""
        with self._lock:
            active = self._current()
            if active:
                active["conversation_id"] = details.get("conversation_id")
        self.event("conversation", "lifecycle", details=details)

    def summary(self, **details: Any) -> None:
        with self._lock:
            active = self._current()
            if active:
                active["summary"].update(_safe(details))

    def knowledge_flow(self, flow: dict) -> None:
        """Attach backend-produced provenance facts without interpreting them."""
        with self._lock:
            active = self._current()
            if active:
                active["knowledge_flow"] = _safe(flow)

    def update_llm_call(self, request_id: str, metrics: dict, *, only_success: bool = False) -> None:
        """Update the single existing request record, including post-response validation."""
        with self._lock:
            for turn in [*self._active.values(), *self._turns]:
                for call in turn["llm_calls"]:
                    if call.get("request_id") == request_id:
                        if not only_success or call.get("status") == "success":
                            call.update({k: v for k, v in _safe(metrics).items() if k != "turn_id"})
                        return

    def finish(self, *, status: str = "success", details: dict | None = None) -> None:
        with self._lock:
            turn_id = self._current_id.get()
            turn = self._active.pop(turn_id, None) if turn_id else None
            if turn is None:
                return
            turn["status"] = status
            turn["duration_ms"] = round((time.perf_counter() - turn.pop("started_monotonic")) * 1000, 2)
            if details:
                turn["summary"].update(_safe(details))
            calls = turn["llm_calls"]
            turn["summary"]["llm_requests"] = {
                "started": len(calls),
                "successful": sum(c.get("status", "success") == "success" for c in calls),
                "failed": sum(c.get("status") not in {None, "success", "running", "cancelled"} for c in calls),
                "cancelled": sum(c.get("status") == "cancelled" for c in calls),
                "running": sum(c.get("status") == "running" for c in calls),
            }
            usage = {"prompt_tokens": 0, "completion_tokens": 0}
            for call in turn["llm_calls"]:
                for key in usage:
                    usage[key] += int(call.get(key) or 0)
            turn["summary"]["usage_reported"] = dict(usage)
            for key in usage:
                if any(call.get(key) is None for call in calls):
                    usage[key] = None
            turn["summary"]["usage"] = usage
            self._turns.appendleft(turn)
            self._current_id.set(None)

    def snapshot(self, conversation_id: str | None = None) -> dict:
        with self._lock:
            turns = list(self._turns)
            for active_turn in self._active.values():
                active = copy.deepcopy(active_turn)
                active.pop("started_monotonic", None)
                turns.insert(0, active)
            if conversation_id:
                turns = [turn for turn in turns if turn.get("conversation_id") == conversation_id]
            return {"turns": copy.deepcopy(turns), "observability_only": True}
