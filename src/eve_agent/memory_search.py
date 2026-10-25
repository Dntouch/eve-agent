"""Structured inventory and model-backed hybrid retrieval over active Memory claims."""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import urllib.request
from pathlib import Path
from contextlib import closing

from .backend_turns import TurnCancelled


def normalized(vector):
    if not isinstance(vector, list) or not vector:
        raise ValueError("Embedding ist leer oder ungültig")
    values = [float(v) for v in vector]
    norm = math.sqrt(sum(v * v for v in values))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("Embedding enthält ungültige Werte")
    return [v / norm for v in values]


class EmbeddingClient:
    def __init__(self, config, llm_config=None):
        self.model = str(config["model"])
        self.base_url = str(config["base_url"]).rstrip("/")
        self.api_key = str(config.get("api_key") or "local")
        self.timeout = int(config.get("timeout_seconds", 60))
        self.query_prefix = str(config.get("query_prefix", ""))
        self.document_prefix = str(config.get("document_prefix", ""))
        self.identity = json.dumps([self.base_url, self.model, self.query_prefix, self.document_prefix])

    def embed(self, texts, *, query=False):
        prefix = self.query_prefix if query else self.document_prefix
        request = urllib.request.Request(
            self.base_url + "/embeddings",
            data=json.dumps({"model": self.model, "input": [prefix + t for t in texts]}).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.api_key},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.load(response)["data"]
        data = sorted(data, key=lambda item: item["index"])
        if [item["index"] for item in data] != list(range(len(texts))):
            raise ValueError("Embedding-Antwort ist unvollständig")
        vectors = [normalized(item["embedding"]) for item in data]
        if len({len(v) for v in vectors}) > 1:
            raise ValueError("Embedding-Dimensionen sind inkonsistent")
        return vectors


