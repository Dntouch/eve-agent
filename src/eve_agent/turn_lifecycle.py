from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from typing import Any


class TurnCompletionStore:
    """Bounded correlation store for post-response presentation and audio results."""

    def __init__(self, limit: int = 20):
        self._lock = threading.RLock()
        self._limit = max(1, int(limit))
        self._items: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def register(self, turn_id: str, conversation_id: str | None, *, presentation: bool, audio: bool) -> None:
        with self._lock:
            self._items[turn_id] = {
                "turn_id": turn_id,
                "conversation_id": conversation_id,
                "status": "pending",
                "presentation": {"status": "pending" if presentation else "skipped"},
                "audio": {"status": "pending" if audio else "skipped"},
                "created_at": time.time(),
            }
            self._items.move_to_end(turn_id)
            while len(self._items) > self._limit:
                self._items.popitem(last=False)

    def update(self, turn_id: str, component: str, result: dict[str, Any]) -> bool:
        """Store one result and report whether this update completed the turn."""
        if component not in {"presentation", "audio"}:
            raise ValueError("Unbekannte Turn-Komponente")
        with self._lock:
            item = self._items.get(turn_id)
            if item is None:
                return False
            was_complete = item.get("status") == "complete"
            item[component] = copy.deepcopy(result)
            self._finish_if_ready(item)
            return not was_complete and item.get("status") == "complete"

    def get(self, turn_id: str) -> dict[str, Any]:
        with self._lock:
            if turn_id not in self._items:
                raise KeyError("Turn-Ergebnis wurde nicht gefunden")
            return copy.deepcopy(self._items[turn_id])

    @staticmethod
    def _finish_if_ready(item: dict[str, Any]) -> None:
        terminal = {"success", "error", "stale", "skipped"}
        if all(item[name].get("status") in terminal for name in ("presentation", "audio")):
            item["status"] = "complete"
            item["completed_at"] = time.time()
