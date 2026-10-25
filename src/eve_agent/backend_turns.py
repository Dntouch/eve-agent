from __future__ import annotations

import copy
import threading
import time
import uuid

from .turn_failures import failure_report
from .answer_stream import AnswerStreamMismatchError
from .memory import redact_sensitive
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor


class TurnCancelled(RuntimeError):
    pass


class TurnCancellation:
    def __init__(self, store, turn_id: str):
        self.store, self.turn_id = store, turn_id

    def checkpoint(self) -> None:
        self.store.checkpoint(self.turn_id)

    def begin_commit(self) -> None:
        self.store.begin_commit(self.turn_id)


class BackendTurnStore:
    """Small bounded owner for local turns whose lifetime exceeds HTTP observers."""

    TERMINAL = {"completed", "failed", "cancelled"}

    def __init__(self, runner, *, limit: int = 20, max_workers: int = 1):
        self.runner = runner
        self.limit = limit
        self._lock = threading.Condition(threading.RLock())
        self._turns: OrderedDict[str, dict] = OrderedDict()
        self._cancel_events: dict[str, threading.Event] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="eve-turn")

    def start(self, text: str, images: list[str], conversation_id: str | None, *, retry_context=None) -> dict:
        return self.start_task(
            conversation_id,
            lambda turn_id, store: self.runner(turn_id, text, list(images), conversation_id, store),
            input_text=text, retry_context=retry_context,
        )

    def start_task(self, conversation_id: str | None, task, *, input_text: str | None = None, retry_context=None) -> dict:
        turn_id = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._turns[turn_id] = {
                "turn_id": turn_id, "conversation_id": conversation_id,
                "status": "queued", "answer": "", "answer_preview": "",
                "answer_preview_generation": 0,
                "reasoning": "", "response": None,
                "transcript": None,
                "input_text": input_text, "retry_context": copy.deepcopy(retry_context),
                "error": None, "created_at": now, "started_at": None,
                "completed_at": None, "version": 1,
                "answer_committed_at": None,
                "cancel_requested": False, "cancel_requested_at": None,
                "cancellable": True, "committing": False,
                "audio_segments": [],
            }
            self._cancel_events[turn_id] = threading.Event()
            self._trim_locked()
        self._executor.submit(self._run_task, turn_id, task)
        return self.snapshot(turn_id)

    def _run_task(self, turn_id: str, task) -> None:
        self.update(turn_id, status="running", started_at=time.time())
        try:
            task(turn_id, self)
        except TurnCancelled:
            self.finish_cancelled(turn_id)
        except Exception as exc:
            if self.cancel_requested(turn_id):
                self.finish_cancelled(turn_id)
                return
            self.clear_answer_preview(turn_id)
            self.update(
                turn_id, status="failed", error=redact_sensitive(str(exc)), completed_at=time.time(),
                failure_report=getattr(exc, "turn_failure_report", None) or failure_report(
                    exc, turn_id=turn_id, input_text=self.snapshot(turn_id).get("input_text"),
                    conversation_id=self.snapshot(turn_id).get("conversation_id")),
            )

    def checkpoint(self, turn_id: str) -> None:
        if self.cancel_requested(turn_id):
            raise TurnCancelled("Turn wurde abgebrochen")

    def cancellation(self, turn_id: str) -> TurnCancellation:
        return TurnCancellation(self, turn_id)

    def cancel_requested(self, turn_id: str) -> bool:
        with self._lock:
            event = self._cancel_events.get(turn_id)
            return bool(event and event.is_set())

    def cancel(self, turn_id: str) -> dict:
        with self._lock:
            if turn_id not in self._turns:
                raise KeyError("Backend-Turn wurde nicht gefunden")
            turn = self._turns[turn_id]
            if turn["status"] in self.TERMINAL or not turn.get("cancellable", True):
                return copy.deepcopy(turn)
            if not turn["cancel_requested"]:
                turn["cancel_requested"] = True
                turn["cancel_requested_at"] = time.time()
                self._cancel_events[turn_id].set()
                turn["version"] += 1
                self._lock.notify_all()
            return copy.deepcopy(turn)

    def begin_commit(self, turn_id: str) -> None:
        """Atomically choose cancellation or the irreversible persistence path."""
        with self._lock:
            turn = self._turns[turn_id]
            if turn["cancel_requested"]:
                raise TurnCancelled("Turn wurde vor Persistenz abgebrochen")
            turn["committing"] = True
            turn["cancellable"] = False
            turn["version"] += 1
            self._lock.notify_all()

    def finish_cancelled(self, turn_id: str) -> dict:
        with self._lock:
            turn = self._turns[turn_id]
            if turn["status"] not in self.TERMINAL:
                turn.update(
                    status="cancelled", cancellable=False, completed_at=time.time(),
                    answer_preview="",
                    answer_preview_generation=turn.get("answer_preview_generation", 0) + 1,
                )
                turn["version"] += 1
                self._lock.notify_all()
            return copy.deepcopy(turn)

    def append(self, turn_id: str, content: str) -> None:
        if not content:
            return
        with self._lock:
            turn = self._turns[turn_id]
            if turn["answer_committed_at"] is None:
                turn["answer_committed_at"] = time.time()
            turn["answer"] += content
            turn["version"] += 1
            self._lock.notify_all()

    def append_answer_preview(self, turn_id: str, content: str) -> None:
        """Publish reversible model text before a native tool choice is final."""
        if not content:
            return
        with self._lock:
            turn = self._turns[turn_id]
            turn["answer_preview"] += content
            turn["version"] += 1
            self._lock.notify_all()

    def clear_answer_preview(self, turn_id: str) -> None:
        """Retract a candidate when the model chooses a tool or the call fails."""
        with self._lock:
            turn = self._turns[turn_id]
            if not turn.get("answer_preview"):
                return
            turn["answer_preview"] = ""
            turn["answer_preview_generation"] = turn.get("answer_preview_generation", 0) + 1
            turn["version"] += 1
            self._lock.notify_all()

    def append_reasoning(self, turn_id: str, content: str) -> None:
        """Publish transient provider reasoning without persisting it as chat content."""
        if not content:
            return
        with self._lock:
            turn = self._turns[turn_id]
            turn["reasoning"] += content
            turn["version"] += 1
            self._lock.notify_all()

    def set_response(self, turn_id: str, response: dict) -> None:
        """Attach a final response without replacing an already published answer."""
        with self._lock:
            turn = self._turns[turn_id]
            final_answer = str(response.get("answer", ""))
            if turn["answer"] and turn["answer"] != final_answer:
                raise AnswerStreamMismatchError(turn["answer"], final_answer)
            if not turn["answer"]:
                turn["answer"] = final_answer
            turn["response"] = response
            turn["version"] += 1
            self._lock.notify_all()

    def publish_audio(self, turn_id: str, text: str, audio_wav_base64: str) -> None:
        with self._lock:
            turn = self._turns[turn_id]
            if turn["cancel_requested"] or turn["status"] in self.TERMINAL:
                return
            turn["audio_segments"].append({
                "sequence": len(turn["audio_segments"]),
                "text": text, "audio_wav_base64": audio_wav_base64,
            })
            turn["version"] += 1
            self._lock.notify_all()

    def update(self, turn_id: str, **changes) -> None:
        with self._lock:
            turn = self._turns[turn_id]
            turn.update(changes)
            turn["version"] += 1
            self._lock.notify_all()

    def active_for_conversation(self, conversation_id: str) -> str | None:
        with self._lock:
            return next((turn["turn_id"] for turn in reversed(self._turns.values())
                         if turn["conversation_id"] == conversation_id
                         and turn["status"] not in self.TERMINAL), None)

    def snapshot(self, turn_id: str) -> dict:
        with self._lock:
            if turn_id not in self._turns:
                raise KeyError("Backend-Turn wurde nicht gefunden")
            return copy.deepcopy(self._turns[turn_id])

    def wait(self, turn_id: str, after_version: int, timeout: float = 15.0) -> dict:
        with self._lock:
            if turn_id not in self._turns:
                raise KeyError("Backend-Turn wurde nicht gefunden")
            self._lock.wait_for(
                lambda: self._turns[turn_id]["version"] > after_version,
                timeout=timeout,
            )
            return copy.deepcopy(self._turns[turn_id])

    def _trim_locked(self) -> None:
        while len(self._turns) > self.limit:
            key, value = next(iter(self._turns.items()))
            if value["status"] not in self.TERMINAL:
                break
            self._turns.pop(key)
            self._cancel_events.pop(key, None)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)
