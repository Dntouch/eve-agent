from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .memory import redact_sensitive
from .memory_runtime_telemetry import (
    EVENT_KINDS as RUNTIME_EVENT_KINDS,
    EVENT_STATUSES as RUNTIME_EVENT_STATUSES,
    PROOF_LEVELS as RUNTIME_PROOF_LEVELS,
    MemoryRuntimeEventReader,
)


NODE_TYPES = {
    "conversation", "message", "turn", "memory", "asset", "tool-event",
    "work-list", "work-item", "work-item-event", "scheduled-task", "task-run",
    "approval", "audit-event", "web-source",
}
EDGE_CATEGORIES = {"factual", "lineage", "retrieval", "semantic_similarity", "lexical_match"}
SEARCH_LIMIT = 30
NEIGHBOR_LIMIT = 30
MEMORY_EXPLORER_LIMIT = 50
MEMORY_EXPLORER_JSON_BUDGET = 64 * 1024
MEMORY_GRAPH_NODE_LIMIT = 400
MEMORY_GRAPH_RESPONSE_NODE_LIMIT = 1000
MEMORY_GRAPH_EDGE_LIMIT = 800
MEMORY_GRAPH_MAX_DEPTH = 3
CLAIM_KINDS = {"opaque_fact", "provider_binding", "alias"}
CLAIM_LIFECYCLES = {"candidate", "active", "retired", "invalid"}
VERIFICATION_POLICIES = {"stable", "configuration", "dynamic", "unknown"}
RELATION_TYPES = {"supersedes", "contradicts", "refines"}
MEMORY_TURN_ORIGINS = {
    "evidence_source_turn", "observation_turn", "learning_decision",
    "compiler_retrieved", "compiler_would_present", "usage_presented",
    "semantic_reuse_result",
}
MEMORY_TURN_CONSUMERS = {"planner", "native_tool", "answer", "audit"}
MEMORY_TURN_ORIGIN_LABELS = {
    "evidence_source_turn": "Herkunft / Evidence",
    "observation_turn": "Beobachtung",
    "learning_decision": "Lernentscheidung",
    "compiler_retrieved": "Compiler-Kandidat",
    "compiler_would_present": "Für Präsentation ausgewählt",
    "usage_presented": "Präsentation protokolliert",
    "semantic_reuse_result": "Semantische Wiederverwendung",
}
MEMORY_TURN_INTERPRETATIONS = {
    "evidence_source_turn": "Herkunft oder Evidence; keine Entscheidungskausalität.",
    "observation_turn": "Gespeicherte Beobachtung; keine Entscheidungskausalität.",
    "learning_decision": "Gespeicherte Lernentscheidung; keine Aussage über die Turn-Entscheidung.",
    "compiler_retrieved": "Compiler-Kandidat; keine Aussage über Auswahl oder Verwendung.",
    "compiler_would_present": "Durch diese Compiler-Evaluation ausgewählt; kein sicherer Prompt-Nachweis.",
    "usage_presented": "Präsentation protokolliert; tatsächliche Prompt-Aufnahme ist nicht zuverlässig belegt.",
    "semantic_reuse_result": "Scopespezifisches Ergebnis einer semantischen Wiederverwendung.",
}
MEMORY_EVENT_FIDELITIES = {"direct_event", "state_timestamp", "derived_link"}
MEMORY_EVENT_CONSUMERS = {"planner", "native_tool", "answer", "audit"}
MEMORY_EVENT_STAGES = {"retrieved", "eligible", "would_present", "rejected", "cancelled", "error"}
MEMORY_EVENT_KINDS = {
    "claim_created", "evidence_created", "observation_recorded", "relation_stored",
    "learning_decision", "learning_job_accepted", "learning_job_started",
    "learning_job_completed", "learning_job_updated", "compiler_evaluation",
    "compiler_retrieved", "compiler_eligible", "compiler_would_present",
    "compiler_rejected", "compiler_cancelled", "compiler_error",
    "usage_presented", "semantic_reuse_result",
}
HISTORICAL_EVENT_CATEGORIES = {
    "retrieval": {
        "compiler_evaluation", "compiler_retrieved", "compiler_eligible",
        "compiler_would_present", "compiler_rejected", "compiler_cancelled",
        "compiler_error", "usage_presented", "semantic_reuse_result",
    },
    "memory_changes": {
        "claim_created", "evidence_created", "observation_recorded", "learning_decision",
        "learning_job_accepted", "learning_job_started", "learning_job_completed",
        "learning_job_updated",
    },
    "relations": {"relation_stored"},
}
HISTORICAL_EVENT_CATEGORY_BY_KIND = {
    event_kind: category
    for category, event_kinds in HISTORICAL_EVENT_CATEGORIES.items()
    for event_kind in event_kinds
}
MEMORY_EVENT_FIDELITY_TEXT = {
    "direct_event": "Eine eigene persistente Ereigniszeile belegt den Vorgang.",
    "state_timestamp": "Der Zeitpunkt gehört zu einem gespeicherten Zustand; ein vollständiges Vorher/Nachher ist nicht aufgezeichnet.",
    "derived_link": "Die Verbindung wird aus persistenten Fremdschlüsseln abgeleitet und belegt keine zusätzliche Kausalität.",
}
RUNTIME_EVENT_CATEGORIES = {
    "retrieval": {
        "claim_query_started", "claim_retrieved", "claim_eligible",
        "claim_selected_for_view", "claim_returned_to_consumer",
    },
    "llm_context": {
        "claim_added_to_prompt_context", "claim_received_by_llm_client",
        "claim_serialized_for_transport", "transport_failed", "llm_transport_result",
    },
    "deterministic": {
        "claim_resolved", "alias_read_for_stt", "claim_technical_verification",
        "claim_bound_to_plan",
    },
    "actions": {
        "claim_bound_to_action", "action_dispatch_attempted_with_claim",
        "action_provider_response_with_claim", "action_verification_with_claim",
        "action_completed_with_claim",
    },
    "memory_changes": {"claim_lifecycle_changed"},
    "relations": {"relation_traversed_for_retrieval", "relation_bound_to_plan"},
    "system": {
        "trace_started", "operation_started", "operation_completed", "operation_aborted",
        "telemetry_persist_failed",
    },
}
RUNTIME_EVENT_CATEGORY_BY_KIND = {
    event_kind: category
    for category, event_kinds in RUNTIME_EVENT_CATEGORIES.items()
    for event_kind in event_kinds
}
_SECRET_KEY = re.compile(
    r"^(?:token|access_token|refresh_token|client_secret|api[_-]?key|authorization|"
    r"password|passwd|passwort|secret|cookie|local[_-]?key)$", re.I,
)
_PUBLIC_URL = re.compile(r"https?://[^\s<>\"']+")
_SEARCH_TOKEN = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)


def _preview(value, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _json_object(value) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normal_url(value: str) -> str | None:
    try:
        parsed = urlsplit(str(value).strip())
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path or "/", parsed.query, ""))


def _public_text(value) -> str:
    def safe_url(match):
        try:
            parsed = urlsplit(match.group(0))
            host = parsed.hostname or ""
            if ":" in host:
                host = f"[{host}]"
            if parsed.port:
                host += f":{parsed.port}"
            return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
        except ValueError:
            return "[REDACTED URL]"
    return redact_sensitive(_PUBLIC_URL.sub(safe_url, str(value or "")))


def _public_json(value, *, budget: int = MEMORY_EXPLORER_JSON_BUDGET):
    """Recursively redact and bound untrusted structured diagnostic values."""
    remaining = [max(0, int(budget))]

    def project(item, key="", depth=0):
        if _SECRET_KEY.match(str(key)):
            return "[REDACTED]"
        if remaining[0] <= 0:
            return "[TRUNCATED]"
        if depth >= 8:
            remaining[0] -= 11
            return "[MAX DEPTH]"
        if isinstance(item, dict):
            result = {}
            entries = list(item.items())
            for child_key, child in entries[:100]:
                safe_key = _public_text(child_key)[:200]
                remaining[0] -= len(safe_key.encode("utf-8"))
                result[safe_key] = project(child, str(child_key), depth + 1)
                if remaining[0] <= 0:
                    break
            if len(entries) > 100 or remaining[0] <= 0:
                result["_truncated"] = True
            if "endpoint" in result and isinstance(result["endpoint"], str):
                try:
                    parsed = urlsplit(result["endpoint"])
                    result["endpoint"] = f"{parsed.scheme}://{parsed.hostname or ''}"
                except ValueError:
                    result["endpoint"] = "[REDACTED]"
            return result
        if isinstance(item, list):
            result = [project(child, key, depth + 1) for child in item[:100]]
            if len(item) > 100 or remaining[0] <= 0:
                result.append("[TRUNCATED]")
            return result
        if isinstance(item, str):
            safe = _public_text(item)
            encoded = safe.encode("utf-8")
            allowed = min(len(encoded), remaining[0], 12_000)
            remaining[0] -= allowed
            if allowed < len(encoded):
                return encoded[:max(0, allowed - 3)].decode("utf-8", "ignore") + "…"
            return safe
        if item is None or isinstance(item, (bool, int, float)):
            remaining[0] -= len(str(item))
            return item
        return project(str(item), key, depth)

    return project(value)


def _decode_json_object(value) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {"_invalid_json": True}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def _encode_cursor(timestamp: str, identifier: str, binding: str) -> str:
    raw = json.dumps(
        {"v": 1, "timestamp": timestamp, "id": identifier, "binding": binding},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str, binding: str) -> tuple[str, str]:
    value = str(value or "")
    if not value or len(value) > 1024 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Ungültiger Memory-Explorer-Cursor")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        payload = json.loads(raw)
    except (ValueError, TypeError, json.JSONDecodeError):
        raise ValueError("Ungültiger Memory-Explorer-Cursor") from None
    if (
        not isinstance(payload, dict) or set(payload) != {"v", "timestamp", "id", "binding"}
        or payload.get("v") != 1 or payload.get("binding") != binding
        or not isinstance(payload.get("timestamp"), str)
        or not isinstance(payload.get("id"), str)
        or not payload["timestamp"] or not payload["id"]
        or len(payload["timestamp"]) > 100 or len(payload["id"]) > 512
    ):
        raise ValueError("Cursor gehört nicht zu dieser Memory-Explorer-Abfrage")
    return payload["timestamp"], payload["id"]


