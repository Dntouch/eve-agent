from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import sys
import time
import webbrowser
import threading
import base64
import io
import re
import wave
import uuid
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .agent import EveAgent
from .artifacts import extract_artifacts
from .audio import Recorder, Speaker, Transcriber, temporary_wav
from .config import ConfigError, config_status, default_config_path, editable_config, load_config, update_editable_config
from .telemetry import TurnTelemetry
from .llm import LocalLLMError, OpenAICompatibleLLM
from .home_assistant import HomeAssistant
from .home_assistant_inventory import HomeAssistantInventory
from .training_packages import HomeAssistantTrainingAdapter, TrainingPackageManager
from .diagnostics import DiagnosticJournal
from .provider_mcp import ProviderMcpCapability
from .work_tasks import WorkTaskStore
from .scheduler import ScheduledTasks
from .shadow_learning import ProductiveLearningPipeline
from .conversation_learning import ConversationLearningCoordinator
from .memory_compiler import MemoryCompiler
from .memory_v2 import MemoryV2Runtime
from .local_embeddings import create_embedding_client
from .turn_failures import failure_report, resume_failure_request
from .answer_stream import unpublished_suffix
from .memory import RedactedTextStream, redact_sensitive
from .memory_runtime_telemetry import MemoryRuntimeRecorder
from .memory_retrieval_telemetry import MemoryRetrievalTelemetry
from .llm_context_telemetry import LLMContextTelemetry
from .action_provenance_telemetry import ActionProvenanceTelemetry
from .memory_maintenance import MemoryMaintenance
from .network_tools import LocalNetworkTools
from .state import StateBus
from .storage import ConversationStore, EveDatabase
from .search import LocalSearchCapability, PersistentSearch
from .visual import VisualServer
from .backend_turns import BackendTurnStore, TurnCancelled
from .presentation import PresentationStore
from .local_files import LocalFileCapability, LocalFileReader
from .turn_lifecycle import TurnCompletionStore
from .streaming_tts import StreamingTTSPipeline
from .web_tools import WebResearch
from .wayland_computer import WaylandComputerCapability
from .external_mcp import ExternalMcpServers
from .image_generation import ImageGeneration
from .shell import ShellCapability
from .runtime_self_knowledge import RuntimeSelfKnowledgeSync, collect_runtime_self_descriptions
from .working_memory import WorkingMemoryCleanupCoordinator


def _merge_hotwords(base: str, *extras: str) -> str:
    """Merge Whisper hotwords without growing the list on every browser turn."""

    words: list[str] = []
    seen: set[str] = set()
    for source in (base, *extras):
        for word in re.findall(r"[^\s,]+", source or ""):
            key = word.casefold()
            if key not in seen:
                seen.add(key)
                words.append(word)
    return " ".join(words)


def _wait_for_service_shutdown() -> None:
    """Wait without depending on stdin and translate process signals to cleanup."""
    shutdown = threading.Event()
    previous_handlers = {}

    def request_shutdown(signum, frame):
        shutdown.set()

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, request_shutdown)
    try:
        while not shutdown.wait(60):
            pass
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def _database(root: Path, cfg: dict) -> EveDatabase:
    paths = cfg.get("paths", {})
    runtime_telemetry_cfg = cfg.get("memory_runtime_telemetry", {})
    return EveDatabase(
        Path(paths.get("database", root / "data" / "eve.db")),
        lifecycle_audit=runtime_telemetry_cfg.get("lifecycle_audit", "required") == "required",
        lifecycle_max_detail_bytes=int(runtime_telemetry_cfg.get("max_detail_bytes", 4096)),
    )


def build(root: Path, cfg: dict, *, config_path: Path | None = None):
    paths = cfg.get("paths", {})
    runtime_path = Path(paths.get("runtime", root / "runtime"))
    bus = StateBus(runtime_path)
    presentations = PresentationStore(runtime_path)
    diagnostics = DiagnosticJournal(runtime_path)
    database = _database(root, cfg)
    llm = OpenAICompatibleLLM(cfg["llm"])
    runtime_telemetry_cfg = cfg.get("memory_runtime_telemetry", {})
    runtime_recorder = MemoryRuntimeRecorder(
        database, enabled=bool(runtime_telemetry_cfg.get("enabled", False)),
        contract_version=str(runtime_telemetry_cfg.get(
            "contract_version", "memory-runtime-events-v1",
        )),
        max_detail_bytes=int(runtime_telemetry_cfg.get("max_detail_bytes", 4096)),
    )
    retrieval_telemetry = MemoryRetrievalTelemetry(runtime_recorder)
    llm.memory_context_telemetry = LLMContextTelemetry(runtime_recorder)
    memory_compiler = MemoryCompiler(database, diagnostics)
    embedding_config = cfg.get("memory_search", {})
    embedding_client = create_embedding_client(embedding_config, root)
    memory = MemoryV2Runtime(database, memory_compiler, telemetry=retrieval_telemetry,
                             embedding_client=embedding_client)
    conversations = ConversationStore(database)
    work_tasks = ProviderMcpCapability("work_tasks", root, database=database.path)
    local_search = LocalSearchCapability(PersistentSearch(database, memory_runtime=memory), llm)
    config_path = (config_path or default_config_path(root)).resolve()

    def current_file_roots() -> list[str]:
        try:
            return list(load_config(config_path)[1].get("local_files", {}).get("roots", []))
        except (ConfigError, OSError):
            return list(cfg.get("local_files", {}).get("roots", []))

    local_files = LocalFileCapability(LocalFileReader(current_file_roots), llm)
    web_cfg = cfg.get("web", {})
    web = WebResearch(web_cfg) if web_cfg.get("enabled", False) else None
    ha_cfg = cfg.get("home_assistant", {})
    home_assistant = HomeAssistant(
        ha_cfg, root, lambda: memory.device_aliases(consumer="home_assistant"),
    ) if ha_cfg.get("enabled", False) else None
    if home_assistant is not None:
        home_assistant.action_memory_telemetry = ActionProvenanceTelemetry(runtime_recorder)
    # The executor is registered after the complete EVE turn path exists.  A
    # due schedule must never race startup and fail merely because the model
    # callback has not been bound yet.
    reminders = ScheduledTasks(database, home_assistant, start_monitor=False)
    network_cfg = cfg.get("network_tools", {})
    network_tools = LocalNetworkTools(network_cfg) if network_cfg.get("enabled", False) else None
    shell = ShellCapability(cfg.get("shell", {}), root)
    wayland_cfg = cfg.get("wayland_computer", {})
    wayland_computer = WaylandComputerCapability(wayland_cfg, root) if wayland_cfg.get("enabled", False) else None
    nova_cfg = cfg.get("nova_maintenance", {})
    nova_maintenance = (
        ProviderMcpCapability("nova", root, config_path=config_path)
        if nova_cfg.get("enabled", False)
        else None
    )
    agent = EveAgent(
        "EVE",
        memory,
        llm,
        bus,
        web,
        home_assistant,
        reminders,
        network_tools,
        nova_maintenance,
        diagnostics,
        conversations,
        presentations,
        work_tasks=work_tasks,
        local_search=local_search,
        local_files=local_files,
        semantic_similarity=cfg.get("semantic_similarity", {}),
        semantic_composition=cfg.get("semantic_composition", {}),
        external_mcp=ExternalMcpServers(cfg.get("mcp", {}), root),
        image_generation=ImageGeneration(cfg["image_generation"], root) if cfg["image_generation"]["enabled"] else None,
        wayland_computer=wayland_computer,
        shell=shell,
    )
    agent.work_task_store = WorkTaskStore(database)
    agent.memory_learning = ProductiveLearningPipeline(database, llm, diagnostics, semantic_links=agent.semantic_links)
    agent.working_memory_cleanup = WorkingMemoryCleanupCoordinator(
        database, cfg.get("working_memory", {}),
    )
    agent.home_assistant_inventory = (
        HomeAssistantInventory(home_assistant, database) if home_assistant is not None else None
    )
    training_adapters = [
        HomeAssistantTrainingAdapter(
            database, memory.home_assistant_memory,
            home_assistant=home_assistant, inventory=agent.home_assistant_inventory,
        )
    ]
    agent.training_packages = TrainingPackageManager(training_adapters)
    agent.memory_compiler = memory_compiler
    agent.memory_runtime_telemetry = retrieval_telemetry
    runtime_sync = RuntimeSelfKnowledgeSync(database, diagnostics)
    agent.runtime_self_knowledge_sync = runtime_sync
    try:
        agent.runtime_self_knowledge_report = runtime_sync.sync(
            collect_runtime_self_descriptions(agent)
        )
    except Exception as exc:
        agent.runtime_self_knowledge_report = {"status": "error", "error": type(exc).__name__}
        diagnostics.record(
            "runtime_self_knowledge", "startup_sync", "error",
            "Runtime-Self-Knowledge konnte beim Start nicht synchronisiert werden.",
            exception=exc,
        )
    return bus, llm, memory, agent, reminders


