from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone

from .shadow_learning import ShadowLearningCancelled


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ConversationLearningCoordinator:
    """Run durable conversation learning in cancellable idle-time batches."""

    def __init__(self, database, pipeline, config: dict, diagnostics=None, *, autostart: bool = True):
        self.database = database
        self.pipeline = pipeline
        self.diagnostics = diagnostics
        self._condition = threading.Condition(threading.RLock())
        self._closed = False
        self._active = False
        self._force_run = False
        self._last_activity_monotonic = time.monotonic()
        self._thread: threading.Thread | None = None
        self.enabled = True
        self.idle_delay_seconds = 120
        self.batch_size = 2
        # A terminated process may leave an inference marked running. Its
        # semantic output was never committed, so the durable job is resumable.
        self.pipeline.pending_turns()
        self.configure(config, wake=False)
        if autostart:
            self._thread = threading.Thread(
                target=self._run, name="eve-conversation-learning", daemon=True,
            )
            self._thread.start()

    def configure(self, config: dict, *, wake: bool = True) -> dict:
        with self._condition:
            self.enabled = bool(config.get("enabled", True))
            self.idle_delay_seconds = max(5, int(config.get("idle_delay_seconds", 120)))
            self.batch_size = min(32, max(1, int(config.get("batch_size", 2))))
            if not self.enabled and self._active:
                self.pipeline.prioritize_interactive_turn()
            row = self._runtime_row()
            paused = bool(row["pause_requested"])
            state = "disabled" if not self.enabled else "paused" if paused else "waiting"
            self._persist_state(state)
            if wake:
                self._condition.notify_all()
        return self.status()

    def accept_turn(self, turn_id: str) -> dict:
        job = self.pipeline.accept_turn(turn_id)
        self.note_activity()
        return job

    def note_activity(self) -> None:
        with self._condition:
            self._last_activity_monotonic = time.monotonic()
            self._force_run = False
            if self._active:
                self.pipeline.prioritize_interactive_turn()
            row = self._runtime_row()
            state = "disabled" if not self.enabled else "paused" if row["pause_requested"] else "waiting"
            self._persist_state(state, last_activity_at=_now())
            self._condition.notify_all()

    def pause(self) -> dict:
        with self._condition:
            self._force_run = False
            if self._active:
                self.pipeline.prioritize_interactive_turn()
            self._persist_state("paused", pause_requested=1)
            self._condition.notify_all()
        return self.status()

    def resume(self, *, run_now: bool = False) -> dict:
        with self._condition:
            self._force_run = bool(run_now)
            if run_now:
                self._last_activity_monotonic = time.monotonic() - self.idle_delay_seconds
            self._persist_state("waiting", pause_requested=0, last_error=None)
            self._condition.notify_all()
        return self.status()

    def run_now(self) -> dict:
        return self.resume(run_now=True)

    def retry_failed(self) -> dict:
        amount = self.pipeline.retry_failed()
        status = self.resume(run_now=True)
        return {**status, "requeued_failed": amount}

    def status(self) -> dict:
        row = self._runtime_row()
        counts = self.pipeline.job_counts()
        outcomes = self.pipeline.productive_outcome_counts()
        return {
            "status": str(row["status"]),
            "pause_requested": bool(row["pause_requested"]),
            "current_batch": json.loads(row["current_batch_json"] or "[]"),
            "last_activity_at": row["last_activity_at"],
            "last_started_at": row["last_started_at"],
            "last_completed_at": row["last_completed_at"],
            "last_error": row["last_error"],
            "updated_at": row["updated_at"],
            "enabled": self.enabled,
            "idle_delay_seconds": self.idle_delay_seconds,
            "batch_size": self.batch_size,
            "jobs": counts,
            "pending": int(counts.get("pending", 0)),
            "running": int(counts.get("running", 0)),
            "learned": outcomes["evidenced_turns"],
            "applied": outcomes["applied_turns"],
            "applied_without_evidence": outcomes["applied_without_evidence"],
            "evidence_records": outcomes["evidence_records"],
            "evidenced_claims": outcomes["evidenced_claims"],
            "discarded": int(counts.get("no_persist", 0)),
            "failed": int(counts.get("failed", 0)),
            "reviewed": int(counts.get("reviewed", 0)),
        }

    def jobs(self, status: str, *, limit: int = 40, offset: int = 0) -> dict:
        return self.pipeline.learning_jobs(status, limit=limit, offset=offset)

    def close(self) -> None:
        with self._condition:
            self._closed = True
            if self._active:
                self.pipeline.prioritize_interactive_turn()
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while True:
            with self._condition:
                if self._closed:
                    return
                row = self._runtime_row()
                if not self.enabled:
                    self._persist_state("disabled")
                    self._condition.wait()
                    continue
                if row["pause_requested"]:
                    self._persist_state("paused")
                    self._condition.wait()
                    continue
                if row["status"] == "failed" and row["last_error"] and not self._force_run:
                    # A deterministic preparation or provider error cannot heal
                    # through a tight retry loop. Keep the failure visible and
                    # wait for an explicit retry/resume or a process restart.
                    self._persist_state("failed", current_batch=[])
                    self._condition.wait()
                    continue
                turn_ids = self.pipeline.queued_turns(self.batch_size)
                if not turn_ids:
                    # Historical failed jobs remain visible and manually
                    # retryable, but do not make an otherwise idle scheduler
                    # look as though its current run had just failed.
                    state = "completed"
                    self._persist_state(state, current_batch=[])
                    self._condition.wait()
                    continue
                remaining = (
                    0.0 if self._force_run
                    else self.idle_delay_seconds - (time.monotonic() - self._last_activity_monotonic)
                )
                if remaining > 0:
                    self._persist_state("waiting", current_batch=[])
                    self._condition.wait(timeout=remaining)
                    continue
                self._force_run = False
                self._active = True
                self._persist_state(
                    "running", current_batch=turn_ids, last_started_at=_now(),
                )
            error = None
            validation_error = None
            paused = False
            try:
                results = []
                for turn_id in turn_ids:
                    with self._condition:
                        if self._closed or not self.enabled or self._runtime_row()['pause_requested']:
                            raise ShadowLearningCancelled('learning_paused_between_turns')
                        if time.monotonic() - self._last_activity_monotonic < self.idle_delay_seconds:
                            raise ShadowLearningCancelled('interactive_activity_between_turns')
                    # Each completed turn is validated and committed before the
                    # next inference. A cancellation cannot discard earlier work.
                    results.extend(self.pipeline.process_batch([turn_id]))
                failures = [item for item in results if item.get("application_status") == "failed"]
                if failures:
                    validation_error = failures[0].get("reason_code") or "learning_proposal_rejected"
            except ShadowLearningCancelled:
                paused = True
            except Exception as exc:  # the job rows retain the exact error class
                error = type(exc).__name__
                self._diagnostic(exc)
            finally:
                with self._condition:
                    self._active = False
                    runtime = self._runtime_row()
                    if runtime["pause_requested"]:
                        state = "paused"
                    elif error:
                        state = "failed"
                    elif paused:
                        state = "waiting"
                    else:
                        state = "completed"
                    changes = {"current_batch": []}
                    if not paused:
                        changes["last_error"] = error or validation_error
                    if not paused and not error:
                        changes["last_completed_at"] = _now()
                    self._persist_state(state, **changes)
                    self._condition.notify_all()

    def _runtime_row(self):
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_learning_runtime WHERE singleton=1"
            ).fetchone()
        if row is None:
            raise RuntimeError("Conversation-Learning-Laufzeitstatus fehlt")
        return row

    def _persist_state(self, status: str, **changes) -> None:
        allowed = {
            "pause_requested", "current_batch", "last_activity_at", "last_started_at",
            "last_completed_at", "last_error",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Unbekannter Learning-Statuswert: {sorted(unknown)[0]}")
        assignments = ["status=?", "updated_at=?"]
        values: list[object] = [status, _now()]
        for key, value in changes.items():
            column = "current_batch_json" if key == "current_batch" else key
            assignments.append(f"{column}=?")
            values.append(json.dumps(value, ensure_ascii=False) if key == "current_batch" else value)
        values.append(1)
        with self.database.connect() as connection:
            connection.execute(
                f"UPDATE conversation_learning_runtime SET {','.join(assignments)} WHERE singleton=?",
                values,
            )

    def _diagnostic(self, exc: Exception) -> None:
        if self.diagnostics is None:
            return
        try:
            self.diagnostics.record(
                "conversation_learning", "idle_batch", "error",
                "Gebündeltes Gesprächslernen ist fehlgeschlagen.", exception=exc,
            )
        except (OSError, ValueError):
            pass
