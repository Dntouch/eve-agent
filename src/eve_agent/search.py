from __future__ import annotations

import json
import re
from datetime import datetime

from .memory import cosine_similarity, lexical_tokens, lexical_vector


def fts_query(text: str) -> str:
    """Convert untrusted natural text into a safe prefix-oriented FTS query."""
    words = re.findall(r"[^\W_]+", str(text).casefold(), flags=re.UNICODE)
    unique = list(dict.fromkeys(word for word in words if word))
    if not unique:
        raise ValueError("Suchanfrage enthält keine durchsuchbaren Begriffe")
    return " OR ".join(f'"{word.replace(chr(34), chr(34) * 2)}"*' for word in unique)


class PersistentSearch:
    """Domain-separated FTS5 search over conversations and durable knowledge."""

    def __init__(self, database, *, memory_runtime=None):
        self.database = database
        self.memory_runtime = memory_runtime
        self.last_knowledge_context_claims: list[dict] = []

    def conversations(self, query: str, *, limit: int | None = None) -> list[dict]:
        sql = """SELECT m.id AS message_id, m.conversation_id, c.title AS conversation_title,
                         m.role, m.created_at, m.content, bm25(conversation_messages_fts) AS rank
                  FROM conversation_messages_fts
                  JOIN messages m ON m.id=conversation_messages_fts.message_id
                  JOIN conversations c ON c.id=m.conversation_id
                  WHERE conversation_messages_fts MATCH ? AND c.status!='deleted'
                  ORDER BY rank, m.created_at DESC"""
        parameters = [fts_query(query)]
        if limit is not None:
            sql += " LIMIT ?"
            parameters.append(max(int(limit), 1))
        with self.database.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return [dict(row) for row in rows]

    def knowledge(self, query: str, *, limit: int | None = None,
                  telemetry_context: dict | None = None) -> list[dict]:
        if self.memory_runtime is None:
            raise RuntimeError("Memory-Runtime fehlt")
        hits = self.memory_runtime.retrieve(
            query, limit, telemetry_context=telemetry_context,
            query_kind="local_knowledge.search",
        )
        self.last_knowledge_context_claims = [
            {
                "claim_id": str(hit.memory_id),
                "compiler_evaluation_id": str(hit.compiler_evaluation_id),
            }
            for hit in hits
            if hit.memory_id and hit.compiler_evaluation_id
        ]
        return [{
            "memory_id": hit.memory_id, "category": "memory",
            "content": hit.text, "confidence": hit.score,
            "valid_from": None, "updated_at": None, "rank": -hit.score,
        } for hit in hits]

    def visual_assets(self, query: str, *, limit: int | None = None) -> list[dict]:
        """Search indexed image context only when the visual capability is selected."""
        query_vector, query_tokens = lexical_vector(query), lexical_tokens(query)
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT v.*, a.conversation_id, a.message_id, a.media_type,
                          c.title AS conversation_title
                   FROM visual_asset_index v
                   JOIN conversation_assets a ON a.id=v.asset_id
                   JOIN conversations c ON c.id=a.conversation_id
                   WHERE c.status!='deleted' ORDER BY v.created_at DESC"""
            ).fetchall()
        scored = []
        local_now = datetime.now().astimezone()
        for row in rows:
            item = dict(row)
            try:
                created = datetime.fromisoformat(item["created_at"]).astimezone()
            except ValueError:
                created = None
            try:
                vector = json.loads(bytes(item.pop("embedding")).decode())
            except (TypeError, ValueError, UnicodeDecodeError):
                vector = lexical_vector(item["description"])
            lexical = len(query_tokens & lexical_tokens(item["description"])) / max(1, len(query_tokens))
            semantic = max(0.0, cosine_similarity(query_vector, vector))
            recency = 0.0
            try:
                age_days = max(0.0, (local_now - datetime.fromisoformat(item["created_at"])).total_seconds() / 86400)
                recency = 0.03 / (1.0 + age_days)
            except ValueError:
                pass
            item["score"] = 0.58 * semantic + 0.42 * lexical + recency
            if item["score"] >= 0.08:
                scored.append(item)
        ranked = sorted(scored, key=lambda item: (item["score"], item["created_at"]), reverse=True)
        return ranked if limit is None else ranked[:max(int(limit), 1)]

    def search(self, domain: str, query: str, *, limit: int | None = None) -> list[dict]:
        normalized = str(domain).casefold()
        if normalized == "conversations":
            return self.conversations(query, limit=limit)
        if normalized == "knowledge":
            return self.knowledge(query, limit=limit)
        raise ValueError("Unbekannter Suchbereich")


class LocalSearchCapability:
    """Model-selected, read-only access to domain-specific local FTS stores."""

    def __init__(self, search: PersistentSearch, llm):
        self.search, self.llm = search, llm
        self.last_knowledge_results: list[dict] = []
        self.last_knowledge_context_claims: list[dict] = []

    @staticmethod
    def self_descriptions():
        from .runtime_self_knowledge import RuntimeSelfDescription
        return [
            RuntimeSelfDescription(
                "local_search.conversations", "local_search.conversations",
                "Ich kann frühere Unterhaltungen lokal durchsuchen.",
                "LocalSearchCapability", "search_conversations",
            ),
            RuntimeSelfDescription(
                "local_search.knowledge", "local_search.knowledge",
                "Ich kann dauerhaftes Wissen lokal durchsuchen.",
                "LocalSearchCapability", "search_knowledge",
            ),
            RuntimeSelfDescription(
                "local_search.visual_assets", "local_search.visual_assets",
                "Ich kann gespeicherte visuelle Inhalte lokal durchsuchen.",
                "LocalSearchCapability", "search_visual_assets",
            ),
        ]

    @staticmethod
    def minimal_contract() -> dict:
        return {
            "description": "Lokale, nur lesende Suche in Unterhaltungen, Wissen und visuellen Assets.",
            "operations": {
                "search_conversations": {
                    "effect": "read",
                    "purpose": (
                        "Frühere persistierte Unterhaltungen durchsuchen; liefert keinen aktuellen Zustand "
                        "eines anderen Providers."
                    ),
                    "parameters_schema": {
                        "type": "object", "additionalProperties": False,
                        "properties": {"query": {"type": "string", "minLength": 1},
                                       "limit": {"type": "integer", "minimum": 1}},
                        "required": ["query"],
                    },
                },
                "search_knowledge": {
                    "effect": "read",
                    "purpose": (
                        "Historisch gespeichertes Memory-Wissen zur Bedeutungs- oder Faktensuche lesen; "
                        "liefert keinen aktuellen Zustand providerverwalteter Daten."
                    ),
                    "parameters_schema": {
                        "type": "object", "additionalProperties": False,
                        "properties": {"query": {"type": "string", "minLength": 1},
                                       "limit": {"type": "integer", "minimum": 1}},
                        "required": ["query"],
                    },
                },
                "search_visual_assets": {
                    "effect": "read",
                    "purpose": "Persistierte visuelle Inhalte lokal suchen.",
                    "parameters_schema": {
                        "type": "object", "additionalProperties": False,
                        "properties": {"query": {"type": "string", "minLength": 1},
                                       "limit": {"type": "integer", "minimum": 1}},
                        "required": ["query"],
                    },
                },
            },
        }

    def execute_operation(self, operation: str, arguments: dict, *,
                          telemetry_context: dict | None = None) -> dict:
        self.last_knowledge_results = []
        self.last_knowledge_context_claims = []
        operation = str(operation)
        if not isinstance(arguments, dict):
            raise ValueError("Lokale Suchargumente müssen ein Objekt sein")
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("Lokale Suchanfrage fehlt")
        limit = arguments.get("limit")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
            raise ValueError("Lokales Suchlimit muss ganzzahlig sein")
        if limit is not None and limit < 1:
            raise ValueError("Lokales Suchlimit muss positiv sein")
        if operation == "search_conversations":
            results = self.search.conversations(query, limit=limit)
            scope = "persisted_conversations"
        elif operation == "search_knowledge":
            results = self.search.knowledge(
                query, limit=limit, telemetry_context=telemetry_context,
            )
            self.last_knowledge_results = list(results)
            self.last_knowledge_context_claims = list(
                self.search.last_knowledge_context_claims
            )
            scope = "durable_knowledge"
        elif operation == "search_visual_assets":
            raw = self.search.visual_assets(query, limit=limit)
            return {
                "kind": "visual", "operation": operation, "query": query,
                "matches": raw, "ambiguous": len(raw) > 1,
                "provenance": {"provider": "conversation_store", "scope": "persisted_visual_assets"},
            }
        else:
            raise ValueError("Unbekannte lokale Suchoperation")
        return {
            "kind": "local_search", "operation": operation, "query": query,
            "matches": results, "provenance": {"provider": "local_store", "scope": scope},
        }