class BrainwatchInspector:
    """Allowlisted, read-only projection of EVE's persistent information graph."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path).resolve()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"file:{self.database_path.as_posix()}?mode=ro", uri=True, timeout=5,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _split_id(namespaced_id: str) -> tuple[str, str]:
        node_type, separator, raw_id = str(namespaced_id).partition(":")
        if not separator or node_type not in NODE_TYPES or not raw_id or len(raw_id) > 512:
            raise ValueError("Ungültige Brainwatch-Knoten-ID")
        return node_type, raw_id

    @staticmethod
    def _node(node_type: str, raw_id, label, timestamp=None, *, preview=None, metadata=None) -> dict:
        return {
            "id": f"{node_type}:{raw_id}", "type": node_type,
            "label": _preview(label, 90) or node_type, "timestamp": timestamp,
            "persistent": True, "preview": _preview(preview if preview is not None else label),
            "metadata": metadata or {},
        }

    @staticmethod
    def _edge(source: str, target: str, edge_type: str, category: str, label: str, *, metadata=None) -> dict:
        digest = hashlib.sha256(f"{source}|{target}|{edge_type}".encode()).hexdigest()[:20]
        return {
            "id": f"edge:{digest}", "source": source, "target": target,
            "type": edge_type, "category": category, "label": label,
            "persistent": True, "metadata": metadata or {},
        }

    def search(self, query: str, *, types=None, cursor: int = 0, limit: int = 20) -> dict:
        query = " ".join(str(query or "").split())
        if not query or len(query) > 300:
            raise ValueError("Suchtext muss zwischen 1 und 300 Zeichen lang sein")
        selected = set(types or NODE_TYPES)
        if not selected or not selected <= NODE_TYPES:
            raise ValueError("Nicht unterstützter Knotentyp")
        cursor = max(0, int(cursor))
        limit = min(max(1, int(limit)), SEARCH_LIMIT)
        needle = f"%{query.replace('%', '').replace('_', '')}%"
        candidates = []
        with closing(self._connect()) as db:
            if "conversation" in selected:
                for row in db.execute("SELECT id,title,updated_at FROM conversations WHERE status!='deleted' AND title LIKE ? ESCAPE '\\' ORDER BY updated_at DESC LIMIT 80", (needle,)):
                    candidates.append(self._node("conversation", row["id"], row["title"], row["updated_at"]))
            if "message" in selected:
                for row in db.execute("SELECT id,role,content,created_at FROM messages WHERE content LIKE ? ESCAPE '\\' ORDER BY created_at DESC LIMIT 80", (needle,)):
                    candidates.append(self._node("message", row["id"], f"{row['role']}: {_preview(row['content'], 70)}", row["created_at"], preview=row["content"], metadata={"role": row["role"]}))
            if "memory" in selected:
                for row in db.execute("SELECT id,content,category,confidence,updated_at FROM memory_items WHERE status!='deleted' AND content LIKE ? ESCAPE '\\' ORDER BY updated_at DESC LIMIT 80", (needle,)):
                    candidates.append(self._node("memory", row["id"], row["content"], row["updated_at"], metadata={"category": row["category"], "confidence": row["confidence"]}))
            if "work-list" in selected:
                for row in db.execute("SELECT id,name,description,updated_at FROM work_task_lists WHERE status!='deleted' AND (name LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\') ORDER BY updated_at DESC LIMIT 80", (needle, needle)):
                    candidates.append(self._node("work-list", row["id"], row["name"], row["updated_at"], preview=row["description"]))
            if "work-item" in selected:
                for row in db.execute("SELECT id,title,description,status,updated_at FROM work_items WHERE status!='deleted' AND (title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\') ORDER BY updated_at DESC LIMIT 80", (needle, needle)):
                    candidates.append(self._node("work-item", row["id"], row["title"], row["updated_at"], preview=row["description"], metadata={"status": row["status"]}))
            if "scheduled-task" in selected:
                for row in db.execute("SELECT id,name,status,updated_at FROM scheduled_tasks WHERE status!='deleted' AND name LIKE ? ESCAPE '\\' ORDER BY updated_at DESC LIMIT 80", (needle,)):
                    candidates.append(self._node("scheduled-task", row["id"], row["name"], row["updated_at"], metadata={"status": row["status"]}))
        candidates.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
        page = candidates[cursor:cursor + limit]
        next_cursor = cursor + len(page) if cursor + len(page) < len(candidates) else None
        return {"query": query, "nodes": page, "page": {"has_more": next_cursor is not None, "next_cursor": next_cursor}}

    def node(self, namespaced_id: str) -> dict:
        node_type, raw_id = self._split_id(namespaced_id)
        with closing(self._connect()) as db:
            node = self._load_node(db, node_type, raw_id)
        if node is None:
            raise KeyError(namespaced_id)
        return {"focus": namespaced_id, "nodes": [node], "edges": [], "page": {"has_more": False, "next_cursor": None}}

    def neighbors(self, namespaced_id: str, *, direction="both", categories=None, cursor=0, limit=30) -> dict:
        node_type, raw_id = self._split_id(namespaced_id)
        if direction not in {"both", "in", "out"}:
            raise ValueError("Ungültige Richtung")
        selected = set(categories or EDGE_CATEGORIES)
        if not selected <= EDGE_CATEGORIES:
            raise ValueError("Nicht unterstützte Kantenkategorie")
        cursor = max(0, int(cursor))
        limit = min(max(1, int(limit)), NEIGHBOR_LIMIT)
        with closing(self._connect()) as db:
            focus = self._load_node(db, node_type, raw_id)
            if focus is None:
                raise KeyError(namespaced_id)
            nodes, edges = self._load_neighbors(db, node_type, raw_id, scan_limit=cursor + limit + 1)
        filtered = [edge for edge in edges if edge["category"] in selected and (direction == "both" or (direction == "out" and edge["source"] == namespaced_id) or (direction == "in" and edge["target"] == namespaced_id))]
        visible = filtered[cursor:cursor + limit]
        used = {namespaced_id} | {edge["source"] for edge in visible} | {edge["target"] for edge in visible}
        by_id = {node["id"]: node for node in nodes}
        result_nodes = [focus] + [by_id[item] for item in used if item != namespaced_id and item in by_id]
        next_cursor = cursor + len(visible) if cursor + len(visible) < len(filtered) else None
        return {"focus": namespaced_id, "nodes": result_nodes, "edges": visible, "page": {"has_more": next_cursor is not None, "next_cursor": next_cursor}}

    def _load_node(self, db, node_type: str, raw_id: str):
        specs = {
            "conversation": ("SELECT id,title,updated_at,status,source FROM conversations WHERE id=? AND status!='deleted'", lambda r: self._node("conversation", r["id"], r["title"], r["updated_at"], metadata={"status": r["status"], "source": r["source"]})),
            "message": ("SELECT id,role,content,kind,created_at,turn_id FROM messages WHERE id=?", lambda r: self._node("message", r["id"], f"{r['role']}: {_preview(r['content'],70)}", r["created_at"], preview=r["content"], metadata={"role": r["role"], "kind": r["kind"], "turn_lineage_recorded": bool(r["turn_id"])})),
            "turn": ("SELECT id,created_at,completed_at,knowledge_flow_json FROM turns WHERE id=?", lambda r: self._node("turn", r["id"], f"Turn {str(r['id'])[:8]}", r["created_at"], metadata={"completed_at": r["completed_at"], "knowledge_flow": _json_object(r["knowledge_flow_json"])})),
            "memory": ("SELECT id,content,category,status,confidence,source_message_id,created_at,updated_at FROM memory_items WHERE id=? AND status!='deleted'", lambda r: self._node("memory", r["id"], r["content"], r["updated_at"], metadata={"category": r["category"], "status": r["status"], "confidence": r["confidence"], "source_recorded": bool(r["source_message_id"])})),
            "asset": ("SELECT id,filename,media_type,byte_size,created_at FROM conversation_assets WHERE id=?", lambda r: self._node("asset", r["id"], r["filename"], r["created_at"], metadata={"media_type": r["media_type"], "byte_size": r["byte_size"], "preview_url": f"/api/conversation-assets/{r['id']}"})),
            "tool-event": ("SELECT id,tool,status,summary,created_at FROM conversation_tool_events WHERE id=?", lambda r: self._node("tool-event", r["id"], f"{r['tool']}: {r['summary']}", r["created_at"], metadata={"tool": r["tool"], "status": r["status"]})),
            "work-list": ("SELECT id,name,description,status,updated_at FROM work_task_lists WHERE id=? AND status!='deleted'", lambda r: self._node("work-list", r["id"], r["name"], r["updated_at"], preview=r["description"], metadata={"status": r["status"]})),
            "work-item": ("SELECT id,title,description,status,updated_at FROM work_items WHERE id=? AND status!='deleted'", lambda r: self._node("work-item", r["id"], r["title"], r["updated_at"], preview=r["description"], metadata={"status": r["status"]})),
            "work-item-event": ("SELECT id,event_type,created_at FROM work_item_events WHERE id=?", lambda r: self._node("work-item-event", r["id"], r["event_type"], r["created_at"])),
            "scheduled-task": ("SELECT id,name,status,schedule_type,next_run_at,updated_at FROM scheduled_tasks WHERE id=? AND status!='deleted'", lambda r: self._node("scheduled-task", r["id"], r["name"], r["updated_at"], metadata={"status": r["status"], "schedule_type": r["schedule_type"], "next_run_at": r["next_run_at"]})),
            "task-run": ("SELECT id,status,scheduled_for,started_at,finished_at,attempt,created_at FROM task_runs WHERE id=?", lambda r: self._node("task-run", r["id"], f"Run: {r['status']}", r["created_at"], metadata={"status": r["status"], "scheduled_for": r["scheduled_for"], "started_at": r["started_at"], "finished_at": r["finished_at"], "attempt": r["attempt"]})),
            "approval": ("SELECT id,risk_level,status,requested_at,decided_at,expires_at FROM approvals WHERE id=?", lambda r: self._node("approval", r["id"], f"Freigabe: {r['status']}", r["requested_at"], metadata={"risk_level": r["risk_level"], "status": r["status"], "decided_at": r["decided_at"], "expires_at": r["expires_at"]})),
            "audit-event": ("SELECT id,event_type,actor,summary,created_at FROM audit_events WHERE id=?", lambda r: self._node("audit-event", r["id"], r["summary"], r["created_at"], metadata={"event_type": r["event_type"], "actor": r["actor"]})),
        }
        if node_type == "web-source":
            return self._find_web_source(db, raw_id)
        query, factory = specs[node_type]
        row = db.execute(query, (raw_id,)).fetchone()
        return factory(row) if row else None

    def _web_sources(self, db, message_id: str | None = None):
        query = "SELECT id,created_at,metadata_json FROM messages WHERE metadata_json LIKE '%\"sources\"%'"
        params = ()
        if message_id:
            query += " AND id=?"
            params = (message_id,)
        for row in db.execute(query, params):
            for source in _json_object(row["metadata_json"]).get("sources", []):
                if not isinstance(source, dict):
                    continue
                url = _normal_url(source.get("url", ""))
                if not url:
                    continue
                source_id = hashlib.sha256(url.encode()).hexdigest()
                yield row, source_id, url, source

    def _find_web_source(self, db, raw_id: str):
        for row, source_id, url, source in self._web_sources(db):
            if source_id == raw_id:
                return self._node("web-source", source_id, source.get("title") or url, row["created_at"], preview=source.get("snippet"), metadata={"url": url, "host": urlsplit(url).hostname})
        return None

    def _load_neighbors(self, db, node_type: str, raw_id: str, *, scan_limit: int = NEIGHBOR_LIMIT + 1):
        nodes, edges = {}, []
        def add(node):
            if node: nodes[node["id"]] = node
        def relation(node, source, target, kind, category, label, metadata=None):
            add(node); edges.append(self._edge(source, target, kind, category, label, metadata=metadata))
        focus_id = f"{node_type}:{raw_id}"

        if node_type == "conversation":
            rows = db.execute("SELECT id FROM messages WHERE conversation_id=? ORDER BY ordinal LIMIT ?", (raw_id, scan_limit))
            for row in rows:
                node = self._load_node(db, "message", row["id"]); relation(node, focus_id, node["id"], "contains", "factual", "enthält")
            for table, kind in (("scheduled_tasks", "scheduled-task"), ("approvals", "approval"), ("audit_events", "audit-event")):
                for row in db.execute(f"SELECT id FROM {table} WHERE conversation_id=? LIMIT ?", (raw_id, scan_limit)):
                    node = self._load_node(db, kind, str(row["id"])); relation(node, focus_id, node["id"], "contains", "factual", "enthält")
        elif node_type == "message":
            row = db.execute("SELECT conversation_id,turn_id,role FROM messages WHERE id=?", (raw_id,)).fetchone()
            conversation = self._load_node(db, "conversation", row["conversation_id"]); relation(conversation, conversation["id"], focus_id, "contains", "factual", "enthält")
            if row["turn_id"]:
                turn = self._load_node(db, "turn", row["turn_id"])
                if row["role"] == "assistant":
                    relation(turn, turn["id"], focus_id, "output_of", "lineage", "Output von")
                else:
                    relation(turn, focus_id, turn["id"], "input_of", "lineage", "Input von")
            for item in db.execute("SELECT id FROM conversation_assets WHERE message_id=?", (raw_id,)):
                node = self._load_node(db, "asset", item["id"]); relation(node, focus_id, node["id"], "has_asset", "factual", "besitzt")
            for item in db.execute("SELECT id FROM conversation_tool_events WHERE message_id=?", (raw_id,)):
                node = self._load_node(db, "tool-event", item["id"]); relation(node, focus_id, node["id"], "has_tool_event", "factual", "besitzt")
            for item in db.execute("SELECT id FROM memory_items WHERE source_message_id=? AND status!='deleted'", (raw_id,)):
                node = self._load_node(db, "memory", item["id"]); relation(node, focus_id, node["id"], "generated_memory", "lineage", "erzeugte Memory")
            for source_row, source_id, url, source in self._web_sources(db, raw_id):
                node = self._find_web_source(db, source_id); relation(node, focus_id, node["id"], "source_available_for_message", "factual", "Quelle verfügbar", {"evidence": "Persistierte Nachrichtenmetadaten; keine Aussage über Nutzung als Beleg."})
        elif node_type == "turn":
            row = db.execute("SELECT conversation_id,user_message_id,assistant_message_id FROM turns WHERE id=?", (raw_id,)).fetchone()
            conversation = self._load_node(db, "conversation", row["conversation_id"]); relation(conversation, conversation["id"], focus_id, "contains_turn", "factual", "enthält")
            if row["user_message_id"]:
                node = self._load_node(db, "message", row["user_message_id"]); relation(node, node["id"], focus_id, "input_of", "lineage", "Input von")
            if row["assistant_message_id"]:
                node = self._load_node(db, "message", row["assistant_message_id"]); relation(node, focus_id, node["id"], "output_of", "lineage", "Output von")
            for item in db.execute("SELECT memory_id,position,method,score,retrieved_at FROM turn_memory_retrievals WHERE turn_id=? ORDER BY position", (raw_id,)):
                node = self._load_node(db, "memory", item["memory_id"]); relation(node, node["id"], focus_id, "retrieved_for", "retrieval", "retrieved für", {"position": item["position"], "method": item["method"], "score": item["score"], "retrieved_at": item["retrieved_at"], "evidence": "Persistiertes Retrieval-Ereignis; keine Kausalitätsbehauptung."})
        elif node_type == "memory":
            row = db.execute("SELECT source_message_id FROM memory_items WHERE id=?", (raw_id,)).fetchone()
            if row["source_message_id"]:
                node = self._load_node(db, "message", row["source_message_id"]); relation(node, node["id"], focus_id, "generated_memory", "lineage", "erzeugte Memory")
            for item in db.execute("SELECT turn_id,position,method,score,retrieved_at FROM turn_memory_retrievals WHERE memory_id=? ORDER BY retrieved_at DESC", (raw_id,)):
                node = self._load_node(db, "turn", item["turn_id"]); relation(node, focus_id, node["id"], "retrieved_for", "retrieval", "retrieved für", {"position": item["position"], "method": item["method"], "score": item["score"], "retrieved_at": item["retrieved_at"], "evidence": "Persistiertes Retrieval-Ereignis; keine Kausalitätsbehauptung."})
        elif node_type in {"asset", "tool-event"}:
            table = "conversation_assets" if node_type == "asset" else "conversation_tool_events"
            row = db.execute(f"SELECT message_id FROM {table} WHERE id=?", (raw_id,)).fetchone()
            node = self._load_node(db, "message", row["message_id"]); relation(node, node["id"], focus_id, "has_asset" if node_type == "asset" else "has_tool_event", "factual", "besitzt")
        elif node_type == "work-list":
            for row in db.execute("SELECT id FROM work_items WHERE list_id=? AND status!='deleted' ORDER BY position LIMIT ?", (raw_id, scan_limit)):
                node = self._load_node(db, "work-item", row["id"]); relation(node, focus_id, node["id"], "contains", "factual", "enthält")
        elif node_type == "work-item":
            row = db.execute("SELECT list_id FROM work_items WHERE id=?", (raw_id,)).fetchone()
            node = self._load_node(db, "work-list", row["list_id"]); relation(node, node["id"], focus_id, "contains", "factual", "enthält")
            for item in db.execute("SELECT id FROM work_item_events WHERE work_item_id=?", (raw_id,)):
                node = self._load_node(db, "work-item-event", str(item["id"])); relation(node, focus_id, node["id"], "has_event", "factual", "besitzt Ereignis")
        elif node_type == "work-item-event":
            row = db.execute("SELECT work_item_id FROM work_item_events WHERE id=?", (raw_id,)).fetchone()
            node = self._load_node(db, "work-item", row["work_item_id"]); relation(node, node["id"], focus_id, "has_event", "factual", "besitzt Ereignis")
        elif node_type == "scheduled-task":
            row = db.execute("SELECT conversation_id FROM scheduled_tasks WHERE id=?", (raw_id,)).fetchone()
            if row["conversation_id"]:
                node = self._load_node(db, "conversation", row["conversation_id"]); relation(node, node["id"], focus_id, "has_task", "factual", "besitzt")
            for item in db.execute("SELECT id FROM task_runs WHERE task_id=?", (raw_id,)):
                node = self._load_node(db, "task-run", item["id"]); relation(node, focus_id, node["id"], "executed_as", "factual", "ausgeführt als")
            for item in db.execute("SELECT id FROM approvals WHERE task_id=?", (raw_id,)):
                node = self._load_node(db, "approval", item["id"]); relation(node, focus_id, node["id"], "has_approval", "factual", "besitzt Freigabe")
        elif node_type == "task-run":
            row = db.execute("SELECT task_id FROM task_runs WHERE id=?", (raw_id,)).fetchone()
            node = self._load_node(db, "scheduled-task", row["task_id"]); relation(node, node["id"], focus_id, "executed_as", "factual", "ausgeführt als")
        elif node_type == "approval":
            row = db.execute("SELECT conversation_id,task_id FROM approvals WHERE id=?", (raw_id,)).fetchone()
            for key, kind in (("conversation_id", "conversation"), ("task_id", "scheduled-task")):
                if row[key]:
                    node = self._load_node(db, kind, row[key]); relation(node, node["id"], focus_id, "has_approval", "factual", "besitzt Freigabe")
        elif node_type == "audit-event":
            row = db.execute("SELECT conversation_id,task_id FROM audit_events WHERE id=?", (raw_id,)).fetchone()
            for key, kind in (("conversation_id", "conversation"), ("task_id", "scheduled-task")):
                if row[key]:
                    node = self._load_node(db, kind, row[key]); relation(node, node["id"], focus_id, "has_audit_event", "factual", "besitzt Audit-Ereignis")
        elif node_type == "web-source":
            for row, source_id, url, source in self._web_sources(db):
                if source_id == raw_id:
                    node = self._load_node(db, "message", row["id"]); relation(node, node["id"], focus_id, "source_available_for_message", "factual", "Quelle verfügbar", {"evidence": "Persistierte Nachrichtenmetadaten; keine Aussage über Nutzung als Beleg."})
        return list(nodes.values()), edges


class MemoryExplorerInspector(BrainwatchInspector):
    """Bounded, redacted and strictly read-only projection of Memory V2."""

    @staticmethod
    def _validate_limit(limit) -> int:
        try:
            parsed = int(limit)
        except (TypeError, ValueError):
            raise ValueError("Ungültige Seitengröße") from None
        if not 1 <= parsed <= MEMORY_EXPLORER_LIMIT:
            raise ValueError(f"Seitengröße muss zwischen 1 und {MEMORY_EXPLORER_LIMIT} liegen")
        return parsed

    @staticmethod
    def _validate_filter(value, allowed: set[str], label: str) -> str:
        value = str(value or "").strip()
        if value and value not in allowed:
            raise ValueError(f"Nicht unterstützter {label}")
        return value

    @staticmethod
    def _validate_scope(value) -> str:
        value = str(value or "").strip()
        if len(value) > 200 or any(ord(character) < 32 for character in value):
            raise ValueError("Ungültiger Memory-Scope")
        return value

    @staticmethod
    def _binding(kind: str, values: dict) -> str:
        encoded = json.dumps([kind, values], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _claim_summary(row) -> dict:
        return {
            "id": f"claim:{row['id']}", "claim_id": row["id"],
            "claim_kind": row["claim_kind"], "scope": row["scope"],
            "lifecycle": row["lifecycle"], "display_text": _preview(_public_text(row["display_text"]), 240),
            "verification_policy": row["verification_policy"],
            "valid_from": row["valid_from"], "valid_until": row["valid_until"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    @staticmethod
    def _claim_detail(row) -> dict:
        item = MemoryExplorerInspector._claim_summary(row)
        item.update({
            "canonical_key": _public_text(row["canonical_key"]),
            "slot_key": _public_text(row["slot_key"]) if row["slot_key"] is not None else None,
            "payload": _public_json(_decode_json_object(row["payload_json"])),
        })
        return item

    @staticmethod
    def _graph_claim(row) -> dict:
        return {
            "id": f"claim:{row['id']}", "claim_id": row["id"],
            "claim_kind": row["claim_kind"], "scope": row["scope"],
            "lifecycle": row["lifecycle"],
            "display_text": _preview(_public_text(row["display_text"]), 240),
            "verification_policy": row["verification_policy"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    @staticmethod
    def _graph_relation(row) -> dict:
        return {
            "id": f"memory-relation:{row['id']}", "relation_id": row["id"],
            "from_claim_id": f"claim:{row['from_claim_id']}",
            "to_claim_id": f"claim:{row['to_claim_id']}",
            "relation_type": row["relation_type"], "created_at": row["created_at"],
            "source_table": "memory_relations", "source_id": row["id"],
        }

    @staticmethod
    def _graph_limit(value, maximum: int, label: str) -> int:
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"Ungültiges {label}") from None
        if not 1 <= value <= maximum:
            raise ValueError(f"{label} muss zwischen 1 und {maximum} liegen")
        return value

    @staticmethod
    def _graph_claim_filter_sql(*, scope="", claim_kind="", lifecycle="", alias="c"):
        clauses, parameters = [], []
        if scope:
            clauses.append(f"{alias}.scope=?"); parameters.append(scope)
        if claim_kind:
            clauses.append(f"{alias}.claim_kind=?"); parameters.append(claim_kind)
        if lifecycle:
            clauses.append(f"{alias}.lifecycle=?"); parameters.append(lifecycle)
        return clauses, parameters

    @staticmethod
    def _graph_load_claims(db, claim_ids: set[str]) -> dict[str, sqlite3.Row]:
        rows = {}
        ordered = sorted(claim_ids)
        for start in range(0, len(ordered), 300):
            batch = ordered[start:start + 300]
            if not batch:
                continue
            placeholders = ",".join("?" for _ in batch)
            rows.update({row["id"]: row for row in db.execute(
                f"SELECT * FROM memory_claims WHERE id IN ({placeholders})", batch,
            )})
        return rows

    @staticmethod
    def _graph_claim_matches(row, *, scope="", claim_kind="", lifecycle="") -> bool:
        return bool(row) and (not scope or row["scope"] == scope) \
            and (not claim_kind or row["claim_kind"] == claim_kind) \
            and (not lifecycle or row["lifecycle"] == lifecycle)

    def graph_revision(self) -> dict:
        """Fingerprint persisted graph rows, including edits and removals."""
        import hashlib
        digest = hashlib.sha256()
        with closing(self._connect()) as db:
            for table in ("memory_claims", "memory_relations"):
                digest.update(table.encode())
                for row in db.execute(f"SELECT * FROM {table} ORDER BY id"):
                    digest.update(json.dumps(tuple(row), ensure_ascii=False).encode())
                    digest.update(b"\n")
        return {"revision": digest.hexdigest()}

    def statistics(self) -> dict:
        """Aggregate only persisted rows; no counts are inferred from rendered projections."""
        with closing(self._connect()) as db:
            lifecycle = {
                row["lifecycle"]: int(row["count"])
                for row in db.execute(
                    "SELECT lifecycle,COUNT(*) count FROM memory_claims GROUP BY lifecycle",
                )
            }
            claim_kinds = {
                row["claim_kind"]: int(row["count"])
                for row in db.execute(
                    "SELECT claim_kind,COUNT(*) count FROM memory_claims GROUP BY claim_kind",
                )
            }
            relation_types = {
                row["relation_type"]: int(row["count"])
                for row in db.execute(
                    "SELECT relation_type,COUNT(*) count FROM memory_relations GROUP BY relation_type",
                )
            }
            memory_counts = db.execute(
                """SELECT
                       (SELECT COUNT(*) FROM memory_claims) claims,
                       (SELECT COUNT(*) FROM memory_relations) relations,
                       (SELECT COUNT(*) FROM memory_observations) observations,
                       (SELECT COUNT(*) FROM memory_evidence) evidence,
                       (SELECT COUNT(*) FROM memory_learning_decisions) learning_decisions,
                       (SELECT COUNT(*) FROM memory_claims
                        WHERE julianday(created_at)>=julianday('now','-1 day')) claims_last_24h""",
            ).fetchone()
            ha = db.execute(
                """SELECT
                       COUNT(*) entities,
                       COUNT(DISTINCT json_extract(payload_json,'$.provider_metadata.domain')) domains,
                       COUNT(DISTINCT json_extract(payload_json,'$.provider_metadata.area')) areas,
                       SUM(json_extract(payload_json,'$.provider_metadata.availability')='unavailable') unavailable
                   FROM memory_claims
                   WHERE lifecycle='active' AND claim_kind='provider_binding'
                     AND json_extract(payload_json,'$.inventory_source')='home_assistant'""",
            ).fetchone()
            ha_retired = int(db.execute(
                """SELECT COUNT(*) FROM memory_claims
                   WHERE lifecycle='retired' AND claim_kind='provider_binding'
                     AND json_extract(payload_json,'$.inventory_source')='home_assistant'""",
            ).fetchone()[0])
            ha_relations = int(db.execute(
                """SELECT COUNT(DISTINCT r.id)
                   FROM memory_relations r JOIN memory_claims c
                     ON c.id=r.from_claim_id OR c.id=r.to_claim_id
                   WHERE c.lifecycle='active' AND c.claim_kind='provider_binding'
                     AND json_extract(c.payload_json,'$.inventory_source')='home_assistant'""",
            ).fetchone()[0])
            language_profiles = int(db.execute(
                """SELECT COUNT(*) FROM memory_claims
                   WHERE lifecycle='active'
                     AND json_extract(payload_json,'$.kind')='home_assistant_language_profile'""",
            ).fetchone()[0])
            largest_domain = db.execute(
                """SELECT json_extract(payload_json,'$.provider_metadata.domain') domain,
                          COUNT(*) count
                   FROM memory_claims
                   WHERE lifecycle='active' AND claim_kind='provider_binding'
                     AND json_extract(payload_json,'$.inventory_source')='home_assistant'
                     AND json_extract(payload_json,'$.provider_metadata.domain') IS NOT NULL
                   GROUP BY domain ORDER BY count DESC,domain LIMIT 1""",
            ).fetchone()
            tool_rows = db.execute(
                """SELECT tool,COUNT(*) total,
                          SUM(status IN ('completed','success')) successful,
                          SUM(status IN ('error','failed')) failed,
                          SUM(status='rejected') rejected,
                          SUM(status='outcome_uncertain') uncertain
                   FROM conversation_tool_events GROUP BY tool
                   ORDER BY total DESC,tool""",
            ).fetchall()
            tool_totals = {
                "total": sum(int(row["total"]) for row in tool_rows),
                "successful": sum(int(row["successful"] or 0) for row in tool_rows),
                "failed": sum(int(row["failed"] or 0) for row in tool_rows),
                "rejected": sum(int(row["rejected"] or 0) for row in tool_rows),
                "uncertain": sum(int(row["uncertain"] or 0) for row in tool_rows),
            }
            tool_totals["other"] = max(0, tool_totals["total"] - sum(
                tool_totals[key] for key in ("successful", "failed", "rejected", "uncertain")
            ))
            activity = db.execute(
                """SELECT
                       (SELECT COUNT(*) FROM turns) turns,
                       (SELECT COUNT(*) FROM conversations) conversations,
                       (SELECT COUNT(*) FROM memory_runtime_events) runtime_events,
                       (SELECT COUNT(DISTINCT claim_id) FROM memory_runtime_events
                        WHERE claim_id IS NOT NULL) claims_with_runtime_events,
                       (SELECT COUNT(DISTINCT relation_id) FROM memory_runtime_events
                        WHERE relation_id IS NOT NULL) relations_with_runtime_events""",
            ).fetchone()
            connected = db.execute(
                """SELECT c.id,c.display_text,c.claim_kind,COUNT(r.id) degree
                   FROM memory_claims c JOIN memory_relations r
                     ON c.id=r.from_claim_id OR c.id=r.to_claim_id
                   GROUP BY c.id,c.display_text,c.claim_kind
                   ORDER BY degree DESC,c.id LIMIT 1""",
            ).fetchone()
            active_runtime = db.execute(
                """SELECT c.id,c.display_text,COUNT(e.id) events
                   FROM memory_runtime_events e JOIN memory_claims c ON c.id=e.claim_id
                   GROUP BY c.id,c.display_text ORDER BY events DESC,c.id LIMIT 1""",
            ).fetchone()

        top_connected = None if connected is None else {
            "claim_id": f"claim:{connected['id']}",
            "display_text": _preview(_public_text(connected["display_text"]), 180),
            "claim_kind": connected["claim_kind"], "relations": int(connected["degree"]),
        }
        top_runtime = None if active_runtime is None else {
            "claim_id": f"claim:{active_runtime['id']}",
            "display_text": _preview(_public_text(active_runtime["display_text"]), 180),
            "events": int(active_runtime["events"]),
        }
        total_tools = tool_totals["total"]
        return {
            "source": "persisted_database_rows",
            "memory": {
                "claims": int(memory_counts["claims"]),
                "relations": int(memory_counts["relations"]),
                "lifecycle": lifecycle, "claim_kinds": claim_kinds,
                "relation_types": relation_types,
                "observations": int(memory_counts["observations"]),
                "evidence": int(memory_counts["evidence"]),
                "learning_decisions": int(memory_counts["learning_decisions"]),
                "claims_last_24h": int(memory_counts["claims_last_24h"]),
            },
            "home_assistant": {
                "active_entities": int(ha["entities"]), "retired_entities": ha_retired,
                "domains": int(ha["domains"]), "areas": int(ha["areas"]),
                "unavailable_entities": int(ha["unavailable"] or 0),
                "relations": ha_relations, "language_profiles": language_profiles,
                "largest_domain": None if largest_domain is None else {
                    "name": largest_domain["domain"], "entities": int(largest_domain["count"]),
                },
            },
            "tools": {
                **tool_totals,
                "success_rate": round(tool_totals["successful"] / total_tools, 4)
                if total_tools else None,
                "by_tool": [
                    {key: (int(row[key] or 0) if key != "tool" else row[key])
                     for key in ("tool", "total", "successful", "failed", "rejected", "uncertain")}
                    for row in tool_rows
                ],
            },
            "activity": {key: int(activity[key]) for key in activity.keys()},
            "fun_facts": {
                "most_connected_claim": top_connected,
                "most_runtime_active_claim": top_runtime,
                "busiest_tool": tool_rows[0]["tool"] if tool_rows else None,
            },
        }

    def working_memory_graph(self) -> dict:
        """Bounded metadata projection of actual temporary learning work; no inferred claims."""
        with closing(self._connect()) as db:
            db.execute('BEGIN')
            runtime = db.execute('SELECT * FROM conversation_learning_runtime WHERE singleton=1').fetchone()
            jobs = {r['status']: r['n'] for r in db.execute(
                'SELECT status,count(*) n FROM memory_learning_jobs GROUP BY status')}
            # Only temporary learning workspaces; interactive/private work is not
            # mixed into the learning projection. Completed work expires visually
            # after 15 minutes, independently of physical retention/cleanup.
            work = db.execute("SELECT t.*,w.title FROM memory_work_turns t "
                "JOIN memory_workspaces w ON w.id=t.workspace_id "
                "JOIN memory_work_objects request ON request.id=t.request_id "
                "JOIN memory_observations source ON source.id=request.observation_id "
                "LEFT JOIN memory_learning_jobs job ON "
                "json_extract(source.structured_value_json,'$.trace_id')='conversation-learning:'||job.turn_id "
                "WHERE w.retention_class='temporary_learning' AND "
                "((t.status='running' AND job.status='running' "
                "AND julianday(t.created_at)>=julianday(job.started_at)) OR "
                "(t.status!='running' AND julianday(t.updated_at)>=julianday('now','-15 minutes'))) "
                "ORDER BY (t.status='running') DESC,t.updated_at DESC LIMIT 3").fetchall()
            nodes, edges, events, turns = {}, {}, [], []
            for turn in work:
                tid, wid = turn['id'], turn['workspace_id']
                calls = db.execute('SELECT c.*,v.structured_value_json parameters FROM memory_work_calls c '
                    'JOIN memory_work_objects o ON o.id=c.request_id '
                    'JOIN memory_observations v ON v.id=o.observation_id '
                    'WHERE c.turn_id=? ORDER BY c.created_at DESC,c.id DESC LIMIT 12', (tid,)).fetchall()
                totals = db.execute("SELECT count(*) calls,sum(operation='read') reads,"
                    "sum(operation='inspect') inspections,max(updated_at) last_activity_at "
                    "FROM memory_work_calls WHERE turn_id=?", (tid,)).fetchone()
                resets = db.execute("SELECT count(*) FROM memory_work_contexts "
                    "WHERE turn_id=? AND reason='fresh_context'", (tid,)).fetchone()[0]
                turns.append({'id': tid, 'workspace_id': wid, 'status': turn['status'],
                    'started_at': turn['created_at'], **dict(totals), 'context_frames': resets,
                    'shown_calls': len(calls)})

                def add_object(identifier):
                    if not identifier:
                        return None
                    key = 'work:' + identifier
                    if key not in nodes:
                        obj = db.execute('SELECT id,kind,title,media_type,byte_count,created_at '
                            'FROM memory_work_objects WHERE (id=? OR observation_id=?) AND workspace_id=?',
                            (identifier, identifier, wid)).fetchone()
                        if obj is None:
                            return None
                        key = 'work:' + obj['id']
                        nodes[key] = {'id': key, 'node_kind': 'working_material', 'object_id': obj['id'],
                            'workspace_id': wid, 'work_turn_id': tid, 'scope': 'working:' + wid,
                            'display_text': _public_text(obj['title'])[:160] or obj['kind'],
                            'work_status': turn['status'],
                            **{field: obj[field] for field in ('kind', 'media_type', 'byte_count', 'created_at')}}
                    return key

                add_object(turn['request_id'])
                for call in reversed(calls):
                    request_id = add_object(call['request_id'])
                    result_id = add_object(call['result_id'])
                    parameters = json.loads(call['parameters'])
                    reference = parameters.get('reference') if isinstance(parameters, dict) else None
                    source_id = add_object(reference) if isinstance(reference, str) else None
                    edge_ids = []
                    for suffix, source, target, label in (
                        ('read', source_id, request_id, call['operation']),
                        ('result', request_id, result_id, 'Ergebnis')):
                        if source and target:
                            key = 'work-edge:' + call['id'] + ':' + suffix
                            edges[key] = {'id': key, 'node_kind': 'working_link',
                                'from_claim_id': source, 'to_claim_id': target,
                                'relation_type': label, 'call_id': call['id'], 'status': call['status']}
                            edge_ids.append(key)
                    events.append({'id': call['id'] + ':' + call['status'],
                        'work_turn_id': tid,
                        'occurred_at': call['updated_at'], 'status': call['status'],
                        'node_ids': list(dict.fromkeys(x for x in (source_id, request_id, result_id) if x)),
                        'edge_ids': edge_ids})
        result = {'version': 'working-memory-graph-v1', 'observed_at': datetime.now().astimezone().isoformat(),
            'nodes': list(nodes.values()), 'edges': list(edges.values()), 'events': events,
            'turns': turns, 'jobs': jobs,
            'runtime': {'status': runtime['status'], 'batch_started_at': runtime['last_started_at'],
                        'batch_size': len(json.loads(runtime['current_batch_json']))} if runtime else {},
            'coverage': {'max_work_turns': 3, 'max_calls_per_turn': 12, 'recent_minutes': 15},
            'durable_claims': False}
        # Preserve whole call projections when enforcing the explorer's transport
        # budget. Counters still describe all calls, not just this bounded view.
        roots = {'work:' + turn['request_id'] for turn in work if turn['request_id']}
        result['events'].sort(key=lambda event: (event['occurred_at'], event['id']))
        while len(json.dumps(result, ensure_ascii=False).encode()) > MEMORY_EXPLORER_JSON_BUDGET and result['events']:
            result['events'].pop(0)
            edge_ids = {key for event in result['events'] for key in event['edge_ids']}
            node_ids = roots | {key for event in result['events'] for key in event['node_ids']}
            result['edges'] = [edge for edge in result['edges'] if edge['id'] in edge_ids]
            result['nodes'] = [node for node in result['nodes'] if node['id'] in node_ids]
        for turn in result['turns']:
            turn['shown_calls'] = sum(event['work_turn_id'] == turn['id'] for event in result['events'])
        return result

    def memory_graph(self, *, anchor_claim_id="", scope="", claim_kind="", lifecycle="",
                     relation_type="", depth=1, cursor="", node_limit=160,
                     edge_limit=320) -> dict:
        """Bounded projection where every node and edge is a persisted Memory-v2 row."""
        anchor_claim_id = self._runtime_identifier(
            anchor_claim_id, "claim", "Anchor-Claim-ID",
        )
        scope = self._validate_scope(scope)
        claim_kind = self._validate_filter(claim_kind, CLAIM_KINDS, "Claim-Art")
        lifecycle = self._validate_filter(lifecycle, CLAIM_LIFECYCLES, "Lifecycle")
        relation_type = self._validate_filter(relation_type, RELATION_TYPES, "Relationstyp")
        node_limit = self._graph_limit(node_limit, MEMORY_GRAPH_NODE_LIMIT, "Knotenlimit")
        edge_limit = self._graph_limit(edge_limit, MEMORY_GRAPH_EDGE_LIMIT, "Kantenlimit")
        try:
            depth = int(depth)
        except (TypeError, ValueError):
            raise ValueError("Ungültige Graph-Tiefe") from None
        if not 0 <= depth <= MEMORY_GRAPH_MAX_DEPTH:
            raise ValueError(f"Graph-Tiefe muss zwischen 0 und {MEMORY_GRAPH_MAX_DEPTH} liegen")
        if anchor_claim_id and cursor:
            raise ValueError("Anchor-Graphen verwenden keinen Cursor")
        filters = {
            "anchor_claim_id": anchor_claim_id, "scope": scope,
            "claim_kind": claim_kind, "lifecycle": lifecycle,
            "relation_type": relation_type, "depth": depth,
            "node_limit": node_limit, "edge_limit": edge_limit,
        }
        binding = self._binding("memory_graph", filters)
        cursor_values = _decode_cursor(cursor, binding) if cursor else None
        nodes, edges = {}, {}
        primary_rows = []
        edge_truncated = False

        with closing(self._connect()) as db:
            claim_clauses, claim_parameters = self._graph_claim_filter_sql(
                scope=scope, claim_kind=claim_kind, lifecycle=lifecycle,
            )
            total_where = " AND ".join(claim_clauses) if claim_clauses else "1=1"
            total_claims = int(db.execute(
                f"SELECT COUNT(*) FROM memory_claims c WHERE {total_where}", claim_parameters,
            ).fetchone()[0])

            if anchor_claim_id:
                anchor = db.execute(
                    "SELECT * FROM memory_claims WHERE id=?", (anchor_claim_id,),
                ).fetchone()
                if anchor is None:
                    raise KeyError("Anchor-Claim wurde nicht gefunden")
                if not self._graph_claim_matches(
                    anchor, scope=scope, claim_kind=claim_kind, lifecycle=lifecycle,
                ):
                    raise ValueError("Anchor-Claim entspricht nicht den gewählten Filtern")
                nodes[anchor_claim_id] = anchor
                frontier = {anchor_claim_id}
                for _level in range(depth):
                    if not frontier or len(nodes) >= node_limit or len(edges) >= edge_limit:
                        break
                    placeholders = ",".join("?" for _ in frontier)
                    relation_clauses = [
                        f"(from_claim_id IN ({placeholders}) OR to_claim_id IN ({placeholders}))",
                    ]
                    parameters = [*sorted(frontier), *sorted(frontier)]
                    if relation_type:
                        relation_clauses.append("relation_type=?"); parameters.append(relation_type)
                    rows = db.execute(
                        f"SELECT * FROM memory_relations WHERE {' AND '.join(relation_clauses)} "
                        "ORDER BY created_at,id LIMIT ?",
                        (*parameters, edge_limit - len(edges) + 1),
                    ).fetchall()
                    if len(rows) > edge_limit - len(edges):
                        edge_truncated = True
                    rows = rows[:edge_limit - len(edges)]
                    candidate_ids = {
                        value for row in rows for value in (row["from_claim_id"], row["to_claim_id"])
                    }
                    candidate_rows = self._graph_load_claims(db, candidate_ids)
                    next_frontier = set()
                    for row in rows:
                        left, right = row["from_claim_id"], row["to_claim_id"]
                        for claim_id in (left, right):
                            candidate = candidate_rows.get(claim_id)
                            if claim_id != anchor_claim_id and not self._graph_claim_matches(
                                candidate, scope=scope, claim_kind=claim_kind, lifecycle=lifecycle,
                            ):
                                break
                        else:
                            required = {left, right} - nodes.keys()
                            if len(nodes) + len(required) > node_limit:
                                edge_truncated = True
                                continue
                            for claim_id in required:
                                nodes[claim_id] = candidate_rows[claim_id]
                                next_frontier.add(claim_id)
                            edges[row["id"]] = row
                    frontier = next_frontier
                primary_rows = list(nodes.values())
                has_more = edge_truncated or bool(frontier and len(nodes) >= node_limit)
                next_cursor = None
            else:
                page_clauses = list(claim_clauses)
                page_parameters = list(claim_parameters)
                if cursor_values:
                    page_clauses.append("(c.created_at<? OR (c.created_at=? AND c.id<?))")
                    page_parameters.extend((cursor_values[0], cursor_values[0], cursor_values[1]))
                page_where = " AND ".join(page_clauses) if page_clauses else "1=1"
                page_rows = db.execute(
                    f"SELECT c.* FROM memory_claims c WHERE {page_where} "
                    "ORDER BY c.created_at DESC,c.id DESC LIMIT ?",
                    (*page_parameters, node_limit + 1),
                ).fetchall()
                primary_rows = page_rows[:node_limit]
                nodes.update({row["id"]: row for row in primary_rows})
                primary_ids = sorted(nodes)
                if primary_ids:
                    placeholders = ",".join("?" for _ in primary_ids)
                    relation_clauses = [
                        f"(from_claim_id IN ({placeholders}) OR to_claim_id IN ({placeholders}))",
                    ]
                    relation_parameters = [*primary_ids, *primary_ids]
                    if relation_type:
                        relation_clauses.append("relation_type=?")
                        relation_parameters.append(relation_type)
                    relation_rows = db.execute(
                        f"SELECT * FROM memory_relations WHERE {' AND '.join(relation_clauses)} "
                        "ORDER BY created_at,id LIMIT ?",
                        (*relation_parameters, edge_limit + 1),
                    ).fetchall()
                    edge_truncated = len(relation_rows) > edge_limit
                    relation_rows = relation_rows[:edge_limit]
                    endpoint_ids = {
                        value for row in relation_rows
                        for value in (row["from_claim_id"], row["to_claim_id"])
                    }
                    endpoint_rows = self._graph_load_claims(db, endpoint_ids)
                    for row in relation_rows:
                        left, right = row["from_claim_id"], row["to_claim_id"]
                        if not all(self._graph_claim_matches(
                            endpoint_rows.get(claim_id), scope=scope,
                            claim_kind=claim_kind, lifecycle=lifecycle,
                        ) for claim_id in (left, right)):
                            continue
                        required = {left, right} - nodes.keys()
                        if len(nodes) + len(required) > MEMORY_GRAPH_RESPONSE_NODE_LIMIT:
                            edge_truncated = True
                            continue
                        for claim_id in required:
                            nodes[claim_id] = endpoint_rows[claim_id]
                        edges[row["id"]] = row
                has_more = len(page_rows) > node_limit
                next_cursor = _encode_cursor(
                    primary_rows[-1]["created_at"], primary_rows[-1]["id"], binding,
                ) if has_more and primary_rows else None

            relation_count_clauses = []
            relation_count_parameters = []
            if relation_type:
                relation_count_clauses.append("r.relation_type=?")
                relation_count_parameters.append(relation_type)
            for alias in ("f", "t"):
                clauses, parameters = self._graph_claim_filter_sql(
                    scope=scope, claim_kind=claim_kind, lifecycle=lifecycle, alias=alias,
                )
                relation_count_clauses.extend(clauses)
                relation_count_parameters.extend(parameters)
            relation_count_where = " AND ".join(relation_count_clauses) \
                if relation_count_clauses else "1=1"
            total_relations = int(db.execute(
                f"""SELECT COUNT(*) FROM memory_relations r
                    JOIN memory_claims f ON f.id=r.from_claim_id
                    JOIN memory_claims t ON t.id=r.to_claim_id
                    WHERE {relation_count_where}""",
                relation_count_parameters,
            ).fetchone()[0])

        result = {
            "layout_contract": {
                "version": "neurocloud-layout-v3-provenance-regions",
                "position_is_semantic": False,
                "node_identity": "memory_claims.id",
                "edge_identity": "memory_relations.id",
                "activity_included": False,
            },
            "anchor_claim_id": f"claim:{anchor_claim_id}" if anchor_claim_id else None,
            "filters": {key: value or None for key, value in filters.items()},
            "nodes": [], "edges": [],
            "coverage": {
                "matching_claims": total_claims, "matching_relations": total_relations,
                "loaded_claims": 0, "loaded_relations": 0, "primary_claims": 0,
                "complete": False,
                "edge_truncated": edge_truncated,
            },
            "page": {
                "node_limit": node_limit, "edge_limit": edge_limit,
                "has_more": has_more, "next_cursor": next_cursor,
            },
        }
        primary_ids, included_ids = [], set()
        for row in primary_rows:
            if row["id"] in included_ids:
                continue
            result["nodes"].append(self._graph_claim(row))
            if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 40 * 1024:
                result["nodes"].pop()
                has_more = True
                break
            primary_ids.append(row["id"]); included_ids.add(row["id"])
        for row in sorted(nodes.values(), key=lambda item: (item["created_at"], item["id"])):
            if row["id"] in included_ids:
                continue
            result["nodes"].append(self._graph_claim(row))
            if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 48 * 1024:
                result["nodes"].pop()
                edge_truncated = True
                break
            included_ids.add(row["id"])
        for row in sorted(edges.values(), key=lambda item: (item["created_at"], item["id"])):
            if row["from_claim_id"] not in included_ids or row["to_claim_id"] not in included_ids:
                edge_truncated = True
                continue
            result["edges"].append(self._graph_relation(row))
            if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 60 * 1024:
                result["edges"].pop()
                edge_truncated = True
                break
        result["coverage"].update(
            loaded_claims=len(result["nodes"]), loaded_relations=len(result["edges"]),
            primary_claims=len(primary_ids), edge_truncated=edge_truncated,
            complete=(not has_more and not edge_truncated and len(result["nodes"]) >= total_claims),
        )
        result["page"]["has_more"] = has_more or edge_truncated
        if not anchor_claim_id and primary_ids and (has_more or len(primary_ids) < len(primary_rows)):
            last = next(row for row in reversed(primary_rows) if row["id"] in set(primary_ids))
            result["page"]["next_cursor"] = _encode_cursor(last["created_at"], last["id"], binding)
        elif anchor_claim_id:
            result["page"]["next_cursor"] = None
        return result

    def memory_graph_relations(self, *, scope="", claim_kind="", lifecycle="",
                               relation_type="", cursor="", limit=200) -> dict:
        """Page every persisted relation whose two endpoints match the claim filters."""
        scope = self._validate_scope(scope)
        claim_kind = self._validate_filter(claim_kind, CLAIM_KINDS, "Claim-Art")
        lifecycle = self._validate_filter(lifecycle, CLAIM_LIFECYCLES, "Lifecycle")
        relation_type = self._validate_filter(relation_type, RELATION_TYPES, "Relationstyp")
        limit = self._graph_limit(limit, MEMORY_GRAPH_EDGE_LIMIT, "Relationslimit")
        filters = {
            "scope": scope, "claim_kind": claim_kind, "lifecycle": lifecycle,
            "relation_type": relation_type, "limit": limit,
        }
        binding = self._binding("memory_graph_relations", filters)
        cursor_values = _decode_cursor(cursor, binding) if cursor else None
        clauses, parameters = [], []
        if relation_type:
            clauses.append("r.relation_type=?"); parameters.append(relation_type)
        for alias in ("f", "t"):
            endpoint_clauses, endpoint_parameters = self._graph_claim_filter_sql(
                scope=scope, claim_kind=claim_kind, lifecycle=lifecycle, alias=alias,
            )
            clauses.extend(endpoint_clauses); parameters.extend(endpoint_parameters)
        if cursor_values:
            clauses.append("(r.created_at<? OR (r.created_at=? AND r.id<?))")
            parameters.extend((cursor_values[0], cursor_values[0], cursor_values[1]))
        where = " AND ".join(clauses) if clauses else "1=1"
        count_clauses = clauses[:-1] if cursor_values else clauses
        count_parameters = parameters[:-3] if cursor_values else parameters
        count_where = " AND ".join(count_clauses) if count_clauses else "1=1"
        with closing(self._connect()) as db:
            total = int(db.execute(
                f"""SELECT COUNT(*) FROM memory_relations r
                    JOIN memory_claims f ON f.id=r.from_claim_id
                    JOIN memory_claims t ON t.id=r.to_claim_id
                    WHERE {count_where}""", count_parameters,
            ).fetchone()[0])
            rows = db.execute(
                f"""SELECT r.* FROM memory_relations r
                    JOIN memory_claims f ON f.id=r.from_claim_id
                    JOIN memory_claims t ON t.id=r.to_claim_id
                    WHERE {where} ORDER BY r.created_at DESC,r.id DESC LIMIT ?""",
                (*parameters, limit + 1),
            ).fetchall()
        items = rows[:limit]
        has_more = len(rows) > limit
        next_cursor = _encode_cursor(
            items[-1]["created_at"], items[-1]["id"], binding,
        ) if has_more and items else None
        return {
            "items": [self._graph_relation(row) for row in items],
            "matching_relations": total,
            "page": {"limit": limit, "has_more": has_more, "next_cursor": next_cursor},
        }

    @staticmethod
    def _fts_expression(query: str) -> str:
        tokens = list(dict.fromkeys(_SEARCH_TOKEN.findall(query.casefold())))[:12]
        return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens if token)

    def claims(self, *, query="", scope="", claim_kind="", lifecycle="",
               verification_policy="", cursor="", limit=20) -> dict:
        query = " ".join(str(query or "").split())
        if len(query) > 300:
            raise ValueError("Suchtext darf höchstens 300 Zeichen lang sein")
        scope = self._validate_scope(scope)
        claim_kind = self._validate_filter(claim_kind, CLAIM_KINDS, "Claim-Art")
        lifecycle = self._validate_filter(lifecycle, CLAIM_LIFECYCLES, "Lifecycle")
        verification_policy = self._validate_filter(
            verification_policy, VERIFICATION_POLICIES, "Verification Policy",
        )
        limit = self._validate_limit(limit)
        filters = {
            "query": query, "scope": scope, "claim_kind": claim_kind,
            "lifecycle": lifecycle, "verification_policy": verification_policy,
        }
        binding = self._binding("claims", filters)
        cursor_values = _decode_cursor(cursor, binding) if cursor else None
        where, params = [], []
        for column, value in (
            ("c.scope", scope), ("c.claim_kind", claim_kind),
            ("c.lifecycle", lifecycle), ("c.verification_policy", verification_policy),
        ):
            if value:
                where.append(f"{column}=?")
                params.append(value)
        if cursor_values:
            where.append("(c.updated_at<? OR (c.updated_at=? AND c.id<?))")
            params.extend((cursor_values[0], cursor_values[0], cursor_values[1]))
        search_mode = "browse"
        expression = self._fts_expression(query) if query else ""
        if query and not expression:
            return {
                "items": [], "filters": filters, "search_mode": "fts_no_terms",
                "page": {"limit": limit, "has_more": False, "next_cursor": None},
            }
        base_where = " AND ".join(where) if where else "1=1"
        with closing(self._connect()) as db:
            try:
                if query:
                    sql = f"""SELECT c.* FROM memory_claims_fts f
                        JOIN memory_claims c ON c.id=f.claim_id
                        WHERE f.memory_claims_fts MATCH ? AND {base_where}
                        ORDER BY c.updated_at DESC,c.id DESC LIMIT ?"""
                    rows = db.execute(sql, (expression, *params, limit + 1)).fetchall()
                    search_mode = "fts"
                else:
                    rows = db.execute(
                        f"""SELECT c.* FROM memory_claims c WHERE {base_where}
                            ORDER BY c.updated_at DESC,c.id DESC LIMIT ?""",
                        (*params, limit + 1),
                    ).fetchall()
            except sqlite3.OperationalError:
                # Bounded degradation only. It never scans JSON payloads and the
                # response explicitly exposes that FTS was unavailable.
                fallback_where = [*where, "c.display_text LIKE ? ESCAPE '\\'"]
                needle = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                rows = db.execute(
                    f"""SELECT c.* FROM memory_claims c WHERE {' AND '.join(fallback_where)}
                        ORDER BY c.updated_at DESC,c.id DESC LIMIT ?""",
                    (*params, needle, limit + 1),
                ).fetchall()
                search_mode = "bounded_like_fallback"
        visible = rows[:limit]
        next_cursor = None
        if len(rows) > limit and visible:
            next_cursor = _encode_cursor(visible[-1]["updated_at"], visible[-1]["id"], binding)
        result = _public_json({
            "items": [self._claim_summary(row) for row in visible],
            "filters": filters, "search_mode": search_mode,
            "page": {"limit": limit, "has_more": next_cursor is not None,
                     "next_cursor": None},
        })
        result["page"]["next_cursor"] = next_cursor
        return result

    def _claim_row(self, db, claim_id: str):
        claim_id = str(claim_id or "")
        if not claim_id or len(claim_id) > 512 or "/" in claim_id:
            raise ValueError("Ungültige Claim-ID")
        row = db.execute("SELECT * FROM memory_claims WHERE id=?", (claim_id,)).fetchone()
        if row is None:
            raise KeyError(claim_id)
        return row

    def claim(self, claim_id: str) -> dict:
        with closing(self._connect()) as db:
            row = self._claim_row(db, claim_id)
            evidence_count = db.execute(
                "SELECT COUNT(*) FROM memory_evidence WHERE claim_id=?", (claim_id,),
            ).fetchone()[0]
            outgoing_count = db.execute(
                "SELECT COUNT(*) FROM memory_relations WHERE from_claim_id=?", (claim_id,),
            ).fetchone()[0]
            incoming_count = db.execute(
                "SELECT COUNT(*) FROM memory_relations WHERE to_claim_id=?", (claim_id,),
            ).fetchone()[0]
            history_rows = db.execute(
                """SELECT r.*,f.claim_kind from_kind,f.scope from_scope,f.lifecycle from_lifecycle,
                          f.display_text from_text,f.verification_policy from_policy,
                          f.valid_from from_valid_from,f.valid_until from_valid_until,
                          f.created_at from_created_at,f.updated_at from_updated_at,
                          t.claim_kind to_kind,t.scope to_scope,t.lifecycle to_lifecycle,
                          t.display_text to_text,t.verification_policy to_policy,
                          t.valid_from to_valid_from,t.valid_until to_valid_until,
                          t.created_at to_created_at,t.updated_at to_updated_at
                   FROM memory_relations r
                   JOIN memory_claims f ON f.id=r.from_claim_id
                   JOIN memory_claims t ON t.id=r.to_claim_id
                   WHERE r.relation_type='supersedes'
                     AND (r.from_claim_id=? OR r.to_claim_id=?)
                   ORDER BY r.created_at DESC,r.id DESC LIMIT 21""",
                (claim_id, claim_id),
            ).fetchall()
        history = [self._relation_item(item, claim_id) for item in history_rows[:20]]
        return _public_json({
            "claim": self._claim_detail(row),
            "counts": {"evidence": evidence_count, "relations_incoming": incoming_count,
                       "relations_outgoing": outgoing_count},
            "history": {"basis": "stored_supersedes_relations_only", "items": history,
                        "truncated": len(history_rows) > 20,
                        "complete_change_history_available": False},
        })

    @staticmethod
    def _provenance_status(row) -> str:
        observation = bool(row["observation_id"] and row["observation_source_type"])
        located = any(row[key] for key in (
            "source_ref", "source_turn_id", "source_message_id", "tool_event_id",
            "observation_turn_id", "observation_message_id", "observation_tool_event_id",
            "observation_external_ref",
        ))
        if observation and located:
            return "available"
        if observation or located:
            return "partial"
        return "not_recorded"

    @staticmethod
    def _evidence_item(row) -> dict:
        observation = None
        if row["observation_id"]:
            observation = {
                "id": f"observation:{row['observation_id']}",
                "observation_id": row["observation_id"],
                "source_type": row["observation_source_type"],
                "source_role": row["observation_source_role"],
                "message_id": row["observation_message_id"],
                "turn_id": row["observation_turn_id"],
                "tool_event_id": row["observation_tool_event_id"],
                "external_ref": _public_text(row["observation_external_ref"]),
                "excerpt": _public_text(row["observation_excerpt"]),
                "observed_at": row["observation_observed_at"],
                "structured_value": _public_json(
                    _decode_json_object(row["observation_structured_value_json"]), budget=16 * 1024,
                ),
            }
        return {
            "id": f"evidence:{row['id']}", "evidence_id": row["id"],
            "claim_id": f"claim:{row['claim_id']}", "raw_claim_id": row["claim_id"],
            "stance": row["stance"], "evidence_type": row["evidence_type"],
            "source_ref": _public_text(row["source_ref"]),
            "source_turn_id": row["source_turn_id"],
            "source_message_id": row["source_message_id"],
            "tool_event_id": row["tool_event_id"],
            "excerpt": _public_text(row["excerpt"]),
            "payload": _public_json(_decode_json_object(row["payload_json"]), budget=16 * 1024),
            "observed_at": row["observed_at"], "effective_from": row["effective_from"],
            "effective_until": row["effective_until"], "created_at": row["created_at"],
            "observation": observation,
            "provenance_status": MemoryExplorerInspector._provenance_status(row),
        }

    def evidence(self, claim_id: str, *, cursor="", limit=20) -> dict:
        limit = self._validate_limit(limit)
        binding = self._binding("evidence", {"claim_id": str(claim_id)})
        cursor_values = _decode_cursor(cursor, binding) if cursor else None
        where = "e.claim_id=?"
        params = [str(claim_id)]
        if cursor_values:
            where += " AND (e.created_at<? OR (e.created_at=? AND e.id<?))"
            params.extend((cursor_values[0], cursor_values[0], cursor_values[1]))
        with closing(self._connect()) as db:
            self._claim_row(db, claim_id)
            rows = db.execute(
                f"""SELECT e.*,
                    o.source_type observation_source_type,o.source_role observation_source_role,
                    o.message_id observation_message_id,o.turn_id observation_turn_id,
                    o.tool_event_id observation_tool_event_id,o.external_ref observation_external_ref,
                    o.excerpt observation_excerpt,o.observed_at observation_observed_at,
                    o.structured_value_json observation_structured_value_json
                    FROM memory_evidence e LEFT JOIN memory_observations o ON o.id=e.observation_id
                    WHERE {where} ORDER BY e.created_at DESC,e.id DESC LIMIT ?""",
                (*params, limit + 1),
            ).fetchall()
        visible = rows[:limit]
        next_cursor = _encode_cursor(visible[-1]["created_at"], visible[-1]["id"], binding) \
            if len(rows) > limit and visible else None
        result = _public_json({
            "claim_id": f"claim:{claim_id}",
            "items": [self._evidence_item(row) for row in visible],
            "page": {"limit": limit, "has_more": next_cursor is not None,
                     "next_cursor": None},
        })
        result["page"]["next_cursor"] = next_cursor
        return result

    @staticmethod
    def _related_claim(row, prefix: str) -> dict:
        return {
            "id": f"claim:{row[prefix + '_claim_id']}",
            "claim_id": row[prefix + "_claim_id"],
            "claim_kind": row[prefix + "_kind"], "scope": row[prefix + "_scope"],
            "lifecycle": row[prefix + "_lifecycle"],
            "display_text": _public_text(row[prefix + "_text"]),
            "verification_policy": row[prefix + "_policy"],
            "valid_from": row[prefix + "_valid_from"],
            "valid_until": row[prefix + "_valid_until"],
            "created_at": row[prefix + "_created_at"],
            "updated_at": row[prefix + "_updated_at"],
        }

    @classmethod
    def _relation_item(cls, row, focus_claim_id: str) -> dict:
        evidence = None
        if "evidence_type" in row.keys() and row["evidence_id"]:
            evidence = {
                "id": f"evidence:{row['evidence_id']}",
                "evidence_id": row["evidence_id"], "stance": row["evidence_stance"],
                "evidence_type": row["evidence_type"],
                "created_at": row["evidence_created_at"],
            }
        return {
            "id": f"memory-relation:{row['id']}", "relation_id": row["id"],
            "relation_type": row["relation_type"],
            "direction": "outgoing" if row["from_claim_id"] == focus_claim_id else "incoming",
            "from_claim": cls._related_claim(row, "from"),
            "to_claim": cls._related_claim(row, "to"),
            "evidence": evidence, "created_at": row["created_at"],
            "interpretation": "stored_relation_only",
        }

    def relations(self, claim_id: str, *, relation_type="", cursor="", limit=30) -> dict:
        relation_type = self._validate_filter(relation_type, RELATION_TYPES, "Relationstyp")
        limit = self._validate_limit(limit)
        binding = self._binding(
            "relations", {"claim_id": str(claim_id), "relation_type": relation_type},
        )
        cursor_values = _decode_cursor(cursor, binding) if cursor else None
        where = ["(r.from_claim_id=? OR r.to_claim_id=?)"]
        params = [str(claim_id), str(claim_id)]
        if relation_type:
            where.append("r.relation_type=?")
            params.append(relation_type)
        if cursor_values:
            where.append("(r.created_at<? OR (r.created_at=? AND r.id<?))")
            params.extend((cursor_values[0], cursor_values[0], cursor_values[1]))
        with closing(self._connect()) as db:
            self._claim_row(db, claim_id)
            rows = db.execute(
                f"""SELECT r.*,
                    f.id from_claim_id,f.claim_kind from_kind,f.scope from_scope,
                    f.lifecycle from_lifecycle,f.display_text from_text,
                    f.verification_policy from_policy,f.valid_from from_valid_from,
                    f.valid_until from_valid_until,f.created_at from_created_at,
                    f.updated_at from_updated_at,
                    t.id to_claim_id,t.claim_kind to_kind,t.scope to_scope,
                    t.lifecycle to_lifecycle,t.display_text to_text,
                    t.verification_policy to_policy,t.valid_from to_valid_from,
                    t.valid_until to_valid_until,t.created_at to_created_at,
                    t.updated_at to_updated_at,
                    e.stance evidence_stance,e.evidence_type evidence_type,
                    e.created_at evidence_created_at
                    FROM memory_relations r
                    JOIN memory_claims f ON f.id=r.from_claim_id
                    JOIN memory_claims t ON t.id=r.to_claim_id
                    LEFT JOIN memory_evidence e ON e.id=r.evidence_id
                    WHERE {' AND '.join(where)}
                    ORDER BY r.created_at DESC,r.id DESC LIMIT ?""",
                (*params, limit + 1),
            ).fetchall()
        visible = rows[:limit]
        next_cursor = _encode_cursor(visible[-1]["created_at"], visible[-1]["id"], binding) \
            if len(rows) > limit and visible else None
        result = _public_json({
            "claim_id": f"claim:{claim_id}", "relation_type": relation_type or None,
            "items": [self._relation_item(row, str(claim_id)) for row in visible],
            "page": {"limit": limit, "has_more": next_cursor is not None,
                     "next_cursor": None},
        })
        result["page"]["next_cursor"] = next_cursor
        return result

    def _turn_row(self, db, turn_id: str):
        turn_id = str(turn_id or "")
        if not turn_id or len(turn_id) > 512 or "/" in turn_id:
            raise ValueError("Ungültige Turn-ID")
        row = db.execute(
            """SELECT t.*,c.title conversation_title
               FROM turns t JOIN conversations c ON c.id=t.conversation_id
               WHERE t.id=?""",
            (turn_id,),
        ).fetchone()
        if row is None:
            raise KeyError(turn_id)
        return row

    @staticmethod
    def _turn_summary(row) -> dict:
        return {
            "id": f"turn:{row['id']}", "turn_id": row["id"],
            "conversation_id": f"conversation:{row['conversation_id']}",
            "raw_conversation_id": row["conversation_id"],
            "conversation_title": _public_text(row["conversation_title"]),
            "created_at": row["created_at"], "completed_at": row["completed_at"],
        }

    @staticmethod
    def _link_filter(value, allowed: set[str], label: str) -> str:
        value = str(value or "").strip()
        if value and value not in allowed:
            raise ValueError(f"Nicht unterstützte {label}")
        return value

    @staticmethod
    def _link_source_query(db, sql: str, params: list, cursor_values, limit: int):
        if cursor_values:
            sql = f"""SELECT * FROM ({sql}) source_rows
                WHERE link_timestamp<? OR (link_timestamp=? AND sort_id<?)
                ORDER BY link_timestamp DESC,sort_id DESC LIMIT ?"""
            params = [*params, cursor_values[0], cursor_values[0], cursor_values[1], limit + 1]
        else:
            sql = f"""SELECT * FROM ({sql}) source_rows
                ORDER BY link_timestamp DESC,sort_id DESC LIMIT ?"""
            params = [*params, limit + 1]
        return db.execute(sql, params).fetchall()

    def _turn_links(self, *, claim_id=None, turn_id=None, origin_class="",
                    consumer="", cursor="", limit=20) -> dict:
        if (claim_id is None) == (turn_id is None):
            raise ValueError("Genau eine Navigationsrichtung muss angegeben werden")
        origin_class = self._link_filter(origin_class, MEMORY_TURN_ORIGINS, "Herkunftsklasse")
        consumer = self._link_filter(consumer, MEMORY_TURN_CONSUMERS, "Consumer-Angabe")
        limit = self._validate_limit(limit)
        target_kind = "claim" if claim_id is not None else "turn"
        target_id = str(claim_id if claim_id is not None else turn_id)
        binding = self._binding("claim_turn_links", {
            "target_kind": target_kind, "target_id": target_id,
            "origin_class": origin_class, "consumer": consumer,
        })
        cursor_values = _decode_cursor(cursor, binding) if cursor else None
        source_rows = []

        def target(claim_expression: str, turn_expression: str):
            return (f"{claim_expression}=?", [target_id]) if claim_id is not None \
                else (f"{turn_expression}=?", [target_id])

        def add_source(db, sql: str, params: list):
            source_rows.extend(self._link_source_query(
                db, sql, params, cursor_values, limit,
            ))

        with closing(self._connect()) as db:
            if claim_id is not None:
                self._claim_row(db, target_id)
            else:
                self._turn_row(db, target_id)

            if not consumer and origin_class in {"", "evidence_source_turn", "semantic_reuse_result"}:
                for source_path, joins, turn_expression, present_clause, message_expression, tool_expression in (
                    ("source_turn", "", "e.source_turn_id", "e.source_turn_id IS NOT NULL",
                     "e.source_message_id", "e.tool_event_id"),
                    ("source_message", "JOIN messages sm ON sm.id=e.source_message_id",
                     "sm.turn_id", "sm.turn_id IS NOT NULL", "e.source_message_id", "e.tool_event_id"),
                    ("tool_event", "JOIN conversation_tool_events et ON et.id=e.tool_event_id "
                     "JOIN messages tm ON tm.id=et.message_id", "tm.turn_id", "tm.turn_id IS NOT NULL",
                     "et.message_id", "e.tool_event_id"),
                ):
                    where, params = target("e.claim_id", turn_expression)
                    if origin_class == "semantic_reuse_result":
                        provenance = "e.evidence_type='reuse_result'"
                    elif origin_class == "evidence_source_turn":
                        provenance = "e.evidence_type!='reuse_result'"
                    else:
                        provenance = "1=1"
                    add_source(db, f"""SELECT e.claim_id,{turn_expression} turn_id,
                        CASE WHEN e.evidence_type='reuse_result' THEN 'semantic_reuse_result'
                             ELSE 'evidence_source_turn' END origin_class,
                        e.id source_id,'memory_evidence' source_table,e.created_at link_timestamp,
                        {message_expression} message_id,{tool_expression} tool_event_id,
                        NULL consumer,NULL compiler_stage,'{source_path}' source_path,
                        'e|' || printf('%016x',e.rowid) || '|{source_path}' sort_id,
                        e.evidence_type,e.stance,e.source_ref,e.observation_id
                        FROM memory_evidence e {joins}
                        WHERE {present_clause} AND {provenance} AND {where}""", params)

            if not consumer and origin_class in {"", "observation_turn", "semantic_reuse_result"}:
                for source_path, joins, turn_expression, present_clause, message_expression, tool_expression in (
                    ("observation_turn", "", "o.turn_id", "o.turn_id IS NOT NULL",
                     "o.message_id", "o.tool_event_id"),
                    ("observation_message", "JOIN messages om ON om.id=o.message_id",
                     "om.turn_id", "om.turn_id IS NOT NULL", "o.message_id", "o.tool_event_id"),
                    ("observation_tool_event", "JOIN conversation_tool_events ot ON ot.id=o.tool_event_id "
                     "JOIN messages otm ON otm.id=ot.message_id", "otm.turn_id", "otm.turn_id IS NOT NULL",
                     "ot.message_id", "o.tool_event_id"),
                ):
                    where, params = target("e.claim_id", turn_expression)
                    if origin_class == "semantic_reuse_result":
                        provenance = "e.evidence_type='reuse_result'"
                    elif origin_class == "observation_turn":
                        provenance = "e.evidence_type!='reuse_result'"
                    else:
                        provenance = "1=1"
                    add_source(db, f"""SELECT e.claim_id,{turn_expression} turn_id,
                        CASE WHEN e.evidence_type='reuse_result' THEN 'semantic_reuse_result'
                             ELSE 'observation_turn' END origin_class,
                        o.id source_id,'memory_observations' source_table,o.created_at link_timestamp,
                        {message_expression} message_id,{tool_expression} tool_event_id,
                        NULL consumer,NULL compiler_stage,'{source_path}' source_path,
                        'o|' || printf('%016x',o.rowid) || '|{source_path}|'
                            || printf('%016x',e.rowid) sort_id,
                        e.evidence_type,e.stance,e.source_ref,e.id evidence_id,
                        o.source_type observation_source_type,o.source_role observation_source_role,
                        o.external_ref observation_external_ref
                        FROM memory_evidence e JOIN memory_observations o ON o.id=e.observation_id
                        {joins} WHERE {present_clause} AND {provenance} AND {where}""", params)

            if not consumer and origin_class in {"", "learning_decision"}:
                where, params = target("dc.claim_id", "j.turn_id")
                add_source(db, f"""SELECT dc.claim_id,j.turn_id,'learning_decision' origin_class,
                    j.turn_id source_id,'memory_learning_jobs' source_table,d.created_at link_timestamp,
                    o.message_id,o.tool_event_id,NULL consumer,NULL compiler_stage,
                    'learning_job' source_path,
                    'd|' || printf('%016x',d.rowid) || '|job' sort_id,
                    d.id decision_id,d.decision_type,d.method,d.rationale,d.observation_id,
                    j.status learning_job_status
                    FROM memory_learning_decision_claims dc
                    JOIN memory_learning_decisions d ON d.id=dc.decision_id
                    JOIN memory_learning_jobs j ON j.decision_id=d.id
                    LEFT JOIN memory_observations o ON o.id=d.observation_id
                    WHERE {where}""", params)
                for source_path, joins, turn_expression, present_clause, message_expression, tool_expression in (
                    ("decision_observation_turn", "", "o.turn_id", "o.turn_id IS NOT NULL",
                     "o.message_id", "o.tool_event_id"),
                    ("decision_observation_message", "JOIN messages dm ON dm.id=o.message_id",
                     "dm.turn_id", "dm.turn_id IS NOT NULL", "o.message_id", "o.tool_event_id"),
                    ("decision_observation_tool_event", "JOIN conversation_tool_events dt ON dt.id=o.tool_event_id "
                     "JOIN messages dtm ON dtm.id=dt.message_id", "dtm.turn_id", "dtm.turn_id IS NOT NULL",
                     "dt.message_id", "o.tool_event_id"),
                ):
                    where, params = target("dc.claim_id", turn_expression)
                    add_source(db, f"""SELECT dc.claim_id,{turn_expression} turn_id,
                        'learning_decision' origin_class,d.id source_id,
                        'memory_learning_decisions' source_table,d.created_at link_timestamp,
                        {message_expression} message_id,{tool_expression} tool_event_id,
                        NULL consumer,NULL compiler_stage,'{source_path}' source_path,
                        'd|' || printf('%016x',d.rowid) || '|{source_path}' sort_id,
                        d.decision_type,d.method,d.rationale,d.observation_id,
                        o.source_type observation_source_type,o.source_role observation_source_role
                        FROM memory_learning_decision_claims dc
                        JOIN memory_learning_decisions d ON d.id=dc.decision_id
                        JOIN memory_observations o ON o.id=d.observation_id {joins}
                        WHERE {present_clause} AND {where}""", params)

            for stage, provenance in (("retrieved", "compiler_retrieved"),
                                      ("would_present", "compiler_would_present")):
                if origin_class not in {"", provenance}:
                    continue
                where, params = target("a.claim_id", "v.turn_id")
                consumer_clause = ""
                if consumer:
                    consumer_clause = " AND v.consumer=?"
                    params.append(consumer)
                add_source(db, f"""SELECT a.claim_id,v.turn_id,'{provenance}' origin_class,
                    v.id source_id,
                    'memory_compiler_claim_audit' source_table,v.created_at link_timestamp,
                    NULL message_id,NULL tool_event_id,v.consumer,a.stage compiler_stage,
                    'compiler_evaluation' source_path,
                    'a|' || printf('%016x',a.rowid) sort_id,
                    a.claim_id audit_claim_id,a.method,a.reason,a.requirement_class,a.token_cost,a.rank_score,
                    v.id evaluation_id,v.status evaluation_status,v.compiler_version
                    FROM memory_compiler_claim_audit a
                    JOIN memory_compiler_evaluations v ON v.id=a.evaluation_id
                    WHERE a.stage='{stage}' AND {where}{consumer_clause}""", params)

            if origin_class in {"", "usage_presented"}:
                where, params = target("u.claim_id", "u.turn_id")
                consumer_clause = ""
                if consumer:
                    consumer_clause = " AND u.consumer=?"
                    params.append(consumer)
                add_source(db, f"""SELECT u.claim_id,u.turn_id,'usage_presented' origin_class,
                    u.turn_id || ':' || u.consumer || ':' || u.claim_id || ':presented' source_id,
                    'memory_compiler_usage' source_table,u.created_at link_timestamp,
                    NULL message_id,NULL tool_event_id,u.consumer,'presented' compiler_stage,
                    'usage_record' source_path,
                    'u|' || printf('%016x',u.rowid) sort_id,u.usage
                    FROM memory_compiler_usage u
                    WHERE u.usage='presented' AND {where}{consumer_clause}""", params)

            ordered = sorted(
                source_rows, key=lambda row: (row["link_timestamp"], row["sort_id"]), reverse=True,
            )
            visible = ordered[:limit]
            claim_ids = sorted({row["claim_id"] for row in visible})
            turn_ids = sorted({row["turn_id"] for row in visible})
            claim_rows = {}
            if claim_ids:
                placeholders = ",".join("?" for _ in claim_ids)
                claim_rows = {row["id"]: row for row in db.execute(
                    f"SELECT * FROM memory_claims WHERE id IN ({placeholders})", claim_ids,
                )}
            turn_rows = {}
            if turn_ids:
                placeholders = ",".join("?" for _ in turn_ids)
                turn_rows = {row["id"]: row for row in db.execute(
                    f"""SELECT t.*,c.title conversation_title FROM turns t
                        JOIN conversations c ON c.id=t.conversation_id
                        WHERE t.id IN ({placeholders})""", turn_ids,
                )}

        core = {
            "claim_id", "turn_id", "origin_class", "source_id", "source_table",
            "link_timestamp", "message_id", "tool_event_id", "consumer",
            "compiler_stage", "source_path", "sort_id",
        }
        projected = []
        for row in visible:
            if row["claim_id"] not in claim_rows or row["turn_id"] not in turn_rows:
                continue
            details = {
                key: value for key, value in dict(row).items()
                if key not in core and value is not None
            }
            provenance = row["origin_class"]
            relationship_id = hashlib.sha256(row["sort_id"].encode()).hexdigest()[:24]
            item = {
                "id": f"claim-turn:{relationship_id}",
                "claim_id": f"claim:{row['claim_id']}",
                "turn_id": f"turn:{row['turn_id']}",
                "claim": self._claim_summary(claim_rows[row["claim_id"]]),
                "turn": self._turn_summary(turn_rows[row["turn_id"]]),
                "origin_class": provenance,
                "origin_label": MEMORY_TURN_ORIGIN_LABELS[provenance],
                "source": {
                    "persistent_source_id": _public_text(row["source_id"]),
                    "source_table": row["source_table"],
                    "source_path": row["source_path"],
                    "timestamp": row["link_timestamp"],
                    "message_id": f"message:{row['message_id']}" if row["message_id"] else None,
                    "tool_event_id": f"tool-event:{row['tool_event_id']}" if row["tool_event_id"] else None,
                    "details": _public_json(details, budget=2 * 1024),
                },
                "consumer": row["consumer"], "compiler_stage": row["compiler_stage"],
                "actual_use_proven": False,
                "interpretation": MEMORY_TURN_INTERPRETATIONS[provenance],
            }
            projected.append((row, item))

        result = {
            f"{target_kind}_id": f"{target_kind}:{target_id}",
            "filters": {"origin_class": origin_class or None, "consumer": consumer or None},
            "semantics": {
                "relationship": "persisted_participation",
                "actual_use_proven": False,
                "notice": "Bei diesem Turn beteiligt ist nicht gleich von EVE tatsächlich verwendet.",
                "legacy_turn_memory_retrievals_included": False,
            },
            "items": [],
            "page": {"limit": limit, "has_more": False, "next_cursor": None},
        }
        returned_rows = []
        response_budget = MEMORY_EXPLORER_JSON_BUDGET - 4096
        for row, item in projected:
            result["items"].append(item)
            if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > response_budget:
                result["items"].pop()
                break
            returned_rows.append(row)
        has_more = bool(returned_rows) and len(returned_rows) < len(ordered)
        if has_more:
            last = returned_rows[-1]
            result["page"]["next_cursor"] = _encode_cursor(
                last["link_timestamp"], last["sort_id"], binding,
            )
        result["page"]["has_more"] = has_more
        return result

    @staticmethod
    def _runtime_event_item(event: dict) -> dict:
        def namespaced(prefix, value):
            return f"{prefix}:{value}" if value else None

        write_delay_ms = None
        try:
            occurred = datetime.fromisoformat(str(event["occurred_at"]).replace("Z", "+00:00"))
            recorded = datetime.fromisoformat(str(event["recorded_at"]).replace("Z", "+00:00"))
            write_delay_ms = max(0, round((recorded - occurred).total_seconds() * 1000))
        except (KeyError, TypeError, ValueError):
            pass
        item = {
            "event_id": f"runtime-event:{event['id']}",
            "runtime_event_id": event["id"],
            "event_source": "runtime",
            "event_kind": event["event_kind"],
            "category": RUNTIME_EVENT_CATEGORY_BY_KIND[event["event_kind"]],
            "source_table": "memory_runtime_events",
            "source_id": event["id"],
            "timestamp": event["occurred_at"],
            "recorded_at": event["recorded_at"],
            "write_delay_ms": write_delay_ms,
            "fidelity": "direct_event",
            "trace_id": event.get("trace_id"),
            "operation_id": event.get("operation_id"),
            "parent_event_id": namespaced("runtime-event", event.get("parent_event_id")),
            "turn_id": namespaced("turn", event.get("turn_id")),
            "planner_round_id": event.get("planner_round_id"),
            "plan_id": event.get("plan_id"),
            "llm_call_id": event.get("llm_call_id"),
            "attempt_id": event.get("attempt_id"),
            "attempt_no": event.get("attempt_no"),
            "consumer": event.get("consumer"),
            "action_id": event.get("action_id"),
            "action_index": event.get("action_index"),
            "tool_event_id": namespaced("tool-event", event.get("tool_event_id")),
            "compiler_evaluation_id": event.get("compiler_evaluation_id"),
            "claim_ids": [namespaced("claim", event.get("claim_id"))] if event.get("claim_id") else [],
            "relation_id": namespaced("memory-relation", event.get("relation_id")),
            "learning_decision_id": event.get("learning_decision_id"),
            "producer": event.get("producer"),
            "proof_level": event.get("proof_level"),
            "event_status": event.get("event_status"),
            "outcome_status": event.get("outcome_status"),
            "verification_status": event.get("verification_status"),
            "provider": event.get("provider"),
            "target_resource_id": _public_text(event.get("target_resource_id")) if event.get("target_resource_id") else None,
            "state_before": _public_json(event.get("state_before"), budget=2048),
            "state_after": _public_json(event.get("state_after"), budget=2048),
            "reason_code": _public_text(event.get("reason_code")) if event.get("reason_code") else None,
            "context_block_id": event.get("context_block_id"),
            "context_manifest_digest": event.get("context_manifest_digest"),
            "ordinal": event.get("ordinal"),
            "details": _public_json(event.get("details", {}), budget=8 * 1024),
        }
        return item

    @staticmethod
    def _runtime_identifier(value, prefix, label):
        value = str(value or "").removeprefix(prefix + ":").strip()
        if len(value) > 512 or "/" in value or any(ord(character) < 32 for character in value):
            raise ValueError(f"Ungültige {label}")
        return value

    def runtime_events(self, *, timestamp_from="", timestamp_to="", trace_id="", turn_id="",
                       claim_id="", relation_id="", event_kind="", category="", proof_level="",
                       event_status="", consumer="", planner_round_id="", llm_call_id="",
                       attempt_id="", operation_id="", plan_id="", action_id="", tool_event_id="",
                       cursor="", sort="asc", limit=30) -> dict:
        limit = self._validate_limit(limit)
        category = self._validate_filter(category, set(RUNTIME_EVENT_CATEGORIES), "Kategorie")
        event_kind = self._validate_filter(event_kind, set(RUNTIME_EVENT_KINDS), "Runtime-Ereignistyp")
        proof_level = self._validate_filter(proof_level, set(RUNTIME_PROOF_LEVELS), "Proof-Level")
        event_status = self._validate_filter(event_status, set(RUNTIME_EVENT_STATUSES), "Eventstatus")
        sort = self._validate_filter(sort, {"asc", "desc"}, "Sortierung") or "asc"
        timestamp_from = self._validate_event_timestamp(timestamp_from, "Startzeitpunkt")
        timestamp_to = self._validate_event_timestamp(timestamp_to, "Endzeitpunkt")
        identifiers = {
            "trace_id": (trace_id, "trace", "Trace-ID"),
            "turn_id": (turn_id, "turn", "Turn-ID"),
            "claim_id": (claim_id, "claim", "Claim-ID"),
            "relation_id": (relation_id, "memory-relation", "Relations-ID"),
            "planner_round_id": (planner_round_id, "tool-round", "Tool-Runden-ID"),
            "llm_call_id": (llm_call_id, "llm-call", "LLM-Call-ID"),
            "attempt_id": (attempt_id, "attempt", "Attempt-ID"),
            "operation_id": (operation_id, "operation", "Operations-ID"),
            "plan_id": (plan_id, "plan", "Plan-ID"),
            "action_id": (action_id, "action", "Action-ID"),
            "tool_event_id": (tool_event_id, "tool-event", "Tool-Event-ID"),
        }
        filters = {}
        for key, (value, prefix, label) in identifiers.items():
            cleaned = self._runtime_identifier(value, prefix, label)
            if cleaned:
                filters[key] = cleaned
        if consumer:
            filters["consumer"] = self._runtime_identifier(consumer, "consumer", "Consumer")
        if event_kind:
            filters["event_kind"] = event_kind
        if proof_level:
            filters["proof_level"] = proof_level
        if event_status:
            filters["event_status"] = event_status
        event_kinds = RUNTIME_EVENT_CATEGORIES[category] if category and not event_kind else ()
        result = MemoryRuntimeEventReader(self.database_path).events(
            limit=limit, cursor=cursor or None, timestamp_from=timestamp_from,
            timestamp_to=timestamp_to, order=sort, event_kinds=event_kinds, **filters,
        )
        result["items"] = [self._runtime_event_item(item) for item in result["items"]]
        result["filters"] = {
            "from": timestamp_from or None, "to": timestamp_to or None,
            "category": category or None, "sort": sort,
            **{key: value for key, value in filters.items()},
        }
        result["semantics"] = {
            "event_source": "runtime", "source_table": "memory_runtime_events",
            "order": f"occurred_at_{sort}_then_event_id",
            "persisted_events_only": True, "inferred_events": False,
            "response_budget_bytes": 64 * 1024,
        }
        return result

    def runtime_event(self, event_id: str) -> dict:
        event_id = self._runtime_identifier(event_id, "runtime-event", "Runtime-Event-ID")
        event = MemoryRuntimeEventReader(self.database_path).event(event_id)
        if event is None:
            raise KeyError("Runtime-Ereignis wurde nicht gefunden")
        item = self._runtime_event_item(event)
        references = {
            "claim_id": (event.get("claim_id"), "memory_claims", "id"),
            "relation_id": (event.get("relation_id"), "memory_relations", "id"),
            "turn_id": (event.get("turn_id"), "turns", "id"),
            "tool_event_id": (event.get("tool_event_id"), "conversation_tool_events", "id"),
        }
        with closing(self._connect()) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            targets = {}
            for name, (value, table, column) in references.items():
                if not value:
                    continue
                targets[name] = {
                    "id": value,
                    "persisted_target_exists": table in tables and db.execute(
                        f"SELECT 1 FROM {table} WHERE {column}=? LIMIT 1", (value,),
                    ).fetchone() is not None,
                }
            for name in ("trace_id", "planner_round_id", "llm_call_id", "attempt_id",
                         "operation_id", "plan_id", "action_id"):
                value = event.get(name)
                if value:
                    targets[name] = {
                        "id": value,
                        "persisted_target_exists": db.execute(
                            f"SELECT 1 FROM memory_runtime_events WHERE {name}=? LIMIT 1", (value,),
                        ).fetchone() is not None,
                        "target_kind": "runtime_event_chain",
                    }
        item["causal_targets"] = targets
        return item

    def _runtime_activity_counts(self, claim_id: str) -> dict:
        expressions = {
            "retrieval": ("claim_retrieved", "COALESCE(compiler_evaluation_id,operation_id,id)"),
            "consumer_return": ("claim_returned_to_consumer", "COALESCE(compiler_evaluation_id,'') || ':' || COALESCE(consumer,'')"),
            "prompt_assembly": ("claim_added_to_prompt_context", "COALESCE(llm_call_id,'') || ':' || COALESCE(context_block_id,'')"),
            "client_handoff": ("claim_received_by_llm_client", "COALESCE(attempt_id,llm_call_id,id) || ':' || COALESCE(context_block_id,'')"),
            "transport_serialization": ("claim_serialized_for_transport", "COALESCE(attempt_id,llm_call_id,id) || ':' || COALESCE(context_block_id,'')"),
            "plan_binding": ("claim_bound_to_plan", "COALESCE(plan_id,id)"),
            "action_binding": ("claim_bound_to_action", "COALESCE(action_id,id)"),
            "dispatch": ("action_dispatch_attempted_with_claim", "COALESCE(attempt_id,action_id,id)"),
            "successful_action": ("action_completed_with_claim", "COALESCE(action_id,id)"),
        }
        columns, parameters = [], []
        for name, (kind, identity) in expressions.items():
            condition = "event_kind=?"
            if name == "successful_action":
                condition += " AND outcome_status='success'"
            columns.append(f"COUNT(DISTINCT CASE WHEN {condition} THEN {identity} END) AS {name}")
            parameters.append(kind)
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT " + ",".join(columns) + " FROM memory_runtime_events WHERE claim_id=?",
                (*parameters, claim_id),
            ).fetchone()
            relation_count = db.execute(
                """SELECT COUNT(DISTINCT e.id) FROM memory_runtime_events e
                   JOIN memory_relations r ON r.id=e.relation_id
                   WHERE e.event_kind='relation_traversed_for_retrieval'
                     AND (r.from_claim_id=? OR r.to_claim_id=?)""",
                (claim_id, claim_id),
            ).fetchone()[0]
        counts = {key: int(row[key]) for key in expressions}
        counts["relation_traversal"] = int(relation_count)
        return counts

    def claim_runtime(self, claim_id: str, **filters) -> dict:
        claim_id = self._runtime_identifier(claim_id, "claim", "Claim-ID")
        with closing(self._connect()) as db:
            if db.execute("SELECT 1 FROM memory_claims WHERE id=?", (claim_id,)).fetchone() is None:
                raise KeyError("Claim wurde nicht gefunden")
        result = self.runtime_events(claim_id=claim_id, **filters)
        result["claim_id"] = f"claim:{claim_id}"
        result["activity_counts"] = self._runtime_activity_counts(claim_id)
        result["semantics"]["counts"] = "deduplicated_per_category_by_persisted_technical_identity"
        result["semantics"]["universal_used_count"] = False
        return result

    def turn_runtime(self, turn_id: str, **filters) -> dict:
        turn_id = self._runtime_identifier(turn_id, "turn", "Turn-ID")
        result = self.runtime_events(turn_id=turn_id, **filters)
        group_fields = (
            "planner_round_id", "llm_call_id", "attempt_id", "operation_id", "plan_id", "action_id",
        )
        result["turn_id"] = f"turn:{turn_id}"
        result["causal_groups"] = {
            field: list(dict.fromkeys(item[field] for item in result["items"] if item.get(field)))
            for field in group_fields
        }
        result["semantics"]["groups_cover"] = "loaded_event_window_only"
        return result

    def turn_runtime_live(self, turn_id: str, *, cursor="", tail=False, limit=50) -> dict:
        turn_id = self._runtime_identifier(turn_id, "turn", "Turn-ID")
        tail = str(tail or "").casefold() in {"1", "true", "yes"}
        limit = self._validate_limit(limit)
        result = MemoryRuntimeEventReader(self.database_path).ingested_events(
            turn_id, cursor=cursor or None, limit=limit, tail=tail,
        )
        result["items"] = [self._runtime_event_item(item) for item in result["items"]]
        result["turn_id"] = f"turn:{turn_id}"
        result["semantics"] = {
            "event_source": "runtime", "persisted_events_only": True,
            "cursor_basis": "append_only_rowid", "late_writes_visible": True,
            "inferred_events": False,
        }
        return result

    def claim_turns(self, claim_id: str, *, origin_class="", consumer="",
                    cursor="", limit=20) -> dict:
        return self._turn_links(
            claim_id=claim_id, origin_class=origin_class, consumer=consumer,
            cursor=cursor, limit=limit,
        )

    def turn_memory(self, turn_id: str, *, origin_class="", consumer="",
                    cursor="", limit=20) -> dict:
        return self._turn_links(
            turn_id=turn_id, origin_class=origin_class, consumer=consumer,
            cursor=cursor, limit=limit,
        )

    @staticmethod
    def _validate_event_timestamp(value, label: str) -> str:
        value = str(value or "").strip()
        if not value:
            return ""
        if len(value) > 64 or any(ord(character) < 32 for character in value):
            raise ValueError(f"Ungültiger {label}")
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            # Date-only values are intentionally accepted because the oldest
            # imported Memory-v2 rows use that persisted precision.
            from datetime import datetime
            datetime.fromisoformat(candidate)
        except ValueError:
            raise ValueError(f"Ungültiger {label}") from None
        return value

    @staticmethod
    def _event_item(row) -> dict:
        claim_ids = [f"claim:{value}" for value in (row["claim_id"], row["claim_id_2"]) if value]
        metadata = _public_json(_decode_json_object(row["metadata_json"]), budget=3 * 1024)
        source_id = row["source_id"]
        event_id = row["event_id"]
        if row["source_table"] == "memory_compiler_claim_audit":
            identity = "\x1f".join((
                str(row["evaluation_id"] or ""), str(row["claim_id"] or ""),
                str(row["compiler_stage"] or ""), str(row["audit_reason"] or ""),
            ))
            suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
            source_id = f"{row['evaluation_id']}:{row['claim_id']}:{row['compiler_stage']}:{suffix}"
            event_id = f"memory-compiler-audit:{source_id}"
        item = {
            "event_id": event_id,
            "event_kind": row["event_kind"],
            "event_source": "historical",
            "category": HISTORICAL_EVENT_CATEGORY_BY_KIND[row["event_kind"]],
            "source_table": row["source_table"],
            "source_id": source_id,
            "claim_ids": list(dict.fromkeys(claim_ids)),
            "timestamp": row["timestamp"],
            "fidelity": row["fidelity"],
            "turn_id": f"turn:{row['turn_id']}" if row["turn_id"] else None,
            "message_id": f"message:{row['message_id']}" if row["message_id"] else None,
            "tool_event_id": f"tool-event:{row['tool_event_id']}" if row["tool_event_id"] else None,
            "consumer": row["consumer"],
            "compiler_stage": row["compiler_stage"],
            "relation_id": f"memory-relation:{row['relation_id']}" if row["relation_id"] else None,
            "evidence_id": f"evidence:{row['evidence_id']}" if row["evidence_id"] else None,
            "metadata": metadata,
        }
        return item

    def events(self, *, timestamp_from="", timestamp_to="", claim_id="", turn_id="",
               event_kind="", category="", fidelity="", consumer="", compiler_stage="", scope="",
               cursor="", limit=30) -> dict:
        timestamp_from = self._validate_event_timestamp(timestamp_from, "Startzeitpunkt")
        timestamp_to = self._validate_event_timestamp(timestamp_to, "Endzeitpunkt")
        if timestamp_from and timestamp_to and timestamp_from > timestamp_to:
            raise ValueError("Startzeitpunkt liegt nach dem Endzeitpunkt")
        claim_id = str(claim_id or "").removeprefix("claim:").strip()
        turn_id = str(turn_id or "").removeprefix("turn:").strip()
        for value, label in ((claim_id, "Claim-ID"), (turn_id, "Turn-ID")):
            if len(value) > 512 or "/" in value or any(ord(character) < 32 for character in value):
                raise ValueError(f"Ungültige {label}")
        event_kind = self._validate_filter(event_kind, MEMORY_EVENT_KINDS, "Ereignistyp")
        category = self._validate_filter(category, set(HISTORICAL_EVENT_CATEGORIES), "Kategorie")
        fidelity = self._validate_filter(fidelity, MEMORY_EVENT_FIDELITIES, "Fidelity-Klasse")
        consumer = self._validate_filter(consumer, MEMORY_EVENT_CONSUMERS, "Consumer")
        compiler_stage = self._validate_filter(compiler_stage, MEMORY_EVENT_STAGES, "Compiler-Stufe")
        scope = self._validate_scope(scope)
        limit = self._validate_limit(limit)
        filters = {
            "from": timestamp_from, "to": timestamp_to, "claim_id": claim_id,
            "turn_id": turn_id, "event_kind": event_kind, "fidelity": fidelity,
            "category": category, "consumer": consumer, "compiler_stage": compiler_stage, "scope": scope,
        }
        binding = self._binding("memory_events", filters)
        cursor_values = _decode_cursor(cursor, binding) if cursor else None
        source_rows = []

        with closing(self._connect()) as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )}

            def add(required_tables, sql, params=()):
                if not set(required_tables) <= tables:
                    return
                where, values = [], list(params)
                if timestamp_from:
                    where.append("timestamp>=?"); values.append(timestamp_from)
                if timestamp_to:
                    where.append("timestamp<=?"); values.append(timestamp_to)
                if claim_id:
                    where.append("(claim_id=? OR claim_id_2=?)"); values.extend((claim_id, claim_id))
                if turn_id:
                    where.append("turn_id=?"); values.append(turn_id)
                if event_kind:
                    where.append("event_kind=?"); values.append(event_kind)
                elif category:
                    category_kinds = sorted(HISTORICAL_EVENT_CATEGORIES[category])
                    where.append("event_kind IN (" + ",".join("?" for _ in category_kinds) + ")")
                    values.extend(category_kinds)
                if fidelity:
                    where.append("fidelity=?"); values.append(fidelity)
                if consumer:
                    where.append("consumer=?"); values.append(consumer)
                if compiler_stage:
                    where.append("compiler_stage=?"); values.append(compiler_stage)
                if scope:
                    where.append("(scope=? OR scope_2=?)"); values.extend((scope, scope))
                if cursor_values:
                    where.append("(timestamp<? OR (timestamp=? AND sort_id<?))")
                    values.extend((cursor_values[0], cursor_values[0], cursor_values[1]))
                outer = " AND ".join(where) if where else "1=1"
                source_rows.extend(db.execute(
                    f"SELECT * FROM ({sql}) event_rows WHERE {outer} "
                    "ORDER BY timestamp DESC,sort_id DESC LIMIT ?",
                    (*values, limit + 1),
                ).fetchall())

            # Standard column order shared by every bounded source query:
            # identity, classification, two possible claims, provenance and metadata.
            add(("memory_claims",), """SELECT
                'claim-created:' || c.id event_id,'claim_created' event_kind,
                'memory_claims' source_table,c.id source_id,c.id claim_id,NULL claim_id_2,
                c.created_at timestamp,'state_timestamp' fidelity,NULL turn_id,NULL message_id,
                NULL tool_event_id,NULL consumer,NULL compiler_stage,NULL relation_id,NULL evidence_id,
                c.scope scope,NULL scope_2,NULL evaluation_id,NULL audit_reason,
                'c|' || printf('%016x',c.rowid) sort_id,
                json_object('claim_kind',c.claim_kind,'lifecycle',c.lifecycle,
                    'verification_policy',c.verification_policy,
                    'timestamp_basis','memory_claims.created_at') metadata_json
                FROM memory_claims c""")

            add(("memory_evidence", "memory_claims"), """SELECT
                CASE WHEN e.evidence_type='reuse_result' THEN 'semantic-reuse-result:'
                     ELSE 'evidence-created:' END || e.id event_id,
                CASE WHEN e.evidence_type='reuse_result' THEN 'semantic_reuse_result'
                     ELSE 'evidence_created' END event_kind,
                'memory_evidence' source_table,e.id source_id,e.claim_id,NULL claim_id_2,
                e.created_at timestamp,'direct_event' fidelity,e.source_turn_id turn_id,
                e.source_message_id message_id,e.tool_event_id tool_event_id,NULL consumer,
                NULL compiler_stage,NULL relation_id,e.id evidence_id,c.scope scope,NULL scope_2,
                NULL evaluation_id,NULL audit_reason,'e|' || printf('%016x',e.rowid) sort_id,
                json_object('evidence_type',e.evidence_type,'stance',e.stance,
                    'source_ref',e.source_ref,'excerpt',e.excerpt,'observed_at',e.observed_at,
                    'payload',json(e.payload_json),'timestamp_basis','memory_evidence.created_at',
                    'actual_use_proven',0) metadata_json
                FROM memory_evidence e JOIN memory_claims c ON c.id=e.claim_id""")

            add(("memory_observations", "memory_evidence", "memory_claims"), """SELECT DISTINCT
                'observation-recorded:' || o.id || CASE WHEN e.claim_id IS NULL THEN '' ELSE ':claim:' || e.claim_id END event_id,
                'observation_recorded' event_kind,'memory_observations' source_table,o.id source_id,
                e.claim_id claim_id,NULL claim_id_2,o.created_at timestamp,'direct_event' fidelity,
                o.turn_id turn_id,o.message_id message_id,o.tool_event_id tool_event_id,NULL consumer,
                NULL compiler_stage,NULL relation_id,NULL evidence_id,COALESCE(c.scope,o.scope) scope,NULL scope_2,
                NULL evaluation_id,NULL audit_reason,
                'o|' || printf('%016x',o.rowid) || '|' || COALESCE(e.claim_id,'') sort_id,
                json_object('source_role',o.source_role,'source_type',o.source_type,
                    'external_ref',o.external_ref,'excerpt',o.excerpt,'observed_at',o.observed_at,
                    'observation_scope',o.scope,'timestamp_basis','memory_observations.created_at') metadata_json
                FROM memory_observations o LEFT JOIN memory_evidence e ON e.observation_id=o.id
                LEFT JOIN memory_claims c ON c.id=e.claim_id""")

            add(("memory_relations", "memory_claims"), """SELECT
                'relation-stored:' || r.id event_id,'relation_stored' event_kind,
                'memory_relations' source_table,r.id source_id,r.from_claim_id claim_id,
                r.to_claim_id claim_id_2,r.created_at timestamp,'direct_event' fidelity,
                NULL turn_id,NULL message_id,NULL tool_event_id,NULL consumer,NULL compiler_stage,
                r.id relation_id,r.evidence_id evidence_id,f.scope scope,t.scope scope_2,
                NULL evaluation_id,NULL audit_reason,'r|' || printf('%016x',r.rowid) sort_id,
                json_object('relation_type',r.relation_type,
                    'timestamp_basis','memory_relations.created_at') metadata_json
                FROM memory_relations r JOIN memory_claims f ON f.id=r.from_claim_id
                JOIN memory_claims t ON t.id=r.to_claim_id""")

            add(("memory_learning_decisions", "memory_learning_decision_claims", "memory_claims", "memory_observations"), """SELECT
                'learning-decision:' || d.id || CASE WHEN dc.claim_id IS NULL THEN '' ELSE ':claim:' || dc.claim_id END event_id,
                'learning_decision' event_kind,'memory_learning_decisions' source_table,d.id source_id,
                dc.claim_id claim_id,NULL claim_id_2,d.created_at timestamp,'direct_event' fidelity,
                o.turn_id turn_id,o.message_id message_id,o.tool_event_id tool_event_id,NULL consumer,
                NULL compiler_stage,NULL relation_id,NULL evidence_id,c.scope scope,NULL scope_2,
                NULL evaluation_id,NULL audit_reason,
                'd|' || printf('%016x',d.rowid) || '|' || COALESCE(dc.claim_id,'') sort_id,
                json_object('decision_type',d.decision_type,'method',d.method,
                    'policy_version',d.policy_version,'model_version',d.model_version,
                    'rationale',d.rationale,'uncertainty',d.uncertainty,
                    'observation_id',d.observation_id,
                    'timestamp_basis','memory_learning_decisions.created_at') metadata_json
                FROM memory_learning_decisions d
                LEFT JOIN memory_learning_decision_claims dc ON dc.decision_id=d.id
                LEFT JOIN memory_claims c ON c.id=dc.claim_id
                LEFT JOIN memory_observations o ON o.id=d.observation_id""")

            if "memory_learning_jobs" in tables:
                for state, column, suffix in (
                    ("learning_job_accepted", "accepted_at", "accepted"),
                    ("learning_job_started", "started_at", "started"),
                    ("learning_job_completed", "completed_at", "completed"),
                    ("learning_job_updated", "updated_at", "updated"),
                ):
                    add(("memory_learning_jobs", "memory_learning_decision_claims", "memory_claims"), f"""SELECT
                        'learning-job:' || j.turn_id || ':{suffix}' || CASE WHEN dc.claim_id IS NULL THEN '' ELSE ':claim:' || dc.claim_id END event_id,
                        '{state}' event_kind,'memory_learning_jobs' source_table,j.turn_id source_id,
                        dc.claim_id claim_id,NULL claim_id_2,j.{column} timestamp,'state_timestamp' fidelity,
                        j.turn_id turn_id,NULL message_id,NULL tool_event_id,NULL consumer,
                        NULL compiler_stage,NULL relation_id,NULL evidence_id,c.scope scope,NULL scope_2,
                        NULL evaluation_id,NULL audit_reason,
                        'j|{suffix}|' || printf('%016x',j.rowid) || '|' || COALESCE(dc.claim_id,'') sort_id,
                        json_object('job_status',j.status,'state','{suffix}','attempt_count',j.attempt_count,
                            'error_class',j.error_class,'decision_id',j.decision_id,
                            'timestamp_basis','memory_learning_jobs.{column}') metadata_json
                        FROM memory_learning_jobs j
                        LEFT JOIN memory_learning_decision_claims dc ON dc.decision_id=j.decision_id
                        LEFT JOIN memory_claims c ON c.id=dc.claim_id WHERE j.{column} IS NOT NULL""")

            add(("memory_compiler_evaluations",), """SELECT
                'compiler-evaluation:' || v.id event_id,'compiler_evaluation' event_kind,
                'memory_compiler_evaluations' source_table,v.id source_id,NULL claim_id,NULL claim_id_2,
                v.created_at timestamp,'direct_event' fidelity,v.turn_id turn_id,NULL message_id,
                NULL tool_event_id,v.consumer consumer,NULL compiler_stage,NULL relation_id,NULL evidence_id,
                NULL scope,NULL scope_2,v.id evaluation_id,NULL audit_reason,
                'v|' || printf('%016x',v.rowid) sort_id,
                json_object('status',v.status,'compiler_version',v.compiler_version,
                    'retrieval_version',v.retrieval_version,'eligibility_version',v.eligibility_version,
                    'projection_version',v.projection_version,'budget_version',v.budget_version,
                    'token_budget',v.token_budget,'token_count',v.token_count,
                    'candidate_count',v.candidate_count,'eligible_count',v.eligible_count,
                    'presented_count',v.presented_count,
                    'timestamp_basis','memory_compiler_evaluations.created_at') metadata_json
                FROM memory_compiler_evaluations v""")

            audit_sql = """SELECT
                'compiler-audit-pending-hash' event_id,'compiler_' || a.stage event_kind,
                'memory_compiler_claim_audit' source_table,NULL source_id,a.claim_id claim_id,NULL claim_id_2,
                v.created_at timestamp,'derived_link' fidelity,v.turn_id turn_id,NULL message_id,
                NULL tool_event_id,v.consumer consumer,a.stage compiler_stage,NULL relation_id,NULL evidence_id,
                c.scope scope,NULL scope_2,v.id evaluation_id,a.reason audit_reason,
                'a|' || printf('%016x',a.rowid) sort_id,
                json_object('evaluation_id',v.id,'evaluation_status',v.status,
                    'method',a.method,'reason',a.reason,'requirement_class',a.requirement_class,
                    'token_cost',a.token_cost,'rank_score',a.rank_score,
                    'timestamp_basis','memory_compiler_evaluations.created_at',
                    'actual_use_proven',0) metadata_json
                FROM memory_compiler_claim_audit a
                JOIN memory_compiler_evaluations v ON v.id=a.evaluation_id
                JOIN memory_claims c ON c.id=a.claim_id"""
            audit_tables = {"memory_compiler_claim_audit", "memory_compiler_evaluations", "memory_claims"}
            if claim_id:
                # The existing (claim_id, stage) index is the selective path for
                # a focused claim, including old events.
                add(audit_tables, audit_sql)
            elif audit_tables <= tables and fidelity in {"", "derived_link"}:
                audit_kinds = {f"compiler_{stage}" for stage in MEMORY_EVENT_STAGES}
                requested_stage = compiler_stage
                if event_kind:
                    if event_kind not in audit_kinds:
                        requested_stage = "__skip__"
                    else:
                        kind_stage = event_kind.removeprefix("compiler_")
                        requested_stage = kind_stage if not requested_stage else requested_stage
                        if compiler_stage and compiler_stage != kind_stage:
                            requested_stage = "__skip__"
                # Walk bounded batches of evaluation timestamps. The audit PK
                # begins with evaluation_id, so this avoids a global scan and
                # still reaches older matches for sparse stage/scope filters.
                before_timestamp = None
                audit_rows = []
                while requested_stage != "__skip__" and len(audit_rows) <= limit:
                    evaluation_where, evaluation_values = [], []
                    if timestamp_from:
                        evaluation_where.append("v.created_at>=?"); evaluation_values.append(timestamp_from)
                    if timestamp_to:
                        evaluation_where.append("v.created_at<=?"); evaluation_values.append(timestamp_to)
                    if turn_id:
                        evaluation_where.append("v.turn_id=?"); evaluation_values.append(turn_id)
                    if consumer:
                        evaluation_where.append("v.consumer=?"); evaluation_values.append(consumer)
                    if cursor_values:
                        evaluation_where.append("v.created_at<=?"); evaluation_values.append(cursor_values[0])
                    if before_timestamp:
                        evaluation_where.append("v.created_at<?"); evaluation_values.append(before_timestamp)
                    evaluation_clause = " AND ".join(evaluation_where) if evaluation_where else "1=1"
                    timestamps = [row[0] for row in db.execute(
                        f"""SELECT DISTINCT v.created_at FROM memory_compiler_evaluations v
                            WHERE {evaluation_clause} ORDER BY v.created_at DESC LIMIT 128""",
                        evaluation_values,
                    ).fetchall()]
                    if not timestamps:
                        break
                    placeholders = ",".join("?" for _ in timestamps)
                    audit_where, audit_values = [f"v.created_at IN ({placeholders})"], list(timestamps)
                    if turn_id:
                        audit_where.append("v.turn_id=?"); audit_values.append(turn_id)
                    if consumer:
                        audit_where.append("v.consumer=?"); audit_values.append(consumer)
                    if requested_stage:
                        audit_where.append("a.stage=?"); audit_values.append(requested_stage)
                    if scope:
                        audit_where.append("c.scope=?"); audit_values.append(scope)
                    if cursor_values:
                        audit_where.append(
                            "(v.created_at<? OR (v.created_at=? AND "
                            "('a|' || printf('%016x',a.rowid))<?))"
                        )
                        audit_values.extend((cursor_values[0], cursor_values[0], cursor_values[1]))
                    rows = db.execute(
                        f"""SELECT * FROM ({audit_sql} WHERE {' AND '.join(audit_where)}) event_rows
                            ORDER BY timestamp DESC,sort_id DESC LIMIT ?""",
                        (*audit_values, limit + 1 - len(audit_rows)),
                    ).fetchall()
                    audit_rows.extend(rows)
                    before_timestamp = timestamps[-1]
                    if len(audit_rows) > limit or len(timestamps) < 128:
                        break
                source_rows.extend(audit_rows)

            add(("memory_compiler_usage", "memory_claims"), """SELECT
                'memory-compiler-usage:' || u.turn_id || ':' || u.consumer || ':' || u.claim_id || ':presented' event_id,
                'usage_presented' event_kind,'memory_compiler_usage' source_table,
                u.turn_id || ':' || u.consumer || ':' || u.claim_id || ':presented' source_id,
                u.claim_id claim_id,NULL claim_id_2,u.created_at timestamp,'direct_event' fidelity,
                u.turn_id turn_id,NULL message_id,NULL tool_event_id,u.consumer consumer,
                'presented' compiler_stage,NULL relation_id,NULL evidence_id,c.scope scope,NULL scope_2,
                NULL evaluation_id,NULL audit_reason,'u|' || printf('%016x',u.rowid) sort_id,
                json_object('usage','presented','actual_prompt_inclusion_proven',0,
                    'actual_use_proven',0,'timestamp_basis','memory_compiler_usage.created_at') metadata_json
                FROM memory_compiler_usage u JOIN memory_claims c ON c.id=u.claim_id
                WHERE u.usage='presented'""")

        ordered = sorted(
            source_rows, key=lambda row: (row["timestamp"], row["sort_id"]), reverse=True,
        )
        result = {
            "items": [], "filters": {key: value or None for key, value in filters.items()},
            "semantics": {
                "order": "timestamp_desc_then_persistent_source",
                "actual_use_proven": False,
                "usage_presented_is_prompt_proof": False,
                "audit_timestamp_basis": "memory_compiler_evaluations.created_at",
                "fidelity": MEMORY_EVENT_FIDELITY_TEXT,
            },
            "page": {"limit": limit, "has_more": False, "next_cursor": None},
        }
        returned_rows = []
        response_budget = MEMORY_EXPLORER_JSON_BUDGET - 4096
        for row in ordered[:limit + 1]:
            if len(result["items"]) >= limit:
                break
            result["items"].append(self._event_item(row))
            if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > response_budget:
                result["items"].pop()
                break
            returned_rows.append(row)
        has_more = bool(returned_rows) and len(returned_rows) < len(ordered)
        if has_more:
            last = returned_rows[-1]
            result["page"]["next_cursor"] = _encode_cursor(
                last["timestamp"], last["sort_id"], binding,
            )
        result["page"]["has_more"] = has_more
        return result
