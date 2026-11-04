"""Content-free runtime events for optional transport activity reporting."""
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from typing import Any

from .transport_access import report_transport_activity


def report_runtime_activity(kind: str, **fields: object) -> None:
    # Optional telemetry must never affect model/tool results or cancellation.
    with suppress(Exception):
        report_transport_activity({"kind": kind, **fields})


@contextmanager
def tool_activity(capability: str) -> Iterator[None]:
    identifier = uuid.uuid4().hex
    report_runtime_activity("tool_start", tool_id=identifier, web=capability == "web")
    try:
        yield
    finally:
        report_runtime_activity("tool_end", tool_id=identifier)


class BotActivity:
    """One request; real overlapping tools take precedence over the model phase."""
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.tools: dict[str, bool] = {}
        self.phase = "THINKING"

    def update(self, event: dict[str, Any]) -> str:
        with self.lock:
            kind = event.get("kind")
            if kind == "model_start":
                self.phase = "THINKING"
            elif kind == "model_writing":
                self.phase = "WRITING"
            elif kind == "tool_start":
                self.tools[event["tool_id"]] = bool(event.get("web"))
                self.phase = "THINKING"
            elif kind == "tool_end":
                self.tools.pop(event["tool_id"], None)
            return ("WEB_RESEARCH" if any(self.tools.values()) else "TOOL_USE" if self.tools else self.phase)