class MemorySearch:
    def __init__(self, runtime, embedding_client=None):
        self.runtime = runtime
        self.client = embedding_client
        self._lock = threading.Lock()
        self.cache_path = Path(runtime.database.path).with_name("memory-embeddings.db")

    def _claims(self, *, provider=None, domain=None, area=None, availability=None):
        # Exact metadata filters have no dependency on names, language or synonyms.
        with self.runtime.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memory_claims WHERE lifecycle='active' AND valid_until IS NULL ORDER BY id"
            ).fetchall()
            source_rows = connection.execute("""
                SELECT DISTINCT e.claim_id,e.evidence_type,m.id,m.role,m.conversation_id,
                       m.created_at,m.metadata_json
                FROM memory_evidence e JOIN messages m ON m.id=e.source_message_id
                JOIN memory_claims c ON c.id=e.claim_id
                WHERE c.lifecycle='active' AND c.valid_until IS NULL AND e.stance='supports'
                ORDER BY e.claim_id,m.created_at,m.id,e.evidence_type
            """).fetchall()
        sources = {}
        for row in source_rows:
            metadata = json.loads(row["metadata_json"] or "{}")
            source = metadata.get("conversation_source")
            source = {
                key: source[key] for key in (
                    "transport", "server_url", "sender_id", "sender_name",
                    "room_id", "room_kind", "room_name", "message_id",
                ) if key in source
            } if isinstance(source, dict) else None
            sources.setdefault(row["claim_id"], []).append({
                "message_id": row["id"], "role": row["role"],
                "conversation_id": row["conversation_id"], "created_at": row["created_at"],
                "evidence_type": row["evidence_type"],
                "conversation_source": source,
            })
        result = []
        for row in rows:
            claim = dict(row)
            payload = json.loads(claim["payload_json"])
            metadata = payload.get("provider_metadata") or {}
            if any(value is not None for value in (domain, area, availability)) and claim["claim_kind"] != "provider_binding":
                continue
            actual = (payload.get("provider"), metadata.get("domain"), metadata.get("area"), metadata.get("availability"))
            wanted = (provider, domain, area, availability)
            if any(value is not None and str(value).casefold() != str(found).casefold()
                   for value, found in zip(wanted, actual)):
                continue
            claim["payload"] = payload
            claim["source_context"] = sources.get(claim["id"], [])
            result.append(claim)
        return result

    @staticmethod
    def _item(claim):
        payload = claim["payload"]
        return {"memory_id": claim["id"], "content": claim["display_text"],
                "reference_kind": "durable_memory", "lookup_operation": "memory.find",
                "claim_kind": claim["claim_kind"], "updated_at": claim["updated_at"],
                "provider": payload.get("provider"), "entity_id": payload.get("external_reference"),
                "epistemic_kind": payload.get("epistemic_kind"),
                "source_context": claim.get("source_context", []),
                "verification_note": payload.get("verification_note"),
                "metadata": payload.get("provider_metadata") or {}}

    def inventory(self, *, provider=None, domain=None, area=None, availability=None, limit=None, offset=0):
        claims = [c for c in self._claims(provider=provider, domain=domain, area=area, availability=availability)
                  if c["claim_kind"] == "provider_binding"]
        return self._page([self._item(c) for c in claims], limit, offset, mode="structured",
                          inventory_updated_at=max((c["updated_at"] for c in claims), default=None),
                          live_verified=False)

    @staticmethod
    def _page(items, limit, offset, **details):
        offset = int(offset)
        if offset < 0 or (limit is not None and int(limit) < 1):
            raise ValueError("Ungültige Seitengröße oder Position")
        page = items[offset:] if limit is None else items[offset:offset + int(limit)]
        end = offset + len(page)
        return {"items": page, "total_matches": len(items), "returned": len(page),
                "offset": offset, "complete": offset == 0 and end >= len(items),
                "has_more": end < len(items), "next_offset": end if end < len(items) else None,
                **details}

    @staticmethod
    def _document(claim):
        # Only observed text/metadata, no hand-maintained vocabulary mappings.
        return json.dumps({"text": claim["display_text"], "kind": claim["claim_kind"],
                           "metadata": claim["payload"]}, ensure_ascii=False, sort_keys=True)

    def _vectors(self, claims, checkpoint):
        with self._lock:
            fd = os.open(self.cache_path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            os.chmod(self.cache_path, 0o600)
            with closing(sqlite3.connect(self.cache_path)) as cache, cache:
                cache.execute("CREATE TABLE IF NOT EXISTS embeddings (claim_id TEXT, identity TEXT, digest TEXT, vector TEXT, PRIMARY KEY(claim_id,identity))")
                cached = {r[0]: r[1:] for r in cache.execute(
                    "SELECT claim_id,digest,vector FROM embeddings WHERE identity=?", (self.client.identity,))}
            with self.runtime.database.connect() as db:
                active_ids = {r[0] for r in db.execute(
                    "SELECT id FROM memory_claims WHERE lifecycle='active' AND valid_until IS NULL")}
            with closing(sqlite3.connect(self.cache_path)) as cache, cache:
                obsolete = [(r[0],) for r in cache.execute("SELECT DISTINCT claim_id FROM embeddings")
                            if r[0] not in active_ids]
                cache.executemany("DELETE FROM embeddings WHERE claim_id=?", obsolete)
            pending, vectors = [], {}
            for claim in claims:
                document = self._document(claim)
                digest = hashlib.sha256(document.encode()).hexdigest()
                old = cached.get(claim["id"])
                if old and old[0] == digest:
                    vectors[claim["id"]] = normalized(json.loads(old[1]))
                else:
                    pending.append((claim["id"], digest, document))
            for start in range(0, len(pending), 16):
                checkpoint()
                batch = pending[start:start + 16]
                embedded = self.client.embed([item[2] for item in batch])
                with closing(sqlite3.connect(self.cache_path)) as cache, cache:
                    for (claim_id, digest, _), vector in zip(batch, embedded, strict=True):
                        vectors[claim_id] = vector
                        cache.execute("INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?)",
                                      (claim_id, self.client.identity, digest, json.dumps(vector)))
            return vectors

    def search(self, query, *, mode="hybrid", provider=None, domain=None, area=None,
               availability=None, limit=20, offset=0, checkpoint=lambda: None):
        checkpoint()
        if not str(query).strip():
            raise ValueError("Suchanfrage fehlt")
        if mode not in {"hybrid", "semantic", "lexical"}:
            raise ValueError("Unbekannter Suchmodus")
        claims = self._claims(provider=provider, domain=domain, area=area, availability=availability)
        by_id = {c["id"]: c for c in claims}
        lexical = []
        if mode != "semantic":
            lexical = [h.memory_id for h in self.runtime.retrieve(query, None) if h.memory_id in by_id]
        scores, methods, warnings = {}, {}, []
        for rank, claim_id in enumerate(lexical, 1):
            scores[claim_id] = 1 / (60 + rank)
            methods[claim_id] = ["lexical"]
        semantic_status = "not_requested"
        if mode != "lexical":
            semantic_status = "unavailable"
            try:
                if self.client is None:
                    raise RuntimeError("Kein Embedding-Modell konfiguriert")
                if claims:
                    vectors = self._vectors(claims, checkpoint)
                    checkpoint()
                    q = self.client.embed([query], query=True)[0]
                    if any(len(v) != len(q) for v in vectors.values()):
                        raise ValueError("Embedding-Dimension hat sich geändert; Index neu aufbauen")
                    ranked = sorted(((cid, sum(a*b for a,b in zip(q,v))) for cid,v in vectors.items()),
                                    key=lambda pair: (-pair[1], pair[0]))
                    # Similarity is a ranking, not proof of category completeness.
                    for rank, (cid, similarity) in enumerate(ranked, 1):
                        if similarity <= 0:
                            continue
                        scores[cid] = scores.get(cid, 0) + 1 / (60 + rank)
                        methods.setdefault(cid, []).append("semantic")
                semantic_status = "available"
            except TurnCancelled:
                raise
            except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                warnings.append("Semantische Suche nicht verfügbar: " + type(exc).__name__)
                if mode == "semantic":
                    raise RuntimeError(warnings[-1]) from exc
        checkpoint()
        # Recheck lifecycle/content after potentially slow embedding calls.
        current = {c["id"]: c for c in self._claims(
            provider=provider, domain=domain, area=area, availability=availability)}
        scores = {cid: score for cid, score in scores.items()
                  if cid in current and self._document(current[cid]) == self._document(by_id[cid])}
        items = []
        for cid in sorted(scores, key=lambda cid: (-scores[cid], cid)):
            items.append({**self._item(by_id[cid]), "rank_score": scores[cid], "methods": methods[cid]})
        return self._page(items, limit, offset, mode=mode, semantic_status=semantic_status,
                          warnings=warnings, completeness_scope="ranked_matches_not_category_inventory",
                          searched_claims=len(claims), live_verified=False)
