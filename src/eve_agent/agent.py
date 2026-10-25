from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import base64
import json
import threading
import time
import uuid
import contextvars
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import datetime
from typing import Any

from .dialog import Route
from .memory import redact_sensitive
from .transport_access import transport_metadata


@dataclass(frozen=True)
class PresentationWork:
    turn_id: str
    sequence: int
    user: str
    answer: str
    route: str
    history: tuple[dict, ...]
    planner_current: dict
    existing_resources: dict[str, str]
    resources: tuple[dict[str, str], ...]
    presentation_resources: tuple[dict[str, str], ...]
    expected_revision: int
    command: dict


@dataclass(frozen=True)
class TurnResult:
    turn_id: str
    answer: str
    route: str
    sources: tuple[dict[str, str], ...]
    resources: tuple[dict[str, str], ...]
    conversation_id: str | None
    presentation: PresentationWork | None
    assistant_message_id: str | None = None


class EveAgent:
    """Deterministic turn orchestrator with an explicit tool boundary."""

    @staticmethod
    def self_descriptions():
        from .runtime_self_knowledge import RuntimeSelfDescription
        return [RuntimeSelfDescription(
            "agent.vision", "vision.input",
            "Ich kann in einer Unterhaltung bereitgestellte Bilder analysieren.",
            "EveAgent", "respond(images)",
        )]

    def __init__(
        self,
        identity: str,
        memory,
        llm,
        bus,
        web=None,
        home_assistant=None,
        reminders=None,
        network_tools=None,
        nova_maintenance=None,
        diagnostics=None,
        conversations=None,
        presentations=None,
        monotonic_clock=None,
        wall_clock=None,
        work_tasks=None,
        local_search=None,
        local_files=None,
        semantic_similarity=None,
        semantic_composition=None,
        wayland_computer=None,
        shell=None,
        external_mcp=None,
        image_generation=None,
    ):
        self.identity, self.memory, self.llm, self.bus = identity, memory, llm, bus
        self.web, self.home_assistant = web, home_assistant
        self.wayland_computer = wayland_computer
        self.external_mcp = external_mcp
        self.image_generation = image_generation
        self.shell = shell
        from .semantic_links import SemanticLinks
        database = getattr(memory, "database", None)
        self.semantic_links = SemanticLinks(database, semantic_similarity, semantic_composition) if database else None
        self._semantic_hit = None
        self._semantic_match = None
        self._semantic_composition = None
        self._semantic_context = None
        self._semantic_references = []
        self._current_turn_plan = None
        self._semantic_feedback_answer = None
        self._semantic_replan_id = None
        self.reminders, self.network_tools = reminders, network_tools
        self.nova_maintenance, self.diagnostics = nova_maintenance, diagnostics
        self.conversations = conversations
        self.presentations = presentations
        self.work_tasks, self.local_search, self.local_files = work_tasks, local_search, local_files
        self._monotonic_clock = monotonic_clock or time.monotonic
        self._wall_clock = wall_clock or time.time
        self._last_user_interaction: dict[str, float] = {}
        self.last_sources: list[dict[str, str]] = []
        self.last_web_query: str | None = None
        self.last_route: Route | None = None
        self.session_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.history: list[dict] = []
        self.conversation_id: str | None = None
        if self.conversations:
            existing = self.conversations.list(limit=1)
            self.conversation_id = (existing[0] if existing else self.conversations.create())["id"]
            self.history = self.conversations.recent_history(self.conversation_id)
            self._restore_interaction_clock(self.conversation_id)
        self._input_image_count = 0
        self._input_images: list[str] = []
        self._tool_events: list[dict] = []
        self._presentation_resources: list[dict[str, str]] = []
        self._unified_presentation_command: dict[str, Any] | None = None
        self._unified_presentation_error: str | None = None
        self._unified_presentation_basis: dict[str, Any] | None = None
        self._turn_attachments: list[dict] = []
        self._turn_number = 0
        self._correlation = ""
        self._turn_state = "conversational"
        self._turn_state_details: dict[str, Any] = {}
        self._last_operational_turn: dict[str, Any] | None = None
        self._turn_planning_failed = False
        self.telemetry = None
        self._defer_presentation = False
        self._last_turn_result: TurnResult | None = None
        self._presentation_order_lock = threading.RLock()
        self._latest_deferred_presentation_sequence = 0
        self._turn_cancellation = contextvars.ContextVar("eve_agent_turn_cancellation", default=None)
        self._published_answer = contextvars.ContextVar("eve_agent_published_answer", default=None)
        self._pending_manual_resume: str | None = None
        self._pending_operational_resolution: dict[str, Any] | None = None
        self._restore_conversation_operational_state()

    def _restore_conversation_operational_state(self) -> None:
        if not self.conversations or not self.conversation_id:
            return
        state = self.conversations.conversation_state(self.conversation_id)
        pending = state.get("pending_resolution")
        self._pending_operational_resolution = (
            dict(pending) if isinstance(pending, dict) and pending.get("status") == "open" else None
        )
        focus = state.get("dialog_focus", [])
        if self.home_assistant and isinstance(focus, list):
            valid = [item for item in focus if isinstance(item, dict) and item.get("entity_id")]
            self.home_assistant.last_target_focus = deepcopy(valid)
            self.home_assistant.last_entities = [str(item["entity_id"]) for item in valid]
            self.home_assistant.last_domain = (
                self.home_assistant.last_entities[-1].split(".", 1)[0]
                if self.home_assistant.last_entities else None
            )

    def _persist_conversation_operational_state(self) -> None:
        if not self.conversations or not self.conversation_id:
            return
        focus = []
        if self.home_assistant:
            focus = deepcopy(getattr(self.home_assistant, "last_target_focus", []))
        state = {"dialog_focus": focus}
        if self._pending_operational_resolution:
            state["pending_resolution"] = deepcopy(self._pending_operational_resolution)
        self.conversations.set_conversation_state(self.conversation_id, state)

    @staticmethod
    def _redact_structure(value):
        if isinstance(value, str):
            return redact_sensitive(value)
        if isinstance(value, list):
            return [EveAgent._redact_structure(item) for item in value]
        if isinstance(value, dict):
            return {str(key): EveAgent._redact_structure(item) for key, item in value.items()}
        return value

    def _pending_context(self) -> dict | None:
        pending = self._pending_operational_resolution
        return deepcopy(pending) if isinstance(pending, dict) and pending.get("status") == "open" else None

    def _pending_discovery(self) -> dict | None:
        pending = self._pending_context()
        if not pending:
            return None
        matches, bindings = [], []
        for candidate in pending.get("candidates", []):
            if not isinstance(candidate, dict) or not candidate.get("entity_id"):
                continue
            entity_id = str(candidate["entity_id"])
            sources = sorted(set(candidate.get("evidence_sources", []) or []))
            user_confirmed = candidate.get("user_confirmed") is True
            matches.append({
                "id": entity_id, "name": candidate.get("name") or entity_id,
                "candidate_origin": (
                    "pending_resolution" if user_confirmed
                    else "remembered_binding" if "remembered_binding" in sources
                    else "pending_resolution"
                ),
                "evidence_sources": sources,
                "provider_existence_verified": bool(candidate.get("provider_existence_verified")),
                "current_target_match": candidate.get("current_target_match", "unassessed"),
                "user_confirmed": user_confirmed,
            })
            if "remembered_binding" in sources:
                bindings.append({
                    "entity_id": entity_id, "subject": candidate.get("name") or entity_id,
                    "property": "resource", "provider": "home_assistant",
                })
        return {
            "status": "pending_resolution_evidence", "matches": matches,
            "remembered_bindings": bindings, "services": {}, "requests": [], "pages": [],
        }

    def _confirm_pending_target(self, entity_id: str) -> list[str]:
        pending = self._pending_operational_resolution
        if not isinstance(pending, dict) or pending.get("status") != "open":
            return []
        if str(pending.get("preferred_target")) != str(entity_id):
            return []
        candidate = next((
            item for item in pending.get("candidates", [])
            if isinstance(item, dict) and str(item.get("entity_id")) == str(entity_id)
        ), None)
        if candidate is None:
            return []
        changed = []
        if candidate.get("user_confirmed") is not True:
            candidate["user_confirmed"] = True
            changed.append("target_confirmation")
        sources = set(candidate.get("evidence_sources", []) or [])
        if "user_confirmation" not in sources:
            sources.add("user_confirmation")
            candidate["evidence_sources"] = sorted(sources)
            changed.append("candidate_evidence")
        if candidate.get("current_target_match") != "user_confirmation":
            candidate["current_target_match"] = "user_confirmation"
            changed.append("current_target_match")
        unresolved = list(pending.get("unresolved", []))
        if "remembered_binding_target_unconfirmed" in unresolved:
            pending["unresolved"] = [
                item for item in unresolved if item != "remembered_binding_target_unconfirmed"
            ]
            changed.append("unresolved")
        if changed:
            now = datetime.now().astimezone().isoformat()
            pending["updated_at"] = now
            pending.setdefault("resolution_history", []).append({
                "at": now, "kind": "target_confirmation", "entity_id": str(entity_id),
                "changed_fields": list(changed),
            })
            self._persist_conversation_operational_state()
        return changed

    def _publish_pending_context(self, context: str) -> str:
        pending = self._pending_context()
        if not pending:
            return context
        try:
            provider = json.loads(context)
        except (TypeError, json.JSONDecodeError):
            return context
        provider["pending_resolution"] = pending
        return json.dumps(provider, ensure_ascii=False, separators=(",", ":"))

    def _open_pending_resolution(
        self, *, utterance: str, plan: dict, discovery: dict | None,
        missing: str, clarification: str,
    ) -> None:
        actions = [deepcopy(item) for item in plan.get("actions", []) if isinstance(item, dict)]
        candidates = []
        for item in (discovery or {}).get("matches", []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            candidates.append({
                "entity_id": str(item["id"]),
                "name": item.get("name"),
                "evidence_sources": sorted(set(
                    item.get("evidence_sources", []) or [item.get("candidate_origin")]
                ) - {None}),
                "provider_existence_verified": bool(item.get("provider_existence_verified")),
                "current_target_match": item.get("current_target_match", "unassessed"),
            })
        now = datetime.now().astimezone().isoformat()
        self._pending_operational_resolution = {
            "version": 1, "status": "open", "provider": "home_assistant",
            "route": Route.HOME.value, "original_utterance": utterance,
            "effect": plan.get("effect"), "actions": actions,
            "operation_types": [str(item.get("type")) for item in actions if item.get("type")],
            "candidates": candidates,
            "preferred_target": next((
                str(item.get("entity_id")) for item in actions if item.get("entity_id")
            ), None),
            "unresolved": [missing], "clarification": clarification,
            "created_at": now, "updated_at": now,
        }
        self._persist_conversation_operational_state()
        if self.telemetry:
            self.telemetry.event("conversation", "pending_resolution", status="opened", details={
                "operation_types": self._pending_operational_resolution["operation_types"],
                "candidate_ids": [item["entity_id"] for item in candidates],
                "unresolved": [missing],
                "evidence_sources": sorted({
                    source for item in candidates for source in item["evidence_sources"]
                }),
            })

    def _close_pending_resolution(self, reason: str) -> None:
        if not self._pending_operational_resolution:
            return
        if self.telemetry:
            self.telemetry.event("conversation", "pending_resolution", status="closed", details={
                "reason": reason,
                "operation_types": self._pending_operational_resolution.get("operation_types", []),
            })
        self._pending_operational_resolution = None
        self._persist_conversation_operational_state()

    @contextmanager
    def cancellable(self, cancellation):
        token = self._turn_cancellation.set(cancellation)
        provider_context = (
            self.home_assistant.cancellable(cancellation)
            if self.home_assistant is not None
            and callable(getattr(self.home_assistant, "cancellable", None))
            else nullcontext()
        )
        try:
            with provider_context:
                yield
        finally:
            self._turn_cancellation.reset(token)

    @contextmanager
    def published_answer_stream(self):
        """Track the exact text already exposed by the active response stream."""
        chunks: list[str] = []
        token = self._published_answer.set(chunks)
        try:
            yield chunks
        finally:
            self._published_answer.reset(token)

    def note_published_answer_delta(self, chunk: str) -> None:
        chunks = self._published_answer.get()
        if chunks is not None and chunk:
            chunks.append(chunk)

    def _cancel_checkpoint(self, *, commit: bool = False) -> None:
        cancellation = self._turn_cancellation.get()
        if cancellation is None:
            return
        if commit:
            cancellation.begin_commit()
        else:
            cancellation.checkpoint()

    @staticmethod
    def _without_inline_media(value):
        """Retain execution provenance while keeping media bytes out of logs/prompts."""
        if isinstance(value, list):
            return [EveAgent._without_inline_media(item) for item in value]
        if not isinstance(value, dict):
            return value
        cleaned = {}
        media = value.get("type") in {"image", "video"}
        for key, item in value.items():
            if media and key == "content":
                continue
            cleaned[key] = EveAgent._without_inline_media(item)
        return cleaned

    def _diagnostic(
        self,
        component: str,
        operation: str,
        status: str,
        message: str,
        *,
        exception: BaseException | None = None,
        route: Route | None = None,
    ) -> None:
        if not self.diagnostics:
            return
        try:
            self.diagnostics.record(
                component,
                operation,
                status,
                message,
                exception=exception,
                route=(route or self.last_route).value if (route or self.last_route) else None,
                correlation=self._correlation or None,
            )
        except (OSError, ValueError):
            # Diagnostics must never make the user-facing tool unavailable.
            pass

    def _record(self, user: str, answer: str, route: Route) -> str:
        self._cancel_checkpoint()
        record_started = time.perf_counter()
        record_start_ms = self.telemetry.elapsed_ms() if self.telemetry else None
        user, answer = redact_sensitive(user), redact_sensitive(answer)
        self._turn_state_details["operational_execution"] = any(
            isinstance(event, dict) and event.get("status") in {
                "completed", "partial", "outcome_uncertain",
            }
            for event in self._tool_events
        )
        published = self._published_answer.get()
        published_answer = "".join(published) if published else ""
        if published_answer and not answer.startswith(published_answer):
            from .answer_stream import AnswerStreamMismatchError
            raise AnswerStreamMismatchError(published_answer, answer)
        if route == Route.HOME:
            statuses = {
                str(event.get("status")) for event in self._tool_events
                if isinstance(event, dict) and event.get("tool") == "home_assistant"
            }
            for event in self._tool_events:
                if not isinstance(event, dict) or event.get("tool") != "home_assistant":
                    continue
                result = event.get("result", {})
                if not isinstance(result, dict):
                    continue
                for action in result.get("action_results", []):
                    if not isinstance(action, dict):
                        continue
                    status = action.get("status")
                    statuses.add({"success": "completed", "failed": "error",
                                  "skipped": "partial"}.get(status, status))
                    if status in {"success", "outcome_uncertain"}:
                        self._turn_state_details["operational_execution"] = True
            outcome = (
                "execution_failed" if "error" in statuses
                else "operational_unresolved" if statuses != {"completed"}
                else "operational_resolved"
            )
            repairing_incomplete = (self._turn_state == "repair"
                and (self._last_operational_turn or {}).get("details", {}).get("write_retry_forbidden"))
            if repairing_incomplete and outcome == "operational_resolved":
                outcome = "operational_unresolved"
            if outcome != "execution_failed":
                self._turn_state_details["status_origin"] = "provider_result"
            self._turn_state_details["provider_outcome"] = outcome
            current_events = deepcopy([
                event for event in self._tool_events
                if isinstance(event, dict) and event.get("tool") == "home_assistant"
            ])
            if repairing_incomplete:
                self._turn_state_details["provider_events"] = deepcopy(
                    self._last_operational_turn["details"].get("provider_events", []))
                self._turn_state_details["repair_events"] = current_events
            else:
                self._turn_state_details["provider_events"] = current_events
            incomplete = bool(repairing_incomplete or statuses & {"outcome_uncertain", "partial", "cancelled"}
                              or {"completed", "error"}.issubset(statuses))
            self._turn_state_details["write_retry_forbidden"] = bool(
                repairing_incomplete or statuses & {"outcome_uncertain", "partial"}
                or {"completed", "error"}.issubset(statuses)
                or ("cancelled" in statuses and self._turn_state_details["operational_execution"])
            )
            if incomplete and self._last_operational_turn:
                previous = self._last_operational_turn
                self._turn_state_details["previous_unresolved_turn"] = {
                    "state": previous.get("state"), "utterance": previous.get("utterance"),
                    "route": previous.get("route"),
                    "details": {k: deepcopy(v) for k, v in previous.get("details", {}).items()
                                if k != "previous_unresolved_turn"},
                }
            if self._turn_state == "repair":
                self._turn_state_details["repair_outcome"] = outcome
                if outcome == "operational_resolved":
                    self._last_operational_turn = None
                elif self._last_operational_turn:
                    self._last_operational_turn = {
                        **self._last_operational_turn, "state": outcome,
                        "details": dict(self._turn_state_details),
                    }
            else:
                self._turn_state = outcome
        if self._turn_state in {"operational_unresolved", "execution_failed"}:
            original = self._turn_state_details.get("original_utterance") or user
            self._last_operational_turn = {
                "state": self._turn_state,
                "utterance": original,
                "route": route,
                "details": dict(self._turn_state_details),
            }
        elif self._turn_state == "operational_resolved":
            self._last_operational_turn = None
        if self.telemetry:
            self.telemetry.summary(
                request_status="completed",
                final_turn_state=self._turn_state,
                operational_execution=bool(
                    self._turn_state_details.get("operational_execution")
                ),
            )
        turn_id = (
            self.telemetry.active_id() if self.telemetry and self.telemetry.active_id()
            else getattr(self, "_trace_id", None)
            or getattr(self, "_semantic_turn_ref", None) or uuid.uuid4().hex
        )
        semantic_claim_id = (self._turn_state_details.get("semantic_link_candidate_id")
                             or self._turn_state_details.get("semantic_link_id"))
        knowledge_flow = getattr(self, "_knowledge_flow", None)
        if isinstance(knowledge_flow, dict):
            stages = knowledge_flow.setdefault("stages", [])
            stages.append({
                "kind": "turn_state", "status": self._turn_state,
                "label": "Turn-Zustand", "summary": self._turn_state,
                "details": dict(self._turn_state_details),
            })
            tool_events = [
                event for event in self._tool_events
                if isinstance(event, dict) and event.get("tool") != "web"
            ]
            if tool_events and not any(stage.get("kind") == "tools" for stage in stages):
                stages.append({
                    "kind": "tools", "status": "completed", "label": "Tools",
                    "summary": f"{len(tool_events)} Tool-Ereignisse",
                    "details": {
                        "tools": [event.get("tool") for event in tool_events],
                        "statuses": [event.get("status") for event in tool_events],
                    },
                })
            if not any(stage.get("kind") == "eve" for stage in stages):
                stages.append({
                    "kind": "eve", "status": "processed", "label": "EVE",
                    "summary": "Turn verarbeitet",
                })
            if not any(stage.get("kind") == "answer" for stage in stages):
                stages.append({
                    "kind": "answer", "status": "completed", "label": "Antwort",
                    "summary": "Antwort erstellt",
                })
        presentation_work = None
        if route != Route.PRESENTATION and self._unified_presentation_command:
            presentation_work = self._prepare_presentation_work(
                user, answer, route, self._unified_presentation_command,
            )
            if presentation_work and self._defer_presentation:
                with self._presentation_order_lock:
                    self._latest_deferred_presentation_sequence = max(
                        self._latest_deferred_presentation_sequence,
                        presentation_work.sequence,
                    )
            elif presentation_work:
                self.run_presentation(presentation_work)
        persistence_started = time.perf_counter()
        persistence_start_ms = self.telemetry.elapsed_ms() if self.telemetry else None
        self._cancel_checkpoint(commit=True)
        assistant_message_id = None
        if self.conversations and self.conversation_id:
            user_message, assistant_message = self.conversations.append_turn(
                self.conversation_id,
                user,
                answer,
                user_metadata={"image_count": self._input_image_count,
                               **({"conversation_source": source} if (source := transport_metadata()) else {})},
                assistant_metadata={
                    "route": route.value, "sources": list(self.last_sources),
                    "turn_state": self._turn_state,
                    "turn_state_details": dict(self._turn_state_details),
                    "working_memory": deepcopy(getattr(self, "_working_memory_context", None)),
                },
                user_attachments=[
                    {"type": "image", "content": image, "source": "user"}
                    for image in self._input_images
                ],
                assistant_attachments=[
                    {**item, "source": route.value}
                    for item in self._presentation_resources if item.get("persist", True)
                ] + list(self._turn_attachments),
                tool_events=list(self._tool_events),
                turn_id=turn_id,
                knowledge_flow=knowledge_flow,
                source_memory_ids=list(getattr(self, "_turn_memory_ids", [])),
                memory_retrievals=[],
            )
            assistant_message_id = assistant_message["id"]
            if getattr(self.memory, "revisions", None):
                self.memory.revisions.attach_turn(turn_id, user_message["id"])
        self.history.extend([
            {"role": "user", "content": user,
             **({"conversation_source": source} if (source := transport_metadata()) else {})},
            {"role": "assistant", "content": answer},
        ])
        if self.conversations and self.conversation_id:
            if route == Route.WORK_TASKS and hasattr(self.work_tasks, "attach_mutation_provenance"):
                try:
                    self.work_tasks.attach_mutation_provenance(
                        self.conversation_id, user_message["id"],
                    )
                except (KeyError, RuntimeError, TypeError, ValueError) as exc:
                    self._diagnostic(
                        "work_tasks", "provenance", "error",
                        "Task-Provenance konnte nicht gespeichert werden", exception=exc, route=route,
                    )
            if self._turn_memory_hits:
                with self.memory.database.connect() as connection:
                    connection.executemany(
                        """INSERT OR IGNORE INTO memory_compiler_usage
                           (turn_id,consumer,claim_id,usage,created_at)
                           VALUES (?,'answer',?,'presented',?)""",
                        [
                            (turn_id, hit.memory_id, datetime.now().astimezone().isoformat())
                            for hit in self._turn_memory_hits
                            if hit.memory_id and hit.method == "memory_v2"
                        ],
                    )
        semantic_claim_ids = self._turn_state_details.get("semantic_link_candidate_ids") or ([semantic_claim_id] if semantic_claim_id else [])
        for semantic_claim_id in semantic_claim_ids if self.semantic_links else []:
            try:
                self.semantic_links.record_occurrence(semantic_claim_id,
                    conversation_id=self._semantic_conversation_key(), turn_ref=self._semantic_source_ref(), utterance=user,
                    similarity=self._turn_state_details.get("semantic_similarity"))
            except (sqlite3.Error, OSError, ValueError) as exc:
                self._semantic_event("provenance", "error", error_class=type(exc).__name__)
        if self.semantic_links and self.conversations and self.conversation_id:
            try:
                self.semantic_links.attach_turn_provenance(self._semantic_source_ref(), turn_id, user_message["id"])
            except (sqlite3.Error, OSError) as exc:
                self._semantic_event("provenance", "error", error_class=type(exc).__name__)
        self.last_route = route
        if self.telemetry:
            if isinstance(knowledge_flow, dict):
                self.telemetry.knowledge_flow(knowledge_flow)
            self.telemetry.route(route.value)
            self.telemetry.event(
                "response", "persist",
                duration_ms=(time.perf_counter() - persistence_started) * 1000,
                start_ms=persistence_start_ms,
            )
            self.telemetry.event(
                "response", "record_total",
                duration_ms=(time.perf_counter() - record_started) * 1000,
                start_ms=record_start_ms,
            )
        self._last_turn_result = TurnResult(
            turn_id=turn_id,
            answer=answer,
            route=route.value,
            sources=tuple(deepcopy(self.last_sources)),
            resources=tuple(deepcopy(self._presentation_resources)),
            conversation_id=self.conversation_id,
            presentation=presentation_work if self._defer_presentation else None,
            assistant_message_id=assistant_message_id,
        )
        return answer

    def respond_turn(
        self,
        utterance: str,
        images: list[str] | None = None,
        conversation_id: str | None = None,
    ) -> TurnResult:
        """Return the persisted answer plus immutable deferred presentation work."""
        if self._defer_presentation:
            raise RuntimeError("Ein Turn wird bereits vorbereitet")
        self._defer_presentation = True
        self._last_turn_result = None
        try:
            self.respond(utterance, images, conversation_id)
            if self._last_turn_result is None:
                raise RuntimeError("Turn wurde ohne strukturiertes Ergebnis abgeschlossen")
            return self._last_turn_result
        finally:
            self._defer_presentation = False

    def _unified_answer_presentation_context(self, route: Route) -> dict | None:
        if not self.presentations:
            return None
        resource_references = [
            {
                "reference": f"resource:{index}",
                **{
                    key: item[key] for key in (
                        "type", "action_index", "operation", "entity_id",
                        "result_status", "result_reference",
                    ) if key in item
                },
            }
            for index, item in enumerate(self._presentation_resources)
        ]
        current = self.presentations.read()
        planner_current, existing_resources = self._presentation_planner_state(current)
        self._unified_presentation_basis = {
            "planner_current": planner_current,
            "existing_resources": existing_resources,
            "resources": tuple(deepcopy(resource_references)),
            "presentation_resources": tuple(deepcopy(self._presentation_resources)),
            "expected_revision": int(current.get("revision", 0)),
        }
        return {
            "active_presentation": planner_current,
            "available_resources": resource_references,
            "completed_capability": route.value,
        }

    def _capture_unified_answer(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        answer = getattr(result, "answer", None)
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("Unified Answer lieferte keinen gültigen Antworttext")
        command = getattr(result, "presentation", None)
        error = getattr(result, "presentation_error", None)
        self._unified_presentation_command = deepcopy(command) if isinstance(command, dict) else None
        self._unified_presentation_error = str(error) if error else None
        if self.telemetry:
            available_ms = self.telemetry.elapsed_ms()
            self.telemetry.event(
                "presentation", "unified_output",
                status="error" if error else "completed",
                start_ms=available_ms, duration_ms=0,
                details={
                    "action": command.get("action") if isinstance(command, dict) else None,
                    "error": self._unified_presentation_error,
                },
            )
            self.telemetry.summary(
                presentation_available_ms=(
                    None if available_ms is None else round(available_ms, 2)
                ),
                presentation_structure_error=self._unified_presentation_error,
            )
        if error:
            self._diagnostic(
                "presentation", "unified_output", "error",
                "Unified Answer enthielt keine gültige Presentation-Struktur",
            )
        return answer



    def _prepare_presentation_work(
        self, user: str, answer: str, route: Route, command: dict,
    ) -> PresentationWork | None:
        if not self.presentations or not isinstance(command, dict):
            return None
        if command.get("action") == "none":
            return None
        basis = self._unified_presentation_basis
        if not isinstance(basis, dict):
            self._diagnostic(
                "presentation", "unified_output", "error",
                "Unified Presentation besitzt keinen gültigen Planning-Scope",
            )
            return None
        turn_id = (
            self.telemetry.active_id() if self.telemetry and self.telemetry.active_id()
            else uuid.uuid4().hex
        )
        return PresentationWork(
            turn_id=turn_id,
            sequence=self._turn_number,
            user=user,
            answer=answer,
            route=route.value,
            history=tuple(deepcopy(self.history)),
            planner_current=deepcopy(basis["planner_current"]),
            existing_resources=deepcopy(basis["existing_resources"]),
            resources=tuple(deepcopy(basis["resources"])),
            presentation_resources=tuple(deepcopy(basis["presentation_resources"])),
            expected_revision=int(basis["expected_revision"]),
            command=deepcopy(command),
        )

    def run_presentation(self, work: PresentationWork) -> dict[str, Any]:
        """Validate and commit the presentation from the unified answer decision."""
        started = time.perf_counter()
        start_ms = self.telemetry.elapsed_ms() if self.telemetry else None
        try:
            command = deepcopy(work.command)
            if command.get("action") == "none":
                if self.telemetry:
                    self.telemetry.event(
                        "presentation", "decision",
                        duration_ms=(time.perf_counter() - started) * 1000,
                        start_ms=start_ms, details={"action": "none", "decision": "unified_answer"},
                    )
                return {
                    "turn_id": work.turn_id, "status": "success", "action": "none",
                    "revision": work.expected_revision,
                }
            decision_finished = time.perf_counter()
            resolved = self._resolve_presentation_resources(
                command, work.existing_resources, list(work.presentation_resources),
            )
            with self._presentation_order_lock:
                if (
                    self._defer_presentation
                    or work.sequence < self._latest_deferred_presentation_sequence
                ):
                    status = "stale"
                    result = {"revision": self.presentations.read().get("revision", 0)}
                else:
                    try:
                        result = self.presentations.execute_if_revision(
                            resolved, work.expected_revision,
                        )
                        status = "success"
                    except RuntimeError:
                        status = "stale"
                        result = {"revision": self.presentations.read().get("revision", 0)}
            if self.telemetry:
                validation_ms = (time.perf_counter() - decision_finished) * 1000
                self.telemetry.event(
                    "presentation", "validate_and_resolve",
                    status=status,
                    duration_ms=validation_ms,
                    start_ms=(
                        None if start_ms is None else
                        start_ms + (decision_finished - started) * 1000
                    ),
                    details={"action": resolved.get("action", "unknown")},
                )
                self.telemetry.event(
                    "presentation", "decision",
                    duration_ms=(decision_finished - started) * 1000,
                    start_ms=start_ms, details={"action": command.get("action")},
                )
                self.telemetry.event(
                    "presentation", resolved.get("action", "unknown"),
                    status=status,
                    duration_ms=(time.perf_counter() - decision_finished) * 1000,
                    details={
                        "id": result.get("id"), "revision": result.get("revision"),
                        "decision": "unified_answer", "turn_id": work.turn_id,
                    },
                )
            return {
                "turn_id": work.turn_id, "status": status,
                "action": resolved.get("action", "unknown"),
                "revision": result.get("revision"),
            }
        except (KeyError, TypeError, ValueError, RuntimeError, OSError) as exc:
            if self.telemetry:
                self.telemetry.event(
                    "presentation", "validate_and_resolve", status="error",
                    duration_ms=(time.perf_counter() - started) * 1000,
                    start_ms=start_ms,
                    details={"error": type(exc).__name__},
                )
            self._diagnostic(
                "presentation", "unified_validation", "error",
                "Unified Presentation konnte technisch nicht ausgeführt werden",
                exception=exc,
            )
            return {
                "turn_id": work.turn_id, "status": "error", "action": "unknown",
                "revision": work.expected_revision, "error": type(exc).__name__,
            }

    @staticmethod
    def _presentation_planner_state(current: dict) -> tuple[dict, dict[str, str]]:
        """Return model-safe state while retaining media only in an opaque server-side map."""

        compact = deepcopy(current)
        retained: dict[str, str] = {}
        metadata: list[dict[str, object]] = []

        def scrub(components, path: str = "") -> None:
            if not isinstance(components, list):
                return
            for index, component in enumerate(components):
                if not isinstance(component, dict):
                    continue
                component_path = f"{path}.{index}" if path else str(index)
                kind = component.get("type")
                content = component.get("content")
                if kind in {"image", "video"} and isinstance(content, str):
                    reference = f"existing-resource:{len(retained)}"
                    retained[reference] = content
                    mime_type = None
                    if content.startswith("data:"):
                        header, separator, _payload = content.partition(",")
                        if separator and ";base64" in header:
                            mime_type = header.removeprefix("data:").split(";", 1)[0]
                    component["content"] = reference
                    item: dict[str, object] = {
                        "reference": reference,
                        "type": kind,
                        "component_path": component_path,
                    }
                    if mime_type:
                        item["mime_type"] = mime_type
                    metadata.append(item)
                if kind == "container":
                    scrub(component.get("components"), component_path)

        presentation = compact.get("presentation")
        if isinstance(presentation, dict):
            scrub(presentation.get("components"))
        if metadata:
            compact["available_media"] = metadata
        return compact, retained

    def _resolve_presentation_resources(
        self,
        command: dict,
        existing_resources: dict[str, str] | None = None,
        presentation_resources: list[dict[str, str]] | None = None,
    ) -> dict:
        """Resolve only opaque references supplied to the model; interpret no source."""

        resolved = deepcopy(command)
        existing_resources = existing_resources or {}
        presentation_resources = presentation_resources or self._presentation_resources

        def visit(value):
            if isinstance(value, dict):
                return {key: visit(item) for key, item in value.items()}
            if isinstance(value, list):
                return [visit(item) for item in value]
            if isinstance(value, str) and value.startswith("resource:"):
                suffix = value.removeprefix("resource:")
                if not suffix.isdigit() or int(suffix) >= len(presentation_resources):
                    raise ValueError("Unbekannte Präsentationsressource")
                return presentation_resources[int(suffix)]["content"]
            if isinstance(value, str) and value.startswith("existing-resource:"):
                if value not in existing_resources:
                    raise ValueError("Unbekannte bestehende Präsentationsressource")
                return existing_resources[value]
            return value

        def validate_media(value):
            if isinstance(value, dict):
                component_type = value.get("type")
                if component_type in {"image", "video"}:
                    content = value.get("content")
                    if not isinstance(content, str) or not (
                        content.startswith("resource:") or content.startswith("existing-resource:")
                    ):
                        raise ValueError("Medienkomponente verwendet keine veröffentlichte Ressource")
                for item in value.values():
                    validate_media(item)
            elif isinstance(value, list):
                for item in value:
                    validate_media(item)

        validate_media(resolved)
        return visit(resolved)

    def _restore_interaction_clock(self, conversation_id: str) -> None:
        if not self.conversations or conversation_id in self._last_user_interaction:
            return
        timestamp = self.conversations.last_user_interaction(conversation_id)
        if timestamp is None:
            return
        elapsed = max(0.0, self._wall_clock() - timestamp)
        self._last_user_interaction[conversation_id] = self._monotonic_clock() - elapsed

    def _activate_conversation(self, conversation_id: str | None) -> bool:
        if not self.conversations:
            return False
        target = conversation_id or self.conversation_id
        if not target:
            target = self.conversations.create()["id"]
        self.conversations.get(target)
        if target == self.conversation_id:
            if (transport_metadata() or {}).get("transport") == "chatto":
                # Silent channel observations may have arrived since our last reply.
                self.history = self.conversations.recent_history(target)
            self._restore_interaction_clock(target)
            return False
        self.conversation_id = target
        self.history = self.conversations.recent_history(target)
        self.last_sources = []
        self.last_web_query = None
        self.last_route = None
        if self.home_assistant:
            getattr(self.home_assistant, "cancel_pending", lambda: None)()
            getattr(self.home_assistant, "clear_context", lambda: None)()
        self._pending_operational_resolution = None
        self._restore_conversation_operational_state()
        self._restore_interaction_clock(target)
        return True

    def _conversation_lifecycle(self, conversation_id: str | None) -> dict:
        """Select the conversation explicitly addressed by the client."""
        switched = self._activate_conversation(conversation_id)
        now_mono = self._monotonic_clock()
        previous = self._last_user_interaction.get(self.conversation_id or "")
        idle = None if previous is None else max(0.0, now_mono - previous)
        reason = "manual" if switched else "existing"
        return {
            "conversation_id": self.conversation_id,
            "idle_time_seconds": idle,
            "configured_session_timeout_seconds": None,
            "new_session": False,
            "reason": reason,
        }

    def prepare_conversation_view(self, conversation_id: str | None = None) -> dict:
        """Select the conversation addressed by the chat UI."""
        return self._conversation_lifecycle(conversation_id)

    def _prepare_user_turn(self, conversation_id: str | None) -> dict:
        """Select the requested conversation, then mark this input arrival.

        Browser clients include their active conversation ID with every turn
        so the response remains bound to the view that submitted it. EVE keeps
        that conversation active until the user explicitly selects another.
        """
        lifecycle = self.prepare_user_turn_view(conversation_id)
        if self.conversation_id:
            self._last_user_interaction[self.conversation_id] = self._monotonic_clock()
            if self.conversations:
                self.conversations.record_user_interaction(self.conversation_id, self._wall_clock())
        return lifecycle

    def prepare_user_turn_view(
        self, conversation_id: str | None, *, explicit_resume: bool = False,
        reserve_resume: bool = False,
    ) -> dict:
        """Resolve the conversation for an incoming turn without recording it.

        The browser uses this before publishing turn acceptance, so a timeout
        rollover becomes visible before optimistic input or streamed output is
        attached to a conversation.
        """
        reserved_resume = (
            conversation_id is not None
            and conversation_id == self._pending_manual_resume
        )
        manual_resume = explicit_resume or reserved_resume or (
            conversation_id is not None
            and conversation_id != self.conversation_id
        )
        lifecycle = self._conversation_lifecycle(conversation_id)
        if manual_resume:
            lifecycle["reason"] = "manual_resume"
        if explicit_resume and reserve_resume and lifecycle.get("conversation_id"):
            self._pending_manual_resume = lifecycle["conversation_id"]
        elif reserved_resume:
            self._pending_manual_resume = None
        return lifecycle

    def _set_turn_planning_failure(
        self,
        *,
        phase: str,
        error: BaseException | None,
        attempt_count: int,
        retry_outcome: str,
        error_code: str = "planning_failure",
        capability: str | None = None,
        operation: str | None = None,
        model_response_accepted: bool = False,
        provider_called: bool = False,
        provider_operation_count: int = 0,
        planner_round_count: int = 0,
        planner_round_limit: int = 0,
        candidate_count: int = 0,
        continuation_count: int = 0,
    ) -> None:
        """Record a technical planning failure without inventing turn semantics."""
        self._turn_planning_failed = True
        self._turn_state = "planning_failed"
        self._turn_state_details = {
            "reason": "technical_planning_failure",
            "phase": phase,
            "error_code": error_code,
            "error_class": type(error).__name__ if error is not None else "UnavailableComponent",
            "technical_cause": redact_sensitive(str(error)) if error is not None else "Komponente nicht verfügbar",
            "capability": capability,
            "operation": operation,
            "model_response_accepted": bool(model_response_accepted),
            "provider_called": bool(provider_called),
            "provider_operation_count": max(0, int(provider_operation_count)),
            "planner_round_count": max(0, int(planner_round_count)),
            "planner_round_limit": max(0, int(planner_round_limit)),
            "candidate_count": max(0, int(candidate_count)),
            "continuation_count": max(0, int(continuation_count)),
            "attempt_count": attempt_count,
            "retry_outcome": retry_outcome,
            "status_origin": "technical_error",
            "valid_model_decision": bool(model_response_accepted),
            "operational_execution": False,
        }
        if self.telemetry:
            self.telemetry.event(
                "planner", "technical_failure", status="error",
                details=dict(self._turn_state_details),
            )

    def _semantic_conversation_key(self):
        return self.conversation_id or "session:" + self.session_id

    def _semantic_source_ref(self):
        return getattr(self, "_semantic_turn_ref", None) or self._correlation

    def _semantic_event(self, operation, status, **details):
        if self.telemetry:
            self.telemetry.event("semantic_links", operation, status=status, details=details)

    def _semantic_feedback(self, result, text):
        decision = result.get("semantic_decision")
        if decision is None or isinstance(decision, dict) and decision.get("type") == "none":
            return None
        if not self.semantic_links:
            return None
        try:
            if not isinstance(decision, dict):
                raise ValueError("Malformed semantic decision")
            quote = decision.get("user_quote")
            if quote != text or not quote or not isinstance(decision.get("basis"), str) or not decision["basis"].strip() or decision.get("current_turn_ref") != self._semantic_source_ref():
                raise ValueError("Semantic feedback has no user evidence")
            if result.get("feedback_contract_conflict") or result.get("authorized_tool") or result.get("tool") not in {None, "respond"} or result.get("candidate_tools") or result.get("contract_match"):
                raise ValueError("Feedback conflicts with operational authorization")
            self._semantic_event("dialog_decision", "feedback_recognized", decision=deepcopy(decision))
            if decision.get("type") == "clarify":
                if decision.get("reason") not in {"ambiguous_reference", "missing_context", "conflicting_evidence"}:
                    raise ValueError("No decision-relevant uncertainty")
                question = decision.get("clarification")
                if not isinstance(question, str) or not question.strip():
                    raise ValueError("Missing clarification")
                self._semantic_feedback_answer = question
                self._semantic_event("learning_clarification", "required", reason=decision["reason"])
                self._turn_state = "operational_unresolved"
            else:
                if result.get("turn_state") != "conversational" or decision.get("reason") != "explicit_feedback" or type(decision.get("replan", False)) is not bool:
                    raise ValueError("Invalid decision contract")
                claim_id = self.semantic_links.apply_dialog_decision(
                    decision, utterance=text, conversation_id=self._semantic_conversation_key(),
                    source_ref=self._semantic_source_ref(), published=self._semantic_references)
                self._semantic_event("feedback_reference", "validated", link_id=claim_id, occurrence_ref=decision["occurrence_ref"], current_turn_ref=self._semantic_source_ref())
                confirmed = decision["type"] == "confirm"
                reference = next((item for item in self._semantic_references
                                  if item.get("link_id") == decision.get("link_id")
                                  and item.get("occurrence_ref") == decision.get("occurrence_ref")), {})
                dynamic_feedback = isinstance(reference.get("similarity"), dict)
                self._semantic_feedback_answer = (
                    "Die Zuordnung ist bestätigt. Ich habe keine weitere Geräteaktion ausgeführt."
                    if confirmed else (
                        "Diese dynamische Zuordnung ist gesperrt. Die ursprünglich gelernte Aktion bleibt erhalten. "
                        "Ich habe keine Geräteaktion wiederholt."
                        if dynamic_feedback else
                        "Die bisherige Zuordnung ist gesperrt. Ich habe keine Geräteaktion wiederholt."
                    )
                )
                if (not confirmed and decision.get("replan") and self.home_assistant
                        and getattr(self.home_assistant, "configured", False)
                        and not self._pending_context() and not (
                        getattr(self.home_assistant, "has_pending", lambda: False)())):
                    self._semantic_replan_id = claim_id
                self._semantic_event("explicit_confirmation" if confirmed else "user_correction", "applied", link_id=claim_id)
                if not confirmed:
                    self._semantic_event("similarity_correction" if dynamic_feedback else "invalidate",
                                         "effective" if dynamic_feedback else "user_contradiction",
                                         link_id=claim_id)
                self._turn_state = "conversational"
                self._turn_state_details["semantic_decision"] = deepcopy(decision)
            return Route.CHAT, text
        except (KeyError, ValueError, sqlite3.Error, OSError) as exc:
            # An ungrounded decision cannot fall through to an old repair route.
            self._semantic_event("dialog_decision", "rejected", reason="insufficient_or_conflicting_causal_evidence", decision=deepcopy(decision), error_class=type(exc).__name__)
            self._semantic_feedback_answer = "Deine Aussage ist nicht eindeutig als Rückmeldung oder neuer Auftrag aufgelöst. Möchtest du einen neuen Auftrag ausführen lassen oder einen früheren Vorgang bewerten?"
            self._turn_state = "operational_unresolved"
            self._turn_state_details["reason"] = "semantic_feedback_reference_unresolved"
            self._semantic_event("learning_clarification", "required", error_class=type(exc).__name__)
            return Route.CHAT, text

    def respond(
        self,
        utterance: str,
        images: list[str] | None = None,
        conversation_id: str | None = None,
    ) -> str:
        """Run Qwen's native Memory and provider tool path."""
        from .minimal import NativeToolRuntime
        runtime = getattr(self, "_native_tool_runtime", None)
        if runtime is None:
            runtime = self._native_tool_runtime = NativeToolRuntime(self)
            # Compatibility handle for Brainwatch and existing integrations.
            self._minimal_runtime = runtime
        return runtime.respond(utterance, images=images, conversation_id=conversation_id)