def doctor(root: Path, cfg: dict, *, config_path: Path | None = None) -> int:
    config_path = (config_path or default_config_path(root)).resolve()
    print(f"EVE root: {root}")
    llm = OpenAICompatibleLLM(cfg["llm"])
    models = llm.models()
    print(f"LLM: {'OK – ' + ', '.join(models) if models else 'NICHT ERREICHBAR – konfigurierten Modellserver prüfen'}")
    try:
        devices = Recorder.devices()
        print("Audio inputs:")
        for item in devices:
            if item["inputs"]: print(f"  [{item['id']}] {item['name']} ({item['inputs']} ch)")
        needle = cfg["audio"].get("input_device_contains", "").casefold()
        print("Mikrofon: " + ("OK" if any(x["inputs"] and needle in x["name"].casefold() for x in devices) else "NICHT GEFUNDEN/ANGESCHLOSSEN"))
    except Exception as exc: print(f"Audio: FEHLER – {exc}")
    tts = cfg.get("text_to_speech", {})
    if tts.get("engine", "piper") in {"auto", "piper"}:
        voice = Path(tts.get("data_dir", root / "voices")) / (tts.get("voice", "de_DE-eve-medium") + ".onnx")
        print("Piper-Stimme: " + ("OK" if voice.is_file() and voice.with_suffix(".onnx.json").is_file() else "NICHT GEFUNDEN"))
    else:
        print("TTS-Engine: " + str(tts.get("engine")) + " (externer Sprachdienst)")
    paths = cfg.get("paths", {})
    database = _database(root, cfg)
    memory = MemoryV2Runtime(database, MemoryCompiler(database))
    print(f"Memory: OK – {len(memory.list_memories(200))} aktive Claims")
    nova_cfg = cfg.get("nova_maintenance", {})
    if nova_cfg.get("enabled", False):
        nova = ProviderMcpCapability("nova", root, config_path=config_path)
        try:
            contract = nova.minimal_contract()
            status = contract.get("execution", {})
            print("Nova-EVE (MCP): " + (f"OK – {status['command']}" if status.get("available") else
                  "NICHT BEREIT – " + str(status.get("message") or contract.get("error"))))
        finally:
            nova.close_all()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eve")
    parser.add_argument(
        "command", nargs="?",
        choices=["run", "serve", "text", "doctor", "memory-status",
                 "memory-maintenance", "memory-maintenance-report",
                 "semantic-links", "semantic-confirm", "semantic-reject", "semantic-maintenance"],
        default="run",
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-tts", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--finding-id")
    parser.add_argument("--link-id")
    parser.add_argument("--source-ref")
    parser.add_argument("--supersedes")
    parser.add_argument("--context-independent", action="store_true")
    args = parser.parse_args(argv)
    args.config = args.config or default_config_path()
    root, cfg = load_config(args.config)
    for path in cfg.get("storage", {}).values():
        Path(path).mkdir(parents=True, exist_ok=True)
    for line in config_status(cfg):
        print(f"[Config] {line}")
    if args.command.startswith("semantic-"):
        from .semantic_links import SemanticLinks
        paths = cfg.get("paths", {})
        links = SemanticLinks(_database(root, cfg))
        if args.command not in {"semantic-links", "semantic-maintenance"}:
            if not args.link_id or not args.source_ref:
                parser.error("--link-id and --source-ref are required for explicit decisions")
            links.decide(args.link_id, confirmed=args.command == "semantic-confirm",
                         source_ref=args.source_ref, supersedes=args.supersedes,
                         context_independent=args.context_independent)
        print(json.dumps(links.maintenance_report() if args.command == "semantic-maintenance" else links.export(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "doctor": return doctor(root, cfg, config_path=args.config)
    if args.command in {"memory-status", "memory-maintenance", "memory-maintenance-report"}:
        paths = cfg.get("paths", {})
        database = _database(root, cfg)
        if args.command == "memory-maintenance":
            result = MemoryMaintenance(database).start()
        elif args.command == "memory-maintenance-report":
            maintenance = MemoryMaintenance(database)
            if args.finding_id:
                result = maintenance.finding(args.finding_id)
            elif args.run_id:
                result = maintenance.run(args.run_id)
            else:
                result = {"runs": maintenance.runs()}
        else:
            with database.connect() as connection:
                result = {
                    "memory": "v2", "schema_version": connection.execute("PRAGMA user_version").fetchone()[0],
                    "active_claims": connection.execute(
                        "SELECT count(*) FROM memory_claims WHERE lifecycle='active'"
                    ).fetchone()[0],
                    "historical_claims": connection.execute(
                        "SELECT count(*) FROM memory_claims WHERE lifecycle IN ('retired','invalid')"
                    ).fetchone()[0],
                    "integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0],
                    "foreign_key_violations": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
                }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    bus, llm, memory, agent, reminders = build(root, cfg, config_path=args.config)
    diagnostics = getattr(agent, "diagnostics", None)
    telemetry = TurnTelemetry()
    llm.telemetry = telemetry
    agent.telemetry = telemetry
    conversations = getattr(agent, "conversations", None)
    recorder, transcriber, speaker = Recorder(cfg["audio"]), Transcriber(cfg["speech_to_text"]), Speaker(cfg["text_to_speech"], root)
    turn_lock = threading.Lock()
    tts_lock = threading.Lock()
    # One bounded P1/P2 executor, with exactly enough workers for the two
    # independent post-turn branches. Piper remains serialized by tts_lock.
    post_turn_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="eve-post-turn")
    # Waiting for audio/presentation completion must not occupy the sole
    # executor that starts interactive turns. Otherwise a slow post-process
    # leaves every following message in ``queued`` even though the agent and
    # model are idle.
    turn_completion_executor = ThreadPoolExecutor(
        max_workers=4, thread_name_prefix="eve-turn-completion",
    )
    productive_learning = getattr(agent, "memory_learning", None)
    conversation_learning = (
        ConversationLearningCoordinator(
            productive_learning.database, productive_learning,
            cfg.get("conversation_learning", {}), diagnostics,
        )
        if productive_learning is not None else None
    )
    agent.conversation_learning = conversation_learning
    turn_results = TurnCompletionStore(limit=20)
    tts_cfg = cfg["text_to_speech"]
    base_hotwords = str(cfg["speech_to_text"].get("hotwords", ""))

    def speech_text(text: str) -> str:
        """Create the complete spoken form without silently truncating it."""
        spoken = llm.sanitize_for_speech(text)
        if tts_cfg.get("llm_rewrite", False):
            try:
                spoken = llm.sanitize_for_speech(llm.prepare_for_speech(spoken))
            except LocalLLMError as exc:
                print(f"[TTS] Sprachumschreibung fehlgeschlagen ({exc}); verwende Originalfassung")
        return spoken

    def remember_turn_failure(exc, turn_id=None, text="", conversation_id=None):
        working = (getattr(agent, "_working_memory_context", None)
                   if getattr(agent, "_trace_id", None) == (turn_id or telemetry.active_id()) else None)
        report = failure_report(
            exc, turn_id=turn_id or telemetry.active_id(), input_text=text,
            conversation_id=conversation_id or getattr(agent, "conversation_id", None),
            tool_events=(getattr(agent, "_tool_events", [])
                         if getattr(agent, "_trace_id", None) == (turn_id or telemetry.active_id()) else []),
            working_activity=working.get("activity") if working else None,
        )
        if working:
            report["working_memory"] = dict(working)
        exc.turn_failure_report = report
        if conversations is not None and report["conversation_id"]:
            try:
                conversations.record_failure(report["conversation_id"], report)
            except Exception as persist_error:
                agent._diagnostic("turn", "persist_failure", "error",
                                  "Fehlerbericht konnte nicht gespeichert werden", exception=persist_error)
        return report

    def browser_response(
        utterance: str,
        images: list[str] | None = None,
        conversation_id: str | None = None,
        on_chunk=None,
        on_preview=None,
        on_preview_reset=None,
        early_tts: StreamingTTSPipeline | None = None,
        synthesize_audio: bool = True,
    ) -> dict:
        if conversation_learning is not None:
            conversation_learning.note_activity()
        shadow_learning = getattr(agent, "shadow_learning", None)
        if shadow_learning is not None:
            shadow_learning.prioritize_interactive_turn()
        memory_compiler = getattr(agent, "memory_compiler", None)
        if memory_compiler is not None:
            memory_compiler.prioritize_interactive_turn()
        telemetry.start(conversation_id=conversation_id or getattr(agent, "conversation_id", None), input_kind="text")
        turn_started = time.perf_counter()
        print(f"\nDu> {utterance or '[Screenshot]'}")
        streaming = getattr(llm, "stream_answers", None)
        published_chunks: list[str] = []
        first_text_chunk = False
        answer_committed = False

        def note_visible_chunk(chunk: str, *, provisional: bool) -> None:
            nonlocal first_text_chunk
            if not chunk:
                return
            if not first_text_chunk:
                first_text_chunk = True
                first_chunk_ms = telemetry.elapsed_ms()
                telemetry.event(
                    "response", "first_text_chunk", start_ms=first_chunk_ms, duration_ms=0,
                    details={"chars": len(chunk)},
                )
                telemetry.summary(
                    first_text_chunk_ms=(
                        None if first_chunk_ms is None else round(first_chunk_ms, 2)
                    ),
                )

        def publish_preview(chunk: str) -> None:
            note_visible_chunk(chunk, provisional=True)
            if on_preview:
                on_preview(chunk)

        def publish_chunk(chunk: str) -> None:
            nonlocal answer_committed
            if not chunk:
                return
            published_chunks.append(chunk)
            note_published = getattr(agent, "note_published_answer_delta", None)
            if note_published:
                note_published(chunk)
            note_visible_chunk(chunk, provisional=False)
            if not answer_committed:
                answer_committed = True
                committed_ms = telemetry.elapsed_ms()
                telemetry.summary(answer_committed_at=(
                    None if committed_ms is None else round(committed_ms, 2)
                ))
            if on_chunk:
                on_chunk(chunk)
            if early_tts:
                early_tts.feed(chunk)

        answer_redactor = RedactedTextStream(publish_chunk)
        preview_redactor = RedactedTextStream(publish_preview)

        def reset_preview():
            preview_redactor.reset()
            if on_preview_reset:
                on_preview_reset()

        stream_callback = answer_redactor.feed if on_chunk or early_tts else None
        stream_context = streaming(stream_callback) if streaming and stream_callback else nullcontext()
        preview_stream = getattr(llm, "stream_tool_previews", None)
        preview_context = (
            preview_stream(preview_redactor.feed, reset_preview)
            if callable(preview_stream) and on_preview else nullcontext()
        )
        publication_context = getattr(agent, "published_answer_stream", None)
        publication_context = publication_context() if publication_context else nullcontext([])
        try:
            with publication_context, stream_context, preview_context:
                result = agent.respond_turn(utterance, images, conversation_id)
                # Unpublished preview text is supplied by the canonical answer.
                # Flushing it here would duplicate the final line after commit.
                preview_redactor.reset()
                answer_redactor.finish()
                # This collector lives at the actual publication boundary. The
                # agent's optional instrumentation is not the stream itself.
                suffix = unpublished_suffix(published_chunks, result.answer)
                if suffix:
                    publish_chunk(suffix)
        finally:
            if early_tts:
                early_tts.close()
            stream_end_ms = telemetry.elapsed_ms()
            telemetry.event(
                "response", "text_stream_end", start_ms=stream_end_ms, duration_ms=0,
            )
            telemetry.summary(
                text_stream_end_ms=None if stream_end_ms is None else round(stream_end_ms, 2),
            )
        answer = result.answer
        print(f"EVE> {answer}")
        answer_ready_ms = telemetry.elapsed_ms()
        telemetry.summary(answer_ready_ms=None if answer_ready_ms is None else round(answer_ready_ms, 2))
        response_started = time.perf_counter()
        response_start_ms = telemetry.elapsed_ms()
        spoken_answer, artifacts = extract_artifacts(answer, utterance)
        for resource in result.resources:
            if resource.get("type") == "file" and isinstance(resource.get("content"), str):
                header, separator, encoded = resource["content"].partition(";base64,")
                if separator and header.startswith("data:"):
                    artifacts.append({"filename": resource.get("filename") or "eve-download.bin",
                                      "mime": header[5:], "base64": encoded})
        if artifacts and conversations and result.conversation_id and result.assistant_message_id:
            conversations.store_artifacts(
                result.conversation_id, result.assistant_message_id, artifacts,
            )
        tts_answer = re.sub(r"\s*\[\d+\]", "", spoken_answer)
        telemetry.event(
            "response", "prepare",
            duration_ms=(time.perf_counter() - response_started) * 1000,
            start_ms=response_start_ms,
            details={"answer_chars": len(answer), "speech_chars": len(spoken_answer), "artifacts": len(artifacts)},
        )
        turn_results.register(
            result.turn_id,
            result.conversation_id,
            presentation=result.presentation is not None,
            audio=synthesize_audio and not args.no_tts and bool(tts_answer),
        )
        text_sent_ms = telemetry.elapsed_ms()
        telemetry.event("response", "text_sent", start_ms=text_sent_ms, duration_ms=0)
        telemetry.summary(
            text_sent_ms=None if text_sent_ms is None else round(text_sent_ms, 2),
            answer_chars=len(answer), speech_chars=len(spoken_answer), sources=len(result.sources),
        )
        bus.set("idle")

        def finish_post_turn_if_ready(completed_now: bool) -> None:
            if not completed_now:
                return
            completion = turn_results.get(result.turn_id)
            presentation_timing = completion.get("presentation", {})
            audio_timing = completion.get("audio", {})
            starts = [
                value for value in (
                    presentation_timing.get("start_ms"), audio_timing.get("start_ms"),
                ) if isinstance(value, (int, float))
            ]
            ends = [
                value for value in (
                    presentation_timing.get("ready_ms"), audio_timing.get("ready_ms"),
                ) if isinstance(value, (int, float))
            ]
            overlap_ms = 0.0
            if all(isinstance(value, (int, float)) for value in (
                presentation_timing.get("start_ms"), presentation_timing.get("ready_ms"),
                audio_timing.get("start_ms"), audio_timing.get("ready_ms"),
            )):
                overlap_ms = max(0.0, min(
                    presentation_timing["ready_ms"], audio_timing["ready_ms"],
                ) - max(
                    presentation_timing["start_ms"], audio_timing["start_ms"],
                ))
            full_ms = telemetry.elapsed_ms()
            telemetry.summary(
                complete_ms=None if full_ms is None else round(full_ms, 2),
                full_turn_completion_ms=None if full_ms is None else round(full_ms, 2),
                backend_status="completed",
                postprocess_overlap_ms=round(overlap_ms, 2),
                postprocess_first_start_ms=round(min(starts), 2) if starts else None,
                postprocess_last_ready_ms=round(max(ends), 2) if ends else None,
            )
            telemetry.finish(details={
                "turn_wall_ms": round((time.perf_counter() - turn_started) * 1000, 2),
            })

        def complete_presentation() -> None:
            with telemetry.bind(result.turn_id):
                presentation_start_ms = telemetry.elapsed_ms()
                rounded_start = None if presentation_start_ms is None else round(presentation_start_ms, 2)
                telemetry.event("presentation", "start", start_ms=presentation_start_ms, duration_ms=0)
                telemetry.summary(
                    presentation_start_ms=rounded_start,
                    presentation_start_after_answer_ms=(
                        None if rounded_start is None or answer_ready_ms is None
                        else round(rounded_start - answer_ready_ms, 2)
                    ),
                )
                try:
                    presentation_result = (
                        agent.run_presentation(result.presentation)
                        if result.presentation is not None
                        else {"turn_id": result.turn_id, "status": "skipped"}
                    )
                except Exception as exc:
                    agent._diagnostic(
                        "presentation", "post_turn", "error",
                        "Nachgelagerte Präsentation fehlgeschlagen", exception=exc,
                    )
                    presentation_result = {
                        "turn_id": result.turn_id, "status": "error",
                        "error": type(exc).__name__,
                    }
                presentation_ready_ms = telemetry.elapsed_ms()
                presentation_result.update({
                    "start_ms": rounded_start,
                    "ready_ms": None if presentation_ready_ms is None else round(presentation_ready_ms, 2),
                })
                telemetry.summary(presentation_ready_ms=presentation_result["ready_ms"])
                completed_now = turn_results.update(
                    result.turn_id, "presentation", presentation_result,
                )
                finish_post_turn_if_ready(completed_now)

        def complete_audio() -> None:
            with telemetry.bind(result.turn_id):
                audio_start_ms = telemetry.elapsed_ms()
                rounded_start = None if audio_start_ms is None else round(audio_start_ms, 2)
                if early_tts is None:
                    telemetry.event("tts", "start", start_ms=audio_start_ms, duration_ms=0)
                    telemetry.summary(
                        tts_start_ms=rounded_start,
                        tts_start_after_answer_ms=(
                            None if rounded_start is None or answer_ready_ms is None
                            else round(rounded_start - answer_ready_ms, 2)
                        ),
                    )
                audio_result = {"turn_id": result.turn_id, "status": "skipped"}
                if early_tts is not None:
                    pipeline_result = early_tts.future.result()
                    rounded_start = getattr(early_tts, "start_ms", rounded_start)
                    audio_ready_ms = telemetry.elapsed_ms()
                    audio_result = {
                        "turn_id": result.turn_id,
                        **pipeline_result,
                        "start_ms": rounded_start,
                        "ready_ms": None if audio_ready_ms is None else round(audio_ready_ms, 2),
                    }
                    telemetry.summary(
                        audio_ready_ms=audio_result["ready_ms"],
                        tts_segment_count=pipeline_result.get("segments"),
                    )
                elif synthesize_audio and not args.no_tts and tts_answer:
                    try:
                        speech_started = time.perf_counter()
                        speech_start_ms = telemetry.elapsed_ms()
                        prepared_tts = speech_text(tts_answer)
                        telemetry.event(
                            "tts", "prepare_text",
                            duration_ms=(time.perf_counter() - speech_started) * 1000,
                            start_ms=speech_start_ms, details={"chars": len(prepared_tts)},
                        )
                        print(f"EVE (gesprochen)> {prepared_tts}")
                        audio_bytes = b""
                        if prepared_tts:
                            tts_started = time.perf_counter()
                            tts_start_ms = telemetry.elapsed_ms()
                            with tts_lock:
                                audio_bytes = speaker.synthesize(prepared_tts)
                            chunks = Speaker.split_piper_text(
                                prepared_tts, int(tts_cfg.get("piper_chunk_chars", 700)),
                            )
                            audio_duration_ms = None
                            try:
                                with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
                                    audio_duration_ms = round(
                                        wav.getnframes() / wav.getframerate() * 1000, 2,
                                    )
                            except (EOFError, wave.Error, ZeroDivisionError):
                                pass
                            telemetry.event(
                                "tts", "synthesize",
                                duration_ms=(time.perf_counter() - tts_started) * 1000,
                                start_ms=tts_start_ms,
                                details={
                                    "engine": tts_cfg.get("engine", "auto"),
                                    "chunks": len(chunks),
                                    "chunk_chars": [len(chunk) for chunk in chunks],
                                    "audio_bytes": len(audio_bytes),
                                    "audio_duration_ms": audio_duration_ms,
                                },
                            )
                        audio_ready_ms = telemetry.elapsed_ms()
                        audio_result = {
                            "turn_id": result.turn_id,
                            "status": "success",
                            "start_ms": rounded_start,
                            "ready_ms": None if audio_ready_ms is None else round(audio_ready_ms, 2),
                            "audio_wav_base64": base64.b64encode(audio_bytes).decode("ascii"),
                        }
                        telemetry.summary(audio_ready_ms=audio_result["ready_ms"])
                    except Exception as exc:
                        agent._diagnostic(
                            "text_to_speech", "synthesize", "error",
                            "Browser-Audio fehlgeschlagen", exception=exc,
                        )
                        audio_result = {
                            "turn_id": result.turn_id, "status": "error",
                            "error": type(exc).__name__, "start_ms": rounded_start,
                            "ready_ms": telemetry.elapsed_ms(),
                        }
                        telemetry.summary(audio_ready_ms=audio_result["ready_ms"])
                        print(f"[TTS] Browser-Audio fehlgeschlagen: {exc}")
                else:
                    audio_ready_ms = telemetry.elapsed_ms()
                    audio_result.update({
                        "start_ms": rounded_start,
                        "ready_ms": None if audio_ready_ms is None else round(audio_ready_ms, 2),
                    })
                    telemetry.summary(audio_ready_ms=audio_result["ready_ms"])
                completed_now = turn_results.update(result.turn_id, "audio", audio_result)
                finish_post_turn_if_ready(completed_now)

        def complete_shadow_learning() -> None:
            if shadow_learning is None:
                return
            with telemetry.bind(result.turn_id):
                started = time.perf_counter()
                start_ms = telemetry.elapsed_ms()
                telemetry.event(
                    "shadow_learning", "start", start_ms=start_ms, duration_ms=0,
                )
                try:
                    shadow_learning.evaluate_turn(result.turn_id, shadow_priority_token)
                    telemetry.event(
                        "shadow_learning", "complete",
                        start_ms=start_ms,
                        duration_ms=(time.perf_counter() - started) * 1000,
                    )
                except Exception as exc:
                    agent._diagnostic(
                        "shadow_learning", "post_turn", "error",
                        "Nachgelagertes Shadow Learning fehlgeschlagen", exception=exc,
                    )

        def complete_memory_compiler() -> None:
            if memory_compiler is None:
                return
            for consumer in ("planner", "answer"):
                memory_compiler.compile_turn(
                    result.turn_id, consumer,
                    expected_priority_generation=compiler_priority_token,
                    queued_at_monotonic=compiler_queued_at,
                )

        try:
            shadow_priority_token = shadow_learning.priority_token() if shadow_learning is not None else None
            compiler_priority_token = memory_compiler.priority_token() if memory_compiler is not None else None
            compiler_queued_at = time.perf_counter()
            post_turn_executor.submit(complete_presentation)
            post_turn_executor.submit(complete_audio)
            if shadow_learning is not None:
                post_turn_executor.submit(complete_shadow_learning)
            if conversation_learning is not None:
                # Acceptance is synchronous and durable; semantic work remains
                # after the visible answer and survives process restart.
                conversation_learning.accept_turn(result.turn_id)
                accepted_ms = telemetry.elapsed_ms()
                telemetry.event(
                    "memory_learning", "accepted",
                    start_ms=accepted_ms, duration_ms=0,
                )
            if memory_compiler is not None:
                post_turn_executor.submit(complete_memory_compiler)
        except RuntimeError:
            with telemetry.bind(result.turn_id):
                telemetry.finish(status="error", details={"error": "post_turn_executor_unavailable"})
            raise
        return {
            "turn_id": result.turn_id,
            "transcript": utterance,
            # The completion must match the chat stream exactly. Speech and
            # artifact extraction use their own derived representation.
            "answer": answer,
            "sources": list(result.sources),
            "artifacts": artifacts,
            "audio_wav_base64": "",
            "postprocess_status": "pending",
            "postprocess_url": f"/api/turn-results/{result.turn_id}",
            "conversation_id": result.conversation_id,
            "assistant_message_id": result.assistant_message_id,
            "resources": [
                {key: resource[key] for key in ("type", "content", "filename", "media_type") if key in resource}
                for resource in result.resources
                if resource.get("type") in {"image", "file"} and isinstance(resource.get("content"), str)
                and (resource["content"].startswith("data:image/") if resource.get("type") == "image" else resource["content"].startswith("data:"))
            ],
            "presentation_pending": result.presentation is not None,
        }

    def execute_scheduled_eve_turn(action: dict) -> dict:
        request = str(action.get("request") or "").strip()
        if not request:
            raise ValueError("Geplanter EVE-Auftrag ist leer")
        conversation_id = action.get("conversation_id")
        previous_conversation_id = getattr(agent, "conversation_id", None)
        with turn_lock:
            try:
                telemetry.start(
                    conversation_id=conversation_id or previous_conversation_id,
                    input_kind="scheduled", new_turn=True,
                )
                bus.set("thinking", "Geplante Aufgabe wird ausgeführt …")
                from contextlib import nullcontext
                from .scheduled_execution import scheduled_execution, ensure_scheduled_deadline
                ensure_scheduled_deadline(action)
                context = action.get("execution_context")
                with scheduled_execution(action), (chatto_bridge.scheduled_access(context) if context else nullcontext()):
                    response = browser_response(request, conversation_id=conversation_id)
            except Exception as exc:
                remember_turn_failure(exc, text=request, conversation_id=conversation_id)
                agent._diagnostic(
                    "scheduled_tasks", "execute", "error",
                    "Geplanter EVE-Turn fehlgeschlagen", exception=exc,
                )
                bus.set("idle")
                telemetry.finish(status="error", details={"error": type(exc).__name__})
                raise
            finally:
                if previous_conversation_id and agent.conversation_id != previous_conversation_id:
                    agent.prepare_conversation_view(previous_conversation_id)
        target = action.get("output_target") or {}
        output_conversation = response.get("conversation_id")
        if target.get("transport") == "eve" and target.get("conversation_id") and target["conversation_id"] != output_conversation:
            output_conversation = target["conversation_id"]
            conversations.get(output_conversation)
            from .scheduled_execution import scheduled_execution, input_metadata
            with scheduled_execution(action):
                copied_metadata = input_metadata()
            conversations.append_turn(output_conversation, request, response["answer"],
                user_metadata={**copied_metadata, "context_copy": True, "origin_turn_id": response.get("turn_id"), "scheduled_task_id": action.get("task_id")},
                assistant_metadata={"context_copy": True, "origin_turn_id": response.get("turn_id")},
                assistant_attachments=response.get("resources", []))
        return {
            "notification": {
                "message": response["answer"], "kind": "scheduled_result", "delivered": False,
                "persisted": True, "conversation_id": output_conversation,
                "turn_id": response.get("turn_id"), "task_id": action.get("task_id"),
            },
            "resources": response.get("resources", []),
            "turn": {
                "turn_id": response.get("turn_id"), "conversation_id": response.get("conversation_id"),
                "assistant_message_id": response.get("assistant_message_id"),
            },
        }

    register_scheduled_executor = getattr(reminders, "register_executor", None)
    if callable(register_scheduled_executor):
        register_scheduled_executor("eve_turn", execute_scheduled_eve_turn)
    start_scheduler = getattr(reminders, "start", None)

    def browser_turn(audio_path: Path, conversation_id: str | None = None) -> dict:
        if not turn_lock.acquire(blocking=False):
            raise RuntimeError("EVE verarbeitet bereits eine Eingabe")
        utterance = ""
        try:
            telemetry.start(conversation_id=conversation_id or getattr(agent, "conversation_id", None), input_kind="voice", new_turn=True)
            bus.set("thinking", "Transkription")
            aliases = ", ".join(alias for alias, _ in memory.device_aliases(
                consumer="stt", telemetry_context={
                    "trace_id": telemetry.active_id(),
                    "turn_id": telemetry.active_id(),
                    "conversation_id": conversation_id or getattr(agent, "conversation_id", None),
                },
            ).values())
            transcriber.config["hotwords"] = _merge_hotwords(base_hotwords, aliases)
            stt_started = time.perf_counter()
            utterance = transcriber.transcribe(audio_path)
            telemetry.event("stt", "transcribe", duration_ms=(time.perf_counter() - stt_started) * 1000,
                            details={"audio_bytes": audio_path.stat().st_size, "text": utterance})
            if not utterance:
                raise RuntimeError("Keine Sprache erkannt")
            return browser_response(utterance, conversation_id=conversation_id)
        except TurnCancelled:
            bus.set("idle")
            telemetry.summary(
                backend_status="cancelled", cancel_requested=True,
                cancel_requested_ms=telemetry.elapsed_ms(),
            )
            telemetry.finish(status="cancelled")
            raise
        except Exception as exc:
            remember_turn_failure(exc, text=utterance, conversation_id=conversation_id)
            agent._diagnostic("speech_to_text", "transcribe", "error", "Transkription fehlgeschlagen", exception=exc)
            bus.set("idle")
            telemetry.finish(status="error", details={"error": type(exc).__name__})
            raise
        finally:
            turn_lock.release()

    def browser_message(
        text: str, images: list[str], conversation_id: str | None = None, on_chunk=None,
        backend_turn_id: str | None = None, cancellation=None,
        on_preview=None, on_preview_reset=None,
        early_tts: StreamingTTSPipeline | None = None, synthesize_audio: bool = True,
    ) -> dict:
        if not turn_lock.acquire(blocking=False):
            raise RuntimeError("EVE verarbeitet bereits eine Eingabe")
        try:
            telemetry.start(
                conversation_id=conversation_id or getattr(agent, "conversation_id", None),
                input_kind="image" if images else "text", turn_id=backend_turn_id, new_turn=True,
            )
            if backend_turn_id:
                telemetry.summary(backend_turn_id=backend_turn_id, backend_status="running")
            bus.set("thinking", "Text und Screenshots werden betrachtet …")
            agent_context = agent.cancellable(cancellation) if cancellation else nullcontext()
            llm_context = llm.cancellable(cancellation) if cancellation else nullcontext()
            with agent_context, llm_context:
                return browser_response(
                    text, images, conversation_id, on_chunk,
                    on_preview=on_preview, on_preview_reset=on_preview_reset,
                    early_tts=early_tts, synthesize_audio=synthesize_audio,
                )
        except TurnCancelled:
            bus.set("idle")
            telemetry.summary(
                backend_status="cancelled", cancel_requested=True,
                cancel_requested_ms=telemetry.elapsed_ms(),
            )
            telemetry.finish(status="cancelled")
            raise
        except Exception as exc:
            remember_turn_failure(exc, backend_turn_id, text, conversation_id)
            bus.set("idle")
            agent._diagnostic(
                "turn", "process", "error", "Text-Turn fehlgeschlagen",
                exception=exc,
            )
            telemetry.finish(status="error", details={"error": type(exc).__name__})
            raise
        finally:
            turn_lock.release()

    def create_streaming_tts(
        turn_id: str, store: BackendTurnStore,
    ) -> StreamingTTSPipeline | None:
        if args.no_tts:
            return None
        first_audio = threading.Event()
        first_segment = threading.Event()
        pipeline = None

        def segment_ready(segment: str, index: int) -> None:
            ready_ms = telemetry.elapsed_ms()
            telemetry.event(
                "tts", "segment_ready", start_ms=ready_ms, duration_ms=0,
                details={"index": index, "chars": len(segment)},
            )
            if not first_segment.is_set():
                first_segment.set()
                telemetry.summary(
                    tts_first_segment_ms=(
                        None if ready_ms is None else round(ready_ms, 2)
                    ),
                )

        def synthesize_segment(spoken: str) -> bytes:
            started = time.perf_counter()
            start_ms = telemetry.elapsed_ms()
            if getattr(pipeline, "start_ms", None) is None:
                pipeline.start_ms = None if start_ms is None else round(start_ms, 2)
                telemetry.event("tts", "start", start_ms=start_ms, duration_ms=0)
                telemetry.summary(tts_start_ms=pipeline.start_ms)
            telemetry.event("tts", "segment_start", start_ms=start_ms, duration_ms=0)
            with tts_lock:
                audio = speaker.synthesize(spoken)
            telemetry.event(
                "tts", "segment_synthesize",
                start_ms=start_ms,
                duration_ms=(time.perf_counter() - started) * 1000,
                details={"chars": len(spoken), "audio_bytes": len(audio)},
            )
            return audio

        def publish_segment(spoken: str, audio: bytes) -> None:
            ready_ms = telemetry.elapsed_ms()
            store.publish_audio(
                turn_id, spoken, base64.b64encode(audio).decode("ascii"),
            )
            if not first_audio.is_set():
                first_audio.set()
                telemetry.summary(
                    tts_first_segment_ready_ms=(
                        None if ready_ms is None else round(ready_ms, 2)
                    ),
                    first_audio_ready_ms=(
                        None if ready_ms is None else round(ready_ms, 2)
                    ),
                )

        pipeline = StreamingTTSPipeline(
            synthesize_segment,
            publish_segment,
            lambda: store.cancel_requested(turn_id),
            prepare=speech_text,
            on_segment=segment_ready,
        )

        def run_streaming_tts():
            with telemetry.bind(turn_id):
                return pipeline.run()

        pipeline.future = post_turn_executor.submit(run_streaming_tts)
        return pipeline

    def run_backend_turn(
        turn_id: str, text: str, images: list[str], conversation_id: str | None,
        store: BackendTurnStore,
    ) -> None:
        retry = store.snapshot(turn_id).get("retry_context")
        if retry:
            _text, report = resume_failure_request(conversations, conversation_id, retry)
            working = report.get('working_memory') or {}
            if working.get('workspace_id') and working.get('work_turn_id'):
                from .working_memory import WorkingMemoryStore
                with conversations.database.connect(lifecycle_audit=False) as connection:
                    source = connection.execute(
                        'SELECT workspace_id FROM memory_work_turns WHERE id=? AND conversation_id=? AND workspace_id=?',
                        (working['work_turn_id'], conversation_id, working['workspace_id']),
                    ).fetchone()
                if source is None:
                    raise ValueError('Arbeitsstand gehört nicht zum Fehlversuch')
                WorkingMemoryStore(conversations.database).open(conversation_id, workspace_id=source[0])
            conversations.record_retry(conversation_id, turn_id, retry["source_turn_id"], retry["correction"])
        early_tts = create_streaming_tts(turn_id, store)
        try:
            with llm.stream_reasoning(lambda chunk: store.append_reasoning(turn_id, chunk)):
                response = browser_message(
                    text, images, conversation_id, lambda chunk: store.append(turn_id, chunk), turn_id,
                    store.cancellation(turn_id),
                    on_preview=lambda chunk: store.append_answer_preview(turn_id, chunk),
                    on_preview_reset=lambda: store.clear_answer_preview(turn_id),
                    early_tts=early_tts,
                )
            persist_backend_reasoning(turn_id, store, response)
            store.set_response(turn_id, response)
            turn_completion_executor.submit(finalize_backend_turn, turn_id, store)
        except Exception:
            if early_tts:
                early_tts.cancel()
            raise

    def persist_backend_reasoning(
        turn_id: str, store: BackendTurnStore, response: dict,
    ) -> None:
        reasoning = str(store.snapshot(turn_id).get("reasoning") or "").strip()
        conversation_id = response.get("conversation_id")
        message_id = response.get("assistant_message_id")
        if not reasoning or conversations is None or not conversation_id or not message_id:
            return
        try:
            conversations.store_message_reasoning(conversation_id, message_id, reasoning)
            response["reasoning_available"] = True
        except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
            agent._diagnostic(
                "conversation", "store_reasoning", "error",
                "Gedankengang konnte nicht an der Antwort gespeichert werden",
                exception=exc,
            )

    def finalize_backend_turn(turn_id: str, store: BackendTurnStore) -> None:
        try:
            complete_backend_turn(turn_id, store)
        except Exception as exc:
            if store.cancel_requested(turn_id):
                store.finish_cancelled(turn_id)
                return
            snapshot = store.snapshot(turn_id)
            report = remember_turn_failure(exc, turn_id, snapshot.get("input_text") or snapshot.get("transcript") or "", snapshot.get("conversation_id"))
            store.update(
                turn_id, status="failed", error=report["reason"], failure_report=report, completed_at=time.time(),
            )

    def complete_backend_turn(turn_id: str, store: BackendTurnStore) -> None:
        # Text is already observable; backend ownership continues through the
        # existing Presentation/TTS completion barrier.
        deadline = time.monotonic() + 300
        completion = None
        while time.monotonic() < deadline:
            completion = turn_results.get(turn_id)
            if completion.get("status") == "complete":
                store.update(
                    turn_id, status="completed", completion=completion,
                    completed_at=time.time(),
                )
                return
            time.sleep(.05)
        raise TimeoutError("Turn-Nachbearbeitung wurde nicht abgeschlossen")

    backend_turns = BackendTurnStore(run_backend_turn, limit=20, max_workers=1)

    def start_backend_message(
        text: str, images: list[str], conversation_id: str | None,
        explicit_resume: bool = False, retry_context: dict | None = None,
    ) -> dict:
        lifecycle = agent.prepare_user_turn_view(
            conversation_id, explicit_resume=explicit_resume, reserve_resume=explicit_resume,
        )
        if retry_context is not None:
            text, _report = resume_failure_request(conversations, lifecycle['conversation_id'], retry_context)
        return backend_turns.start(text, images, lifecycle["conversation_id"], retry_context=retry_context)

    def start_backend_voice(
        audio_path: Path, conversation_id: str | None, explicit_resume: bool = False,
    ) -> dict:
        lifecycle = agent.prepare_user_turn_view(
            conversation_id, explicit_resume=explicit_resume, reserve_resume=explicit_resume,
        )
        conversation_id = lifecycle["conversation_id"]
        def run_voice(turn_id: str, store: BackendTurnStore) -> None:
            early_tts = None
            if not turn_lock.acquire(blocking=False):
                raise RuntimeError("EVE verarbeitet bereits eine Eingabe")
            try:
                telemetry.start(
                    conversation_id=conversation_id or getattr(agent, "conversation_id", None),
                    input_kind="voice", turn_id=turn_id, new_turn=True,
                )
                telemetry.summary(backend_turn_id=turn_id, backend_status="running")
                bus.set("thinking", "Transkription")
                aliases = ", ".join(alias for alias, _ in memory.device_aliases(
                    consumer="stt", telemetry_context={
                        "trace_id": telemetry.active_id(), "turn_id": turn_id,
                        "conversation_id": conversation_id,
                    },
                ).values())
                transcriber.config["hotwords"] = _merge_hotwords(base_hotwords, aliases)
                stt_started = time.perf_counter()
                utterance = transcriber.transcribe(audio_path)
                telemetry.event(
                    "stt", "transcribe",
                    duration_ms=(time.perf_counter() - stt_started) * 1000,
                    details={"audio_bytes": audio_path.stat().st_size, "text": utterance},
                )
                if not utterance:
                    raise RuntimeError("Keine Sprache erkannt")
                cancellation = store.cancellation(turn_id)
                cancellation.checkpoint()
                # This snapshot update is the single publication point for the
                # exact final text subsequently passed to the agent.
                store.update(turn_id, transcript=utterance)
                early_tts = create_streaming_tts(turn_id, store)
                with (
                    agent.cancellable(cancellation),
                    llm.cancellable(cancellation),
                    llm.stream_reasoning(lambda chunk: store.append_reasoning(turn_id, chunk)),
                ):
                    cancellation.checkpoint()
                    response = browser_response(
                        utterance, conversation_id=conversation_id,
                        on_chunk=lambda chunk: store.append(turn_id, chunk),
                        on_preview=lambda chunk: store.append_answer_preview(turn_id, chunk),
                        on_preview_reset=lambda: store.clear_answer_preview(turn_id),
                        early_tts=early_tts,
                    )
                persist_backend_reasoning(turn_id, store, response)
                store.set_response(turn_id, response)
            except TurnCancelled:
                if early_tts:
                    early_tts.cancel()
                bus.set("idle")
                telemetry.summary(
                    backend_status="cancelled", cancel_requested=True,
                    cancel_requested_ms=telemetry.elapsed_ms(),
                )
                telemetry.finish(status="cancelled")
                raise
            except Exception as exc:
                if early_tts:
                    early_tts.cancel()
                bus.set("idle")
                remember_turn_failure(exc, turn_id, store.snapshot(turn_id).get("transcript") or "", conversation_id)
                agent._diagnostic(
                    "speech_to_text", "transcribe", "error",
                    "Sprach-Turn fehlgeschlagen", exception=exc,
                )
                telemetry.finish(status="error", details={"error": type(exc).__name__})
                raise
            finally:
                turn_lock.release()
                audio_path.unlink(missing_ok=True)
            complete_backend_turn(turn_id, store)

        return backend_turns.start_task(conversation_id, run_voice)

    def backend_message_snapshot(turn_id: str, after_version: int | None = None) -> dict:
        if after_version is None:
            return backend_turns.snapshot(turn_id)
        return backend_turns.wait(turn_id, after_version, timeout=15)

    def cancel_backend_turn(turn_id: str) -> dict:
        return backend_turns.cancel(turn_id)

    def browser_telemetry(query: dict) -> dict:
        conversation_id = query.get("conversation_id", [None])[0]
        snapshot = telemetry.snapshot(conversation_id)
        from .semantic_inspector import turn_semantics
        for turn in snapshot['turns']:
            turn['semantic_learning'] = turn_semantics(turn)
        return snapshot

    def browser_turn_result(turn_id: str) -> dict:
        return turn_results.get(turn_id)

    def browser_notifications() -> dict:
        notifications = []
        for item in reminders.pop_due(limit=1):
            message = (
                f"Erinnerung: {item['message']}"
                if item.get("kind") == "reminder" else str(item["message"])
            )
            audio_b64 = ""
            if not args.no_tts:
                try:
                    spoken_message = llm.sanitize_for_speech(message)
                    with tts_lock:
                        audio_b64 = base64.b64encode(speaker.synthesize(spoken_message)).decode("ascii")
                except Exception as exc:
                    agent._diagnostic("text_to_speech", "notification", "error", "Erinnerungs-Audio fehlgeschlagen", exception=exc)
                    print(f"[TTS] Erinnerungs-Audio fehlgeschlagen: {exc}")
            notifications.append({**item, "message": message, "audio_wav_base64": audio_b64})
        return {"notifications": notifications}

    def browser_conversations(method: str, conversation_id: str | None, payload: dict, query: dict) -> tuple[int, dict]:
        if conversations is None:
            return 503, {"error": "Konversationsspeicher ist nicht verfügbar"}
        try:
            if method == "GET" and conversation_id is None:
                limit = int(query.get("limit", [50])[0])
                offset = int(query.get("offset", [0])[0])
                return 200, {"conversations": conversations.list(
                    limit=limit, offset=offset,
                    include_member_dms=chatto_bridge.config.get("show_member_dms_in_web", False),
                    include_owner_dms=chatto_bridge.config.get("show_owner_dms_in_web", True),
                    include_chatto_channels=chatto_bridge.config.get("show_channels_in_web", True),
                ), "active_id": agent.conversation_id}
            if method == "POST" and conversation_id is None:
                return 201, {"conversation": conversations.create(payload.get("title", "Neue Unterhaltung"))}
            if method == "POST" and conversation_id == "active":
                selected_id = payload.get("conversation_id")
                lifecycle = agent.prepare_conversation_view(selected_id)
                return 200, {"active_id": agent.conversation_id, "lifecycle": lifecycle}
            if not conversation_id:
                return 404, {"error": "Konversation wurde nicht gefunden"}
            if method == "GET":
                limit = int(query.get("limit", [100])[0])
                before_raw = query.get("before", [None])[0]
                before = int(before_raw) if before_raw is not None else None
                return 200, {"conversation": conversations.get(conversation_id),
                             "active_turn_id": backend_turns.active_for_conversation(conversation_id),
                             "failures": conversations.failures(conversation_id),
                             **conversations.messages(conversation_id, limit=limit, before=before)}
            if method == "PATCH":
                return 200, {"conversation": conversations.rename(conversation_id, payload.get("title", ""))}
            if method == "DELETE":
                conversations.delete(conversation_id)
                if agent.conversation_id == conversation_id:
                    agent.conversation_id = conversations.create()["id"]
                    agent.history = []
                return 200, {"deleted": True, "active_id": agent.conversation_id}
            return 405, {"error": "Methode ist nicht erlaubt"}
        except KeyError as exc:
            return 404, {"error": str(exc.args[0])}
        except (TypeError, ValueError) as exc:
            return 400, {"error": str(exc)}

    def browser_tasks(method: str, task_id: str | None, payload: dict, query: dict) -> tuple[int, dict]:
        try:
            if method == "GET" and task_id is None:
                include_finished = query.get("include_finished", ["false"])[0].casefold() == "true"
                limit = int(query.get("limit", [100])[0])
                return 200, {"tasks": reminders.list_tasks(include_finished=include_finished, limit=limit)}
            if method == "GET" and task_id:
                return 200, {"task": reminders.get_task(task_id)}
            if method == "PATCH" and task_id:
                return 200, {"task": reminders.update_task(task_id, payload)}
            if method == "DELETE" and task_id:
                reminders.delete_task(task_id)
                return 200, {"deleted": True}
            return 405, {"error": "Methode ist nicht erlaubt"}
        except KeyError as exc:
            return 404, {"error": str(exc.args[0])}
        except (TypeError, ValueError) as exc:
            return 400, {"error": str(exc)}

    work_store = getattr(agent, "work_task_store", None)

    def browser_work_lists(method: str, list_id: str | None, payload: dict, query: dict) -> tuple[int, dict]:
        if work_store is None:
            return 503, {"error": "Arbeitslistenspeicher ist nicht verfügbar"}
        if method == "GET" and list_id is None:
            return 200, {"lists": work_store.list_lists(
                include_archived=query.get("include_archived", ["false"])[0].casefold() == "true"
            )}
        if method == "POST" and list_id is None:
            if "items" in payload:
                return 201, {"list": work_store.create_list_with_items(
                    payload.get("name", ""), payload.get("items"), payload.get("description"),
                )}
            return 201, {"list": work_store.create_list(payload.get("name", ""), payload.get("description"))}
        if method == "GET" and list_id:
            return 200, {"list": work_store.get_list(list_id)}
        if method == "DELETE" and list_id:
            return 200, {"deleted": work_store.delete_list(list_id)}
        return 405, {"error": "Methode ist nicht erlaubt"}

    def browser_work_items(method: str, item_id: str | None, payload: dict, query: dict) -> tuple[int, dict]:
        if work_store is None:
            return 503, {"error": "Arbeitslistenspeicher ist nicht verfügbar"}
        if method == "GET" and item_id is None:
            status = query.get("status", ["open"])[0]
            status = None if status.casefold() == "all" else status
            search_query = query.get("q", [None])[0]
            items = (
                work_store.search_items(search_query, status=status)
                if search_query else work_store.list_items(
                    list_id=query.get("list_id", [None])[0], status=status,
                    limit=int(query.get("limit", [100])[0]),
                )
            )
            return 200, {"items": items}
        if method == "POST" and item_id is None:
            return 201, {"item": work_store.create_item(
                payload.get("list_id", ""), payload.get("title", ""), payload.get("description"),
                status=payload.get("status", "open"), metadata=payload.get("metadata"),
            )}
        if method == "GET" and item_id:
            return 200, {"item": work_store.get_item(item_id), "events": work_store.events(item_id)}
        if method == "PATCH" and item_id:
            if "position" in payload:
                if set(payload) - {"list_id", "position"}:
                    return 400, {"error": "Move akzeptiert nur list_id und position"}
                return 200, {"item": work_store.move_item(
                    item_id, payload.get("list_id", ""), payload.get("position")
                )}
            return 200, {"item": work_store.update_item(item_id, payload)}
        if method == "DELETE" and item_id:
            return 200, {"deleted": work_store.delete_item(item_id)}
        return 405, {"error": "Methode ist nicht erlaubt"}

    config_path = (args.config or default_config_path(root)).resolve()

    def browser_presentation(method: str, payload: dict) -> tuple[int, dict]:
        presentations = agent.presentations
        if method == "GET":
            return 200, presentations.client_state()
        if method == "POST":
            return 201, presentations.create(payload.get("presentation", payload))
        if method == "PATCH":
            return 200, presentations.update(str(payload.get("id", "")), payload.get("presentation"))
        if method == "DELETE":
            return 200, presentations.close(payload.get("id"))
        return 405, {"error": "Methode ist nicht erlaubt"}

    def browser_config(method: str, payload: dict) -> tuple[int, dict]:
        def with_chatto_status(result):
            status = chatto_process.status()
            result["chatto_status"] = status
            labels = {
                "home_assistant": "Home Assistant", "home_assistant_inventory": "Hausinventar",
                "local_search": "Lokale Suche", "local_files": "Lokale Dateien", "shell": "Shell",
                "nova": "Nova", "wayland_computer": "Desktop", "network": "Lokales Netzwerk",
                "scheduled_tasks": "Geplante Aufträge", "work_tasks": "Arbeitsaufträge",
                "assist_events": "Hausereignisse", "presentation": "Lokale Anzeige",
                "memory": "Gemeinsames Gedächtnis", "semantic_learning": "Bedeutungslernen",
                "working_memory": "Arbeitsgedächtnis", "web": "Webrecherche", "clock": "Uhrzeit",
                "image_generation": "Bildgenerierung",
                "calculator": "Rechner",
            }
            _, current_config = load_config(config_path)
            labels.update({"mcp_" + name: server.get("title") or name
                           for name, server in current_config.get("mcp", {}).get("servers", {}).items()})
            for section in result["sections"]:
                for field in section["fields"]:
                    if field["id"] == "chatto.channel_capabilities":
                        field["choices"] = [{"value": key, "label": label} for key, label in labels.items()]
                    if field["id"] in {"chatto.channel_ids", "chatto.channel_learning_ids"} and status.get("rooms"):
                        rooms = {room["id"]: room["name"] for room in status["rooms"]}
                        for identifier in field["value"]:
                            rooms.setdefault(identifier, identifier)
                        field["choices"] = [{"value": key, "label": label} for key, label in rooms.items()]
            return result
        try:
            if method == "GET":
                return 200, with_chatto_status(editable_config(config_path))
            if method == "PATCH":
                result = update_editable_config(config_path, payload)
                _, effective = load_config(config_path)
                chatto_bridge.configure(effective["chatto"])
                try:
                    chatto_process.configure(effective)
                except OSError:
                    return 503, {"error": "Konfiguration gespeichert, aber Chatto konnte nicht neu verbinden. Node-Programm prüfen."}
                agent_shell = getattr(agent, "shell", None)
                if agent_shell is not None:
                    shell_was_enabled = agent_shell.enabled
                    agent_shell.configure(effective.get("shell", {}))
                    sync = getattr(agent, "runtime_self_knowledge_sync", None)
                    if sync is not None and shell_was_enabled != agent_shell.enabled:
                        agent.runtime_self_knowledge_report = sync.sync(collect_runtime_self_descriptions(agent))
                if agent.semantic_links:
                    agent.semantic_links.configure_similarity(effective.get("semantic_similarity", {}))
                    agent.semantic_links.configure_composition(effective.get("semantic_composition", {}))
                if conversation_learning is not None:
                    conversation_learning.configure(effective.get("conversation_learning", {}))
                cleanup = getattr(agent, "working_memory_cleanup", None)
                if cleanup is not None:
                    cleanup.configure(effective.get("working_memory", {}))
                return 200, with_chatto_status(result)
            return 405, {"error": "Methode ist nicht erlaubt"}
        except ConfigError as exc:
            return 400, {"error": str(exc)}

    def browser_home_assistant_inventory() -> tuple[int, dict]:
        inventory = getattr(agent, "home_assistant_inventory", None)
        if inventory is None or not inventory.configured:
            return 503, {"error": "Home Assistant ist nicht verbunden"}
        try:
            return 200, {"inventory": inventory.run()}
        except Exception as exc:
            diagnostics.record(
                "home_assistant", "inventory", "error",
                "Die Home-Assistant-Inventur ist fehlgeschlagen.", exception=exc,
            )
            cause = redact_sensitive(str(exc)).strip()[:300]
            return 503, {"error": (
                "Home-Assistant-Inventur fehlgeschlagen"
                + (f": {cause}" if cause else ".")
            )}

    def browser_home_assistant_policy(method: str, payload: dict) -> tuple[int, dict]:
        provider_client = getattr(agent, "home_assistant", None)
        if provider_client is None or not provider_client.configured:
            return 503, {"error": "Home Assistant ist nicht verbunden"}
        try:
            provider = provider_client.semantic_provider_identity()
            if method == "GET":
                return 200, memory.home_assistant_policy_overview(provider)
            if method == "PATCH":
                if set(payload) != {"excluded_areas"}:
                    return 400, {"error": "Erwartet wird ausschließlich excluded_areas"}
                return 200, memory.set_home_assistant_aggregate_policy(
                    provider, payload["excluded_areas"], source_ref="ui:home-assistant-policy",
                )
            return 405, {"error": "Methode ist nicht erlaubt"}
        except Exception as exc:
            diagnostics.record(
                "home_assistant", "aggregate_policy", "error",
                "Die Home-Assistant-Bereichsregel konnte nicht verarbeitet werden.",
                exception=exc,
            )
            cause = redact_sensitive(str(exc)).strip()[:300]
            return 500, {"error": (
                "Home-Assistant-Bereichsregel konnte nicht verarbeitet werden"
                + (f": {cause}" if cause else ".")
            )}

    def browser_training_packages(method: str, payload: dict, query: dict) -> tuple[int, dict]:
        manager = getattr(agent, "training_packages", None)
        if manager is None:
            return 503, {"error": "Trainingspakete sind nicht verfügbar"}
        first = lambda key, default=None: (query.get(key) or [default])[0]
        try:
            if method == "GET":
                action = first("action", "overview")
                provider = first("provider")
                locale = first("locale", "de")
                if action == "overview":
                    return 200, manager.overview(provider, locale=locale)
                if action == "export":
                    entry_ids = [
                        entry for value in query.get("entry_id", []) for entry in value.split(",")
                        if entry
                    ]
                    return 200, manager.export(
                        provider, first("kind"), locale=locale, entry_ids=entry_ids,
                    )
                return 400, {"error": "Unbekannte Trainingspaket-Abfrage"}
            action = payload.get("action")
            if action == "preview":
                return 200, manager.preview(payload.get("package"))
            if action == "import":
                return 200, manager.import_package(payload.get("package"))
            if action == "train":
                return 200, manager.train(
                    payload.get("provider"),
                    refresh_inventory=payload.get("refresh_inventory") is True,
                    locale=str(payload.get("locale") or "de"),
                )
            return 400, {"error": "Unbekannte Trainingspaket-Aktion"}
        except (TypeError, ValueError) as exc:
            return 400, {"error": str(exc)}
        except RuntimeError as exc:
            return 503, {"error": str(exc)}

    from .brainwatch import BrainwatchInspector, MemoryExplorerInspector
    brainwatch = BrainwatchInspector(conversations.database.path) if conversations else None
    memory_explorer = MemoryExplorerInspector(conversations.database.path) if conversations else None
    from .semantic_inspector import SemanticInspector
    semantic_inspector = SemanticInspector(conversations.database.path) if conversations else None

    def browser_brainwatch(operation: str, namespaced_id: str | None, query: dict) -> dict:
        if brainwatch is None:
            raise RuntimeError("Brainwatch-Datenspeicher ist nicht verfügbar")
        first = lambda name, default=None: query.get(name, [default])[0]
        if operation == "assist_events":
            inbox = getattr(agent, "assist_events", None)
            if inbox is None:
                raise ValueError("Ereigniskanal ist nicht aktiviert")
            return inbox.groups(offset=int(first("offset", 0)), limit=int(first("limit", 50)))
        if operation == "working_memory":
            from .working_memory import WorkingMemoryStore
            store = WorkingMemoryStore(conversations.database)
            workspace = first("workspace_id")
            if not workspace:
                with conversations.database.connect(lifecycle_audit=False) as connection:
                    row = connection.execute("SELECT workspace_id FROM memory_work_bindings WHERE conversation_id=?",
                                             (agent.conversation_id,)).fetchone()
                if row is None:
                    return store.workspaces()
                workspace = row[0]
            view = first("view", "status")
            limit = int(first("limit")) if first("limit") is not None else None
            snapshot = int(first("snapshot")) if first("snapshot") is not None else None
            if view == "events":
                return store.events(workspace, after=int(first("after", 0)), limit=limit, snapshot=snapshot)
            if view == "objects":
                return store.list_objects(workspace, query=first("q"), kind=first("kind"),
                    offset=int(first("offset", 0)), limit=limit, snapshot=snapshot)
            if view == "object":
                return store.read(workspace, first("reference"), pointer=first("pointer", ""),
                                  offset=int(first("offset", 0)), limit=limit)
            if view == "structure":
                return store.inspect(workspace, first("reference"), pointer=first("pointer", ""),
                                     offset=int(first("offset", 0)), limit=limit)
            if view == "activity":
                return store.activity(workspace, turn_id=first("work_turn_id"))
            if view == "calls":
                return {"workspace_id": workspace, **store.calls(workspace)}
            if view == "contexts":
                with conversations.database.connect(lifecycle_audit=False) as connection:
                    rows = connection.execute("SELECT id,turn_id,reason,request_id AS reference,input_tokens,context_tokens,created_at "
                                              "FROM memory_work_contexts WHERE workspace_id=? ORDER BY created_at,id", (workspace,)).fetchall()
                return {"workspace_id": workspace, "items": [dict(row) for row in rows]}
            if view != "status":
                raise ValueError("Unbekannte Arbeitsgedächtnis-Ansicht")
            return store.manifest(workspace)
        if operation == "semantic_summary":
            return semantic_inspector.summary()
        if operation == "conversation_learning_status":
            if conversation_learning is None:
                raise RuntimeError("Gesprächslernen ist nicht verfügbar")
            if first("view", "status") == "jobs":
                return conversation_learning.jobs(
                    str(first("status", "evidenced")),
                    limit=int(first("limit", 40)),
                    offset=int(first("offset", 0)),
                )
            return conversation_learning.status()
        if operation == "conversation_learning_control":
            if conversation_learning is None:
                raise RuntimeError("Gesprächslernen ist nicht verfügbar")
            action = str(query.get("action") or "")
            if action == "pause":
                return conversation_learning.pause()
            if action == "resume":
                return conversation_learning.resume()
            if action == "run_now":
                return conversation_learning.run_now()
            if action == "retry_failed":
                return conversation_learning.retry_failed()
            if action in {"review", "reopen_review"}:
                result = conversation_learning.pipeline.review_turn(
                    query.get("turn_id"), query.get("note", ""), reopen=action == "reopen_review")
                return {**conversation_learning.status(), "review": result}
            raise ValueError("Unbekannte Gesprächslernen-Aktion")
        if operation == "semantic_similarity":
            return semantic_inspector.similarity(agent.semantic_links.similarity_settings(), first("limit", 30))
        if operation == "semantic_composition":
            return semantic_inspector.composition(agent.semantic_links.composition_settings(), first("limit", 30))
        if operation == "semantic_similarity_relation":
            relation_id = agent.semantic_links.record_similarity_relation(
                query.get("left"), query.get("right"), query.get("polarity"),
                representation_id=query.get("representation_id") or None,
                basis=query.get("basis") or "Explizite Brainwatch-Korrektur.",
                source_ref="brainwatch:similarity:" + str(uuid.uuid4()))
            return {"relation_id": relation_id, "status": "active"}
        if operation == "semantic_similarity_recognition":
            relation_id = agent.semantic_links.record_similarity_recognition(
                query.get("input_formulation"), query.get("learned_claim_id"), query.get("polarity"),
                basis=query.get("basis") or "Explizite Brainwatch-Bewertung der Zuordnung.",
                source_ref="brainwatch:recognition:" + str(uuid.uuid4()))
            return {"relation_id": relation_id, "status": "active"}
        if operation == "semantic_similarity_undo":
            return agent.semantic_links.retract_similarity_relation(
                namespaced_id, source_ref="brainwatch:similarity-undo:" + str(uuid.uuid4()))
        if operation == "semantic_actions":
            return semantic_inspector.actions(first("q", ""), first("cursor", 0), first("limit", 20))
        if operation == "semantic_action":
            return semantic_inspector.action_detail(namespaced_id, first("cursor", 0), first("limit", 20), first("evidence_cursor", 0))
        if operation == "semantic_list":
            return semantic_inspector.listing(
                first("q", ""), first("status", ""), first("action_link_status", ""),
                first("cursor", 0), first("limit", 20),
            )
        if operation == "semantic_detail":
            return semantic_inspector.detail(namespaced_id, first("cursor", 0), first("limit", 30), first("relation_cursor", 0))
        if operation == "semantic_reject":
            return semantic_inspector.reject(conversations.database, namespaced_id, query)
        if operation == "memory_graph_revision":
            return memory_explorer.graph_revision()
        if operation == "statistics":
            return memory_explorer.statistics()
        if operation == "memory_claims":
            return memory_explorer.claims(
                query=first("q", ""), scope=first("scope", ""),
                claim_kind=first("claim_kind", ""), lifecycle=first("lifecycle", ""),
                verification_policy=first("verification_policy", ""),
                cursor=first("cursor", ""), limit=first("limit", 20),
            )
        if operation == "working_memory_graph":
            return memory_explorer.working_memory_graph()
        if operation == "memory_graph":
            return memory_explorer.memory_graph(
                anchor_claim_id=first("anchor_claim_id", ""),
                scope=first("scope", ""), claim_kind=first("claim_kind", ""),
                lifecycle=first("lifecycle", ""),
                relation_type=first("relation_type", ""),
                depth=first("depth", 1), cursor=first("cursor", ""),
                node_limit=first("node_limit", 160),
                edge_limit=first("edge_limit", 320),
            )
        if operation == "memory_graph_relations":
            return memory_explorer.memory_graph_relations(
                scope=first("scope", ""), claim_kind=first("claim_kind", ""),
                lifecycle=first("lifecycle", ""),
                relation_type=first("relation_type", ""),
                cursor=first("cursor", ""), limit=first("limit", 200),
            )
        if operation == "memory_claim":
            return memory_explorer.claim(namespaced_id)
        if operation == "memory_evidence":
            return memory_explorer.evidence(
                namespaced_id, cursor=first("cursor", ""), limit=first("limit", 20),
            )
        if operation == "memory_relations":
            return memory_explorer.relations(
                namespaced_id, relation_type=first("relation_type", ""),
                cursor=first("cursor", ""), limit=first("limit", 30),
            )
        if operation == "memory_claim_turns":
            return memory_explorer.claim_turns(
                namespaced_id, origin_class=first("origin_class", ""),
                consumer=first("consumer", ""), cursor=first("cursor", ""),
                limit=first("limit", 20),
            )
        if operation == "memory_claim_runtime":
            return memory_explorer.claim_runtime(
                namespaced_id, category=first("category", ""),
                event_kind=first("event_kind", ""), proof_level=first("proof_level", ""),
                event_status=first("event_status", ""), consumer=first("consumer", ""),
                timestamp_from=first("from", ""), timestamp_to=first("to", ""),
                cursor=first("cursor", ""), sort=first("sort", "asc"),
                limit=first("limit", 30),
            )
        if operation == "turn_memory":
            return memory_explorer.turn_memory(
                namespaced_id, origin_class=first("origin_class", ""),
                consumer=first("consumer", ""), cursor=first("cursor", ""),
                limit=first("limit", 20),
            )
        if operation == "turn_runtime":
            return memory_explorer.turn_runtime(
                namespaced_id, category=first("category", ""),
                event_kind=first("event_kind", ""), proof_level=first("proof_level", ""),
                event_status=first("event_status", ""), consumer=first("consumer", ""),
                timestamp_from=first("from", ""), timestamp_to=first("to", ""),
                cursor=first("cursor", ""), sort=first("sort", "asc"),
                limit=first("limit", 50),
            )
        if operation == "turn_runtime_live":
            return memory_explorer.turn_runtime_live(
                namespaced_id, cursor=first("cursor", ""), tail=first("tail", "false"),
                limit=first("limit", 50),
            )
        if operation == "memory_runtime_event":
            return memory_explorer.runtime_event(namespaced_id)
        if operation == "memory_runtime_events":
            return memory_explorer.runtime_events(
                timestamp_from=first("from", ""), timestamp_to=first("to", ""),
                trace_id=first("trace_id", ""), turn_id=first("turn_id", ""),
                claim_id=first("claim_id", ""), relation_id=first("relation_id", ""),
                event_kind=first("event_kind", ""), category=first("category", ""),
                proof_level=first("proof_level", ""), event_status=first("event_status", ""),
                consumer=first("consumer", ""), planner_round_id=first("planner_round_id", ""),
                llm_call_id=first("llm_call_id", ""), attempt_id=first("attempt_id", ""),
                operation_id=first("operation_id", ""), plan_id=first("plan_id", ""),
                action_id=first("action_id", ""), tool_event_id=first("tool_event_id", ""),
                cursor=first("cursor", ""), sort=first("sort", "asc"),
                limit=first("limit", 30),
            )
        if operation == "memory_events":
            return memory_explorer.events(
                timestamp_from=first("from", ""), timestamp_to=first("to", ""),
                claim_id=first("claim_id", ""), turn_id=first("turn_id", ""),
                event_kind=first("event_kind", ""), category=first("category", ""),
                fidelity=first("fidelity", ""),
                consumer=first("consumer", ""), compiler_stage=first("compiler_stage", ""),
                scope=first("scope", ""), cursor=first("cursor", ""),
                limit=first("limit", 30),
            )
        if operation == "search":
            types = [item for value in query.get("types", []) for item in value.split(",") if item]
            return brainwatch.search(
                first("q", ""), types=types or None,
                cursor=int(first("cursor", 0)), limit=int(first("limit", 20)),
            )
        if operation == "node":
            return brainwatch.node(namespaced_id)
        categories = [item for value in query.get("categories", []) for item in value.split(",") if item]
        return brainwatch.neighbors(
            namespaced_id, direction=first("direction", "both"), categories=categories or None,
            cursor=int(first("cursor", 0)), limit=int(first("limit", 30)),
        )

    def browser_semantic_feedback(
        conversation_id: str, assistant_message_id: str, decision: str,
        explanation: str | None = None,
    ) -> dict:
        with conversations.database.connect(lifecycle_audit=False) as connection:
            row = connection.execute("SELECT metadata_json FROM messages WHERE id=? AND conversation_id=? AND role='assistant'",
                (assistant_message_id, conversation_id)).fetchone()
        if row is None:
            raise KeyError(assistant_message_id)
        metadata = json.loads(row[0] or '{}')
        details = metadata.get('turn_state_details') or {}
        semantic = (metadata.get('semantic_feedback') or (not metadata.get('answer_feedback')
            and metadata.get('turn_state') == 'operational_resolved' and details.get('operational_execution') is True
            and (details.get('semantic_link_candidate_id') or details.get('semantic_link_id'))))
        if semantic:
            if agent.semantic_links is None:
                raise RuntimeError("Semantischer Datenspeicher ist nicht verfügbar")
            return agent.semantic_links.execution_feedback(conversation_id, assistant_message_id, decision, explanation)
        return conversations.answer_feedback(conversation_id, assistant_message_id, decision, explanation)

    visual_cfg = cfg["visual"]
    cert = Path(visual_cfg["tls_cert"]) if visual_cfg.get("tls_cert") else None
    key = Path(visual_cfg["tls_key"]) if visual_cfg.get("tls_key") else None
    service_ready = threading.Event()
    readiness_lock = threading.Lock()
    readiness_cache = {"checked_at": 0.0, "result": {"ready": False, "llm": "not_checked"}}

    def service_readiness() -> dict:
        if not service_ready.is_set():
            return {"ready": False, "llm": "not_checked"}
        now = time.monotonic()
        with readiness_lock:
            cached = readiness_cache["result"]
            cache_seconds = 5.0 if cached.get("ready") else 1.0
            if now - readiness_cache["checked_at"] < cache_seconds:
                return dict(cached)
            models = llm.models()
            configured = llm.model.casefold().strip()
            configured_name = configured.rsplit("/", 1)[-1]
            model_ready = any(
                model.casefold().strip() == configured
                or model.casefold().strip().rsplit("/", 1)[-1] == configured_name
                for model in models
            )
            result = {
                "ready": model_ready,
                "llm": "ready" if model_ready else "not_ready",
                "model": llm.model,
            }
            readiness_cache.update(checked_at=now, result=result)
            return dict(result)

    from .assist_api import AssistAPI
    from .chatto import ChattoAPI, ChattoProcess
    chatto_process = ChattoProcess(root, cfg)
    chatto_bridge = ChattoAPI(
        cfg["chatto"], conversations,
        lambda text, images, identifier: browser_message(text, images, identifier, synthesize_audio=False),
        learning_activity=conversation_learning.note_activity if conversation_learning else None,
    )
    chatto_bridge.scheduler = reminders
    reminders.output_targets_provider = chatto_bridge.output_targets
    if callable(start_scheduler):
        start_scheduler()
    from .assist_events import AssistEventInbox
    assist_config = cfg.get("assist_api", {})
    assist_bridge = None
    if assist_config.get("enabled"):
        if not assist_config.get("token"):
            raise ValueError("Assist-API benötigt EVE_ASSIST_TOKEN")
        agent.assist_events = AssistEventInbox(bus.runtime_dir / "assist-events.sqlite3")
        assist_bridge = AssistAPI(
            transcriber, speaker, conversations,
            lambda text, images, identifier: browser_message(
                text, images, identifier, synthesize_audio=False),
            event_inbox=agent.assist_events,
        )

    visual = VisualServer(
        Path(cfg.get("paths", {}).get("web", root / "web")),
        bus,
        visual_cfg["host"],
        int(visual_cfg["port"]),
        browser_turn,
        browser_message,
        cert,
        key,
        notification_handler=browser_notifications,
        readiness_handler=service_readiness,
        assist_handler=assist_bridge,
        assist_token=assist_config.get("token", ""),
        chatto_handler=chatto_bridge,
        chatto_token=chatto_process.token,
        chatto_status_handler=chatto_process.status,
        conversation_handler=browser_conversations,
        task_handler=browser_tasks,
        work_list_handler=browser_work_lists,
        work_item_handler=browser_work_items,
        config_handler=browser_config,
        home_assistant_inventory_handler=browser_home_assistant_inventory,
        home_assistant_policy_handler=browser_home_assistant_policy,
        training_package_handler=browser_training_packages,
        telemetry_handler=browser_telemetry,
        brainwatch_handler=browser_brainwatch,
        semantic_feedback_handler=browser_semantic_feedback,
        turn_result_handler=browser_turn_result,
        presentation_handler=browser_presentation,
        presentation_resource_handler=(
            agent.presentations.read_resource if getattr(agent, "presentations", None) else None
        ),
        conversation_asset_handler=(conversations.read_asset if conversations else None),
        backend_message_start_handler=start_backend_message,
        backend_message_snapshot_handler=backend_message_snapshot,
        backend_voice_start_handler=start_backend_voice,
        backend_turn_cancel_handler=cancel_backend_turn,
        max_connections=int(visual_cfg.get("max_connections", 32)),
        max_concurrent_requests=int(visual_cfg.get("max_concurrent_requests", 8)),
        allowed_hosts=visual_cfg.get("allowed_hosts", [visual_cfg.get("public_host")]),
    )
    visual.start()
    try:
        chatto_process.start()
    except OSError:
        print("Chatto konnte nicht starten; Node-Programm und Client-Build prüfen.", file=sys.stderr)
    working_memory_cleanup = getattr(agent, "working_memory_cleanup", None)
    if working_memory_cleanup is not None:
        working_memory_cleanup.start()
    service_ready.set()
    if args.command != "serve" and visual_cfg.get("open_browser", True) and not args.no_browser:
        webbrowser.open(visual.url)
    print(f"EVE Visual Presence: {visual.url}")
    public_host = visual_cfg.get("public_host")
    if public_host:
        print(f"EVE LAN: {visual.scheme}://{public_host}:{visual.port}/")
    text_mode = args.command == "text"
    try:
        if args.command == "serve":
            print("EVE läuft im Service-Modus. SIGINT oder SIGTERM beendet den Prozess.")
            _wait_for_service_shutdown()
            return 0
        while True:
            bus.set("idle")
            if text_mode:
                utterance = input("\nDu> ").strip()
            else:
                input("\nEnter startet Push-to-Talk (Ctrl-C beendet) … ")
                bus.set("listening")
                handle = temporary_wav(); audio_path = Path(handle.name); handle.close()
                try:
                    recorder.record_until_enter(audio_path)
                    bus.set("thinking", "Transkription")
                    utterance = transcriber.transcribe(audio_path)
                finally:
                    audio_path.unlink(missing_ok=True)
                print(f"Du> {utterance}")
            if not utterance: continue
            if not turn_lock.acquire(blocking=False):
                print("EVE verarbeitet bereits eine Browser-Eingabe.")
                continue
            try:
                if conversation_learning is not None:
                    conversation_learning.note_activity()
                shadow_learning = getattr(agent, "shadow_learning", None)
                if shadow_learning is not None:
                    shadow_learning.prioritize_interactive_turn()
                memory_compiler = getattr(agent, "memory_compiler", None)
                if memory_compiler is not None:
                    memory_compiler.prioritize_interactive_turn()
                answer = agent.respond(utterance)
                print(f"EVE> {answer}")
                completed_turn = getattr(agent, "_last_turn_result", None)
                if shadow_learning is not None and completed_turn is not None:
                    token = shadow_learning.priority_token()
                    post_turn_executor.submit(shadow_learning.evaluate_turn, completed_turn.turn_id, token)
                if conversation_learning is not None and completed_turn is not None:
                    conversation_learning.accept_turn(completed_turn.turn_id)
                if memory_compiler is not None and completed_turn is not None:
                    token = memory_compiler.priority_token()
                    compiler_queued_at = time.perf_counter()
                    for consumer in ("planner", "answer"):
                        post_turn_executor.submit(
                            memory_compiler.compile_turn, completed_turn.turn_id, consumer,
                            expected_priority_generation=token,
                            queued_at_monotonic=compiler_queued_at,
                        )
                if not args.no_tts:
                    spoken_answer, _ = extract_artifacts(answer, utterance)
                    bus.set("speaking")
                    with tts_lock:
                        speaker.speak(speech_text(spoken_answer))
            except LocalLLMError as exc:
                bus.set("error", str(exc)); print(f"EVE Fehler> {exc}", file=sys.stderr)
            finally:
                turn_lock.release()
    except (KeyboardInterrupt, EOFError):
        print("\nEVE beendet.")
    finally:
        service_ready.clear()
        chatto_process.close()
        bus.set("idle")
        visual.stop()
        backend_turns.close()
        if conversation_learning is not None:
            conversation_learning.close()
        if working_memory_cleanup is not None:
            working_memory_cleanup.close()
        turn_completion_executor.shutdown(wait=False, cancel_futures=False)
        shadow_learning = getattr(agent, "shadow_learning", None)
        if shadow_learning is not None:
            shadow_learning.prioritize_interactive_turn()
        memory_compiler = getattr(agent, "memory_compiler", None)
        if memory_compiler is not None:
            memory_compiler.prioritize_interactive_turn()
        post_turn_executor.shutdown(wait=True)
        shell = getattr(agent, "shell", None)
        if shell is not None:
            shell.close_all()
        for name in ("work_tasks", "nova_maintenance", "external_mcp"):
            provider = getattr(agent, name, None)
            if provider is not None:
                provider.close_all()
        wayland_computer = getattr(agent, "wayland_computer", None)
        if wayland_computer is not None:
            wayland_computer.close_all()
    return 0


if __name__ == "__main__": raise SystemExit(main())
