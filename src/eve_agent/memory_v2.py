from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone

from .memory import MemoryHit, redact_sensitive
from .memory_compiler import (
    MemoryCompiler, MemoryCompilerCancelled, MemoryNeed, _fts_query_tokens,
)
from .memory_lifecycle import lifecycle_operation
from .runtime_self_knowledge import RuntimeSelfDescription
from .home_assistant_memory import HomeAssistantMemory


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_PROVIDER_PROTOCOL_NAMESPACE = uuid.UUID("bbbc6c43-e512-4a29-a0b6-ea5cb7069a51")


def _protocol_id(kind: str, *parts: str) -> str:
    return str(uuid.uuid5(_PROVIDER_PROTOCOL_NAMESPACE, "|".join((kind, *parts))))


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _response_shape(value):
    """Describe returned structure without persisting provider values."""
    if isinstance(value, dict):
        return {
            redact_sensitive(str(key)): _response_shape(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        return {
            "type": "list", "length": len(value),
            "item": _response_shape(value[0]) if value else None,
        }
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


class MemoryV2Runtime:
    """Productive Memory-v2 read surface; Legacy tables are never consulted."""

    def __init__(self, database, compiler: MemoryCompiler, *, telemetry=None, embedding_client=None):
        self.database = database
        self.compiler = compiler
        self.telemetry = telemetry
        self.home_assistant_memory = HomeAssistantMemory(database)
        from .memory_revision import MemoryRevision
        self.revisions = MemoryRevision(database)
        from .memory_search import MemorySearch
        self.search_index = MemorySearch(self, embedding_client)

    def _begin(self, *, consumer: str, producer: str, query_kind: str,
               telemetry_context: dict | None = None):
        if self.telemetry is None or not self.telemetry.enabled:
            return None
        context = telemetry_context or {}
        return self.telemetry.begin(
            consumer=consumer, producer=producer, query_kind=query_kind,
            trace_id=context.get("trace_id"), turn_id=context.get("turn_id"),
            planner_round_id=context.get("planner_round_id"),
            conversation_id=context.get("conversation_id"),
        )

    @staticmethod
    def self_descriptions() -> list[RuntimeSelfDescription]:
        return [RuntimeSelfDescription(
            "memory_v2.search", "memory.search",
            "Ich kann gespeichertes Wissen durchsuchen und abrufen.",
            "MemoryV2Runtime", "compile_view,retrieve",
        )]

    @staticmethod
    def _context_text(history: list[dict] | None) -> str:
        users = [str(item.get("content") or "") for item in (history or []) if item.get("role") == "user"]
        return users[-1] if users else ""

    def _scopes_for_query(self, query: str) -> tuple[str, ...]:
        scopes = {"legacy:unknown", "legacy:global", "user:default", "user:self", "household:default"}
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT DISTINCT scope FROM memory_claims
                   WHERE lifecycle='active' AND valid_until IS NULL
                   AND scope NOT IN ('semantic_links','semantic_actions','semantic_similarity_relations')
                   ORDER BY scope""",
            ).fetchall()
        scopes.update(str(row[0]) for row in rows)
        return tuple(sorted(scopes))

    def compile_view(self, query: str, consumer: str, *, provider: str | None = None,
                     effect: str = "none", live_verification_required: bool = False,
                     history: list[dict] | None = None, general_memory_needed: bool | None = None,
                     resources: tuple[str, ...] = (), historical: bool = False,
                     telemetry_context: dict | None = None,
                     query_kind: str = "memory.compile_view") -> dict:
        view, operation = self._compile_view(
            query, consumer, provider=provider, effect=effect,
            live_verification_required=live_verification_required, history=history,
            general_memory_needed=general_memory_needed, resources=resources,
            historical=historical, telemetry_context=telemetry_context,
            query_kind=query_kind,
        )
        try:
            if operation is not None:
                for ordinal, claim in enumerate(view["claims"]):
                    operation.returned(str(claim["id"]), ordinal=ordinal)
                operation.complete(result_count=len(view["claims"]))
            return view
        except BaseException as exc:
            if operation is not None:
                operation.abort(exc, cancelled=isinstance(exc, MemoryCompilerCancelled))
            raise

    def _compile_view(self, query: str, consumer: str, *, provider: str | None = None,
                      effect: str = "none", live_verification_required: bool = False,
                      history: list[dict] | None = None,
                      general_memory_needed: bool | None = None,
                      resources: tuple[str, ...] = (), historical: bool = False,
                      telemetry_context: dict | None = None,
                      query_kind: str = "memory.compile_view"):
        operation = self._begin(
            consumer=consumer, producer="memory.v2.compiler", query_kind=query_kind,
            telemetry_context=telemetry_context,
        )
        try:
            need = MemoryNeed(
                consumer=consumer, query=query, provider=provider, effect=effect,
                scopes=self._scopes_for_query(query),
                live_verification_required=live_verification_required,
                historical=bool(historical),
                conversation_text=self._context_text(history),
                general_memory_needed=general_memory_needed, resources=resources,
            )
            return self.compiler.preview(need, telemetry_operation=operation), operation
        except BaseException as exc:
            if operation is not None:
                operation.abort(exc, cancelled=isinstance(exc, MemoryCompilerCancelled))
            raise

    def retrieve(self, query: str, limit: int | None = None, *, historical: bool = False,
                 consumer: str = "answer",
                 telemetry_context: dict | None = None,
                 query_kind: str = "memory.retrieve") -> list[MemoryHit]:
        view, operation = self._compile_view(
            query, consumer, historical=historical,
            telemetry_context=telemetry_context, query_kind=query_kind,
        )
        try:
            claims = view["claims"]
            if limit is not None:
                claims = claims[:max(1, int(limit))]
            hits = [
                MemoryHit(
                    text=str(claim.get("display_text") or ""), score=1.0,
                    memory_id=str(claim["id"]), method="memory_v2",
                    compiler_evaluation_id=(
                        operation.compiler_evaluation_id if operation is not None else None
                    ),
                )
                for claim in claims
            ]
            if operation is not None:
                for ordinal, claim in enumerate(claims):
                    operation.returned(str(claim["id"]), ordinal=ordinal, method="memory_v2")
                operation.complete(result_count=len(claims))
            return hits
        except BaseException as exc:
            if operation is not None:
                operation.abort(exc, cancelled=isinstance(exc, MemoryCompilerCancelled))
            raise

    def standing_instructions(self, *, telemetry_context=None):
        """Read explicitly global, user-grounded instructions without query ranking."""
        operation = self._begin(consumer="native_tool", producer="memory.v2.standing_instructions",
                                query_kind="memory.standing_instructions", telemetry_context=telemetry_context)
        try:
            with self.database.connect() as connection:
                rows = connection.execute("""
                    SELECT c.* FROM memory_claims c
                    WHERE c.lifecycle='active' AND (c.valid_until IS NULL OR c.valid_until>?)
                      AND (c.valid_from IS NULL OR c.valid_from<=?)
                      AND json_extract(c.payload_json,'$.epistemic_kind')='user_instruction'
                      AND json_extract(c.payload_json,'$.applicability')='always'
                      AND EXISTS (
                          SELECT 1 FROM memory_evidence e JOIN messages m ON m.id=e.source_message_id
                          WHERE e.claim_id=c.id AND e.stance='supports'
                            AND e.evidence_type='user_message' AND m.role='user'
                            AND length(c.display_text)>0 AND instr(m.content,c.display_text)>0)
                    ORDER BY c.created_at,c.id
                """, (_now(), _now())).fetchall()
            items = [{"memory_id": str(row["id"]), "content": row["display_text"],
                      "reference_kind": "durable_memory", "lookup_operation": "memory.find",
                      "applicability": "always"} for row in rows]
            if operation is not None:
                for ordinal, item in enumerate(items):
                    operation.returned(item['memory_id'], ordinal=ordinal, method="explicit_applicability")
                operation.complete(result_count=len(items))
            return items
        except BaseException as exc:
            if operation is not None:
                operation.abort(exc)
            raise

    def query_memory(self, operation, parameters, *, telemetry_context=None, checkpoint=None):
        """Expose structured/semantic results with the existing retrieval audit."""
        observation = self._begin(
            consumer="native_tool", producer="memory.v2.search",
            query_kind="memory." + operation, telemetry_context=telemetry_context,
        )
        try:
            method = self.search_index.inventory if operation == "inventory" else self.search_index.search
            arguments = dict(parameters)
            if checkpoint is not None:
                checkpoint()
                if operation != "inventory":
                    arguments["checkpoint"] = checkpoint
            result = method(**arguments)
            if observation is not None:
                for ordinal, item in enumerate(result["items"]):
                    observation.returned(item["memory_id"], ordinal=ordinal, method=result["mode"])
                observation.complete(result_count=result["returned"])
            return result
        except BaseException as exc:
            if observation is not None:
                observation.abort(exc)
            raise

    def provider_bindings(self, query: str, *, history: list[dict] | None = None,
                          telemetry_context: dict | None = None) -> list[dict]:
        view, operation = self._compile_view(
            query, "native_tool", provider="home_assistant", history=history,
            telemetry_context=telemetry_context, query_kind="provider_binding.query",
        )
        try:
            bindings = []
            for claim in view["claims"]:
                if claim["claim_kind"] != "provider_binding" or claim.get("conflict"):
                    continue
                bindings.append(self._provider_binding(claim))
                if operation is not None:
                    operation.returned(str(claim["id"]), ordinal=len(bindings) - 1,
                                       method="provider_binding")
            if operation is not None:
                operation.complete(result_count=len(bindings))
            return bindings
        except BaseException as exc:
            if operation is not None:
                operation.abort(exc, cancelled=isinstance(exc, MemoryCompilerCancelled))
            raise

    def provider_context_claims(self, query: str, provider: str, *,
                                telemetry_context: dict | None = None) -> list[dict]:
        """Retrieve provider-owned non-resource claims before semantic planning.

        The provider identity and FTS rank are structural retrieval constraints.
        This method does not decide which operation, effect or resource the user
        intends; it only publishes real active claims for the model to consider.
        """
        provider = str(provider or "").strip()
        tokens = _fts_query_tokens(query)
        if not provider or not tokens:
            return []
        operation = self._begin(
            consumer="native_tool", producer="memory.v2.provider_context",
            query_kind="provider_context.predecision",
            telemetry_context=telemetry_context,
        )
        try:
            expression = self.compiler._fts_expression(tokens)
            with self.database.connect() as connection:
                rows = connection.execute(
                    """SELECT c.*,bm25(memory_claims_fts) AS fts_rank
                       FROM memory_claims_fts f
                       JOIN memory_claims c ON c.id=f.claim_id
                       WHERE memory_claims_fts MATCH ?
                         AND c.lifecycle='active' AND c.valid_until IS NULL
                         AND c.claim_kind!='provider_binding'
                         AND c.scope NOT LIKE 'portable:%'
                         AND json_extract(c.payload_json,'$.provider')=?
                       ORDER BY fts_rank,c.updated_at DESC,c.id""",
                    (expression, provider),
                ).fetchall()
            claims = []
            for row in rows:
                payload = json.loads(row["payload_json"] or "{}")
                item = {
                    "memory_id": str(row["id"]),
                    "claim_kind": str(row["claim_kind"]),
                    "scope": str(row["scope"]),
                    "content": str(row["display_text"] or ""),
                }
                identity = {
                    key: payload[key] for key in ("kind", "domain", "locale")
                    if payload.get(key) is not None
                }
                if identity:
                    item["identity"] = identity
                if payload.get("kind") == "provider_protocol_experience":
                    item["provider_evidence"] = {
                        "request_signature": payload.get("request_signature"),
                        "response": payload.get("response"),
                    }
                claims.append(item)
                if operation is not None:
                    operation.returned(
                        str(row["id"]), ordinal=len(claims) - 1, method="provider_fts",
                    )
            if operation is not None:
                operation.complete(result_count=len(claims))
            return claims
        except BaseException as exc:
            if operation is not None:
                operation.abort(exc, cancelled=isinstance(exc, MemoryCompilerCancelled))
            raise

    @staticmethod
    def _provider_request_signature(operation: str, request: dict) -> dict:
        """Keep the provider-confirmed interface shape, never credentials or bodies."""
        signature = {"operation": redact_sensitive(str(operation or ""))}
        if "method" in request or "path" in request:
            signature.update({
                "method": redact_sensitive(str(request.get("method") or "")),
                "path": redact_sensitive(str(request.get("path") or "")),
                "query_keys": sorted(str(key) for key in (request.get("query") or {})),
            })
            return signature
        command = request.get("command")
        if isinstance(command, dict):
            signature.update({
                "command_type": redact_sensitive(str(command.get("type") or "")),
                "command_fields": sorted(
                    redact_sensitive(str(key)) for key in command if str(key) != "id"
                ),
            })
            return signature
        signature["request_fields"] = sorted(
            redact_sensitive(str(key)) for key in request
        )
        return signature

    @lifecycle_operation("memory.provider_protocol", "confirmed_provider_experience")
    def record_provider_protocol_experience(
            self, provider: str, operation: str, query: str, result: dict, *,
            trace_id: str | None = None, conversation_id: str | None = None) -> dict | None:
        """Persist only interface facts proven by a successful native provider response."""
        provider = redact_sensitive(str(provider or "").strip())
        request = result.get("request") if isinstance(result, dict) else None
        if not provider or not isinstance(request, dict) or result.get("status") != "completed":
            return None
        signature = self._provider_request_signature(operation, request)
        signature_json = _json(signature)
        digest = hashlib.sha256(
            f"{provider}|{signature_json}".encode("utf-8")
        ).hexdigest()
        claim_id = _protocol_id("claim", provider, digest)
        now = _now()
        safe_query = redact_sensitive(str(query or "").strip())
        response = result.get("response") if isinstance(result.get("response"), dict) else {}
        response_fact = {
            "status": response.get("status"),
            "content_type": redact_sensitive(str(response.get("content_type") or "")) or None,
            "shape": _response_shape(response.get("body", response)),
        }
        scope = f"provider:{provider}:protocol"
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT payload_json,created_at FROM memory_claims WHERE id=?", (claim_id,),
            ).fetchone()
            payload = {
                "provider": provider,
                "kind": "provider_protocol_experience",
                "operation": redact_sensitive(str(operation or "")),
                "request_signature": signature,
                "response": response_fact,
                "last_verified_at": now,
            }
            display = f"Provider {provider} confirmed native interface {_json(signature)}."
            if existing:
                connection.execute(
                    """UPDATE memory_claims SET slot_key=?,display_text=?,payload_json=?,lifecycle='active',
                       valid_until=NULL,updated_at=? WHERE id=?""",
                    (f"provider-protocol:{digest}", display, _json(payload), now, claim_id),
                )
                decision_type = "append_supporting_evidence"
            else:
                connection.execute(
                    """INSERT INTO memory_claims
                       (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,
                        lifecycle,valid_from,valid_until,verification_policy,created_at,updated_at)
                       VALUES (?,'opaque_fact',?,?,?,?,?,'active',?,NULL,'dynamic',?,?)""",
                    (claim_id, scope, f"provider-protocol:{digest}",
                     f"provider-protocol:{digest}", display, _json(payload), now, now, now),
                )
                decision_type = "create_active"

            occurrence = str(trace_id or uuid.uuid4().hex)
            observation_id = _protocol_id(
                "observation", claim_id, occurrence, uuid.uuid4().hex,
            )
            observation = {
                "provider": provider, "operation": str(operation or ""),
                "request_signature": signature, "response": response_fact,
            }
            if safe_query:
                observation["turn_request"] = safe_query
            connection.execute(
                """INSERT INTO memory_observations
                   (id,source_role,source_type,external_ref,excerpt,structured_value_json,
                    observed_at,scope,metadata_json,created_at)
                   VALUES (?,'provider','provider_result',?,?,?,?,?,?,?)""",
                (observation_id, occurrence, display, _json(observation), now, scope,
                 _json({"conversation_id": conversation_id} if conversation_id else {}), now),
            )
            evidence_id = _protocol_id("evidence", claim_id, observation_id)
            connection.execute(
                """INSERT INTO memory_evidence
                   (id,claim_id,observation_id,stance,evidence_type,source_ref,excerpt,payload_json,
                    observed_at,effective_from,created_at)
                   VALUES (?,?,?,'supports','provider_response',?,?,?,?,?,?)""",
                (evidence_id, claim_id, observation_id, occurrence, display,
                 _json(observation), now, now, now),
            )
            decision_id = _protocol_id("decision", observation_id)
            connection.execute(
                """INSERT INTO memory_learning_decisions
                   (id,observation_id,decision_type,method,rationale,metadata_json,uncertainty,created_at)
                   VALUES (?,?,?,'deterministic_provider_confirmation',?,?,0,?)""",
                (decision_id, observation_id, decision_type,
                 "Native provider accepted the exact request and returned success.",
                 _json({"provider": provider, "operation": str(operation or "")}), now),
            )
            connection.execute(
                "INSERT INTO memory_learning_decision_claims(decision_id,claim_id) VALUES (?,?)",
                (decision_id, claim_id),
            )
        return {"memory_id": claim_id, "created": not bool(existing)}

    @staticmethod
    def _provider_binding(claim: dict) -> dict:
        payload = json.loads(claim.get("payload_json") or "{}")
        metadata = payload.get("provider_metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        services = list(metadata.get("services") or [])
        service_fields = dict(metadata.get("service_fields") or {})
        return {
            "provider": payload.get("provider"), "subject": payload.get("subject"),
            "property": payload.get("property"),
            "entity_id": payload.get("external_reference"),
            "memory_id": claim["id"], "score": 1.0,
            "stored_not_live_verified": True,
            "inventory_source": payload.get("inventory_source"),
            "domain": metadata.get("domain"),
            "area": metadata.get("area"),
            "device_class": metadata.get("device_class"),
            "unit": metadata.get("unit"),
            "availability": metadata.get("availability"),
            "supported_features": metadata.get("supported_features"),
            "services": services,
            "service_fields": service_fields,
            "properties": list(metadata.get("properties") or []),
            "inventory_contract_complete": all(
                service in service_fields for service in services
            ),
            "members": list(metadata.get("members") or []),
        }

    @staticmethod
    def _inventory_identity_tokens(value: str) -> set[str]:
        """Tokenize provider-owned identity text, including short technical names.

        General memory retrieval deliberately ignores very short words. Provider
        inventories cannot do that: names such as TV, PV and CO2 are meaningful
        identifiers. Exact token equality keeps this lookup lexical and avoids
        adding language or household semantics to Python.
        """
        spelling = str(value).casefold().translate(str.maketrans({
            "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
        }))
        folded = "".join(
            character for character in unicodedata.normalize("NFKD", spelling)
            if not unicodedata.combining(character)
        )
        return set(re.findall(r"[^\W_]{2,}", folded.replace("_", " ")))

    @staticmethod
    def _single_edit_identity_variant(left: str, right: str) -> bool:
        """Accept one conservative spelling edit in a longer identity token."""
        if left == right:
            return True
        if min(len(left), len(right)) < 5 or abs(len(left) - len(right)) > 1:
            return False
        if left[:3] != right[:3]:
            return False
        previous = list(range(len(right) + 1))
        for row, left_character in enumerate(left, 1):
            current = [row]
            for column, right_character in enumerate(right, 1):
                current.append(min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (left_character != right_character),
                ))
            previous = current
            if min(current) > 1:
                return False
        return previous[-1] <= 1

    def _lexical_inventory_bindings(self, query: str) -> list[dict]:
        query_tokens = self._inventory_identity_tokens(query)
        if not query_tokens:
            return []
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM memory_claims
                   WHERE lifecycle='active' AND valid_until IS NULL
                     AND claim_kind='provider_binding'
                     AND json_extract(payload_json,'$.provider')='home_assistant'
                     AND json_extract(payload_json,'$.inventory_source')='home_assistant'
                   ORDER BY canonical_key,id""",
            ).fetchall()
        candidates = []
        for row in rows:
            claim = dict(row)
            payload = json.loads(claim.get("payload_json") or "{}")
            metadata = payload.get("provider_metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            identity = " ".join(str(value or "") for value in (
                payload.get("subject"), payload.get("external_reference"),
                metadata.get("name"), metadata.get("area"),
            ))
            identity_tokens = self._inventory_identity_tokens(identity)
            matched = {
                query_token for query_token in query_tokens
                if any(
                    self._single_edit_identity_variant(query_token, identity_token)
                    or (
                        min(len(query_token), len(identity_token)) >= 4
                        and identity_token.startswith(query_token)
                    )
                       for identity_token in identity_tokens)
            }
            if matched:
                exact = matched & identity_tokens
                candidates.append((claim, payload, matched, exact))
        frequencies = {
            token: sum(token in matched for _claim, _payload, matched, _exact in candidates)
            for token in query_tokens
        }
        ranked = []
        for claim, payload, matched, exact in candidates:
            score = sum(1.0 / max(1, frequencies[token]) for token in matched)
            score += 0.05 * len(exact)
            binding = self._provider_binding(claim)
            binding["_inventory_match_score"] = score
            ranked.append((
                -score, -len(matched), str(payload.get("external_reference") or ""), binding,
            ))
        return [binding for _score, _count, _reference, binding in sorted(ranked)]

    def inventory_bindings(self, query: str = "", *, namespace: str | None = None,
                           namespace_hint: str | None = None,
                           cursor: int = 0, limit: int | None = None,
                           history: list[dict] | None = None,
                           telemetry_context: dict | None = None) -> dict:
        """Return HA inventory facts without consulting the provider.

        Namespace selection is an exact technical filter supplied by the
        semantic planner. Text selection reuses the Memory-v2 compiler and its
        formal retrieval rules; this method contains no language mapping.
        """
        cursor = max(0, int(cursor))
        if namespace:
            with self.database.connect() as connection:
                where = """lifecycle='active' AND valid_until IS NULL
                    AND claim_kind='provider_binding'
                    AND json_extract(payload_json,'$.provider')='home_assistant'
                    AND json_extract(payload_json,'$.inventory_source')='home_assistant'
                    AND json_extract(payload_json,'$.provider_metadata.domain')=?"""
                total = int(connection.execute(
                    f"SELECT count(*) FROM memory_claims WHERE {where}", (namespace,),
                ).fetchone()[0])
                sql = f"SELECT * FROM memory_claims WHERE {where} ORDER BY canonical_key,id"
                parameters: list = [namespace]
                if limit is not None:
                    sql += " LIMIT ? OFFSET ?"
                    parameters.extend([max(1, int(limit)), cursor])
                elif cursor:
                    sql += " LIMIT -1 OFFSET ?"
                    parameters.append(cursor)
                rows = connection.execute(sql, parameters).fetchall()
            bindings = [self._provider_binding(dict(row)) for row in rows]
        else:
            compiled = [
                item for item in self.provider_bindings(
                    query, history=history, telemetry_context=telemetry_context,
                )
                if item.get("inventory_source") == "home_assistant"
            ]
            # Exact provider identity tokens are authoritative inventory data,
            # not inferred semantics. Put them before broader compiler matches
            # so a rare device name is not displaced by a generic property.
            lexical = self._lexical_inventory_bindings(query)
            hinted_lexical = [
                item for item in lexical
                if namespace_hint
                and str(item.get("domain") or "").casefold() == namespace_hint.casefold()
            ]
            hinted_score = max(
                (float(item.get("_inventory_match_score") or 0) for item in hinted_lexical),
                default=0.0,
            )
            other_scores = [
                float(item.get("_inventory_match_score") or 0) for item in lexical
                if not namespace_hint
                or str(item.get("domain") or "").casefold() != namespace_hint.casefold()
            ]
            constrain_to_hint = bool(hinted_lexical) and (
                not other_scores or hinted_score > max(other_scores) + 1e-12
            )
            combined = {}
            for item in [*(hinted_lexical if constrain_to_hint else lexical), *compiled]:
                combined.setdefault(str(item.get("entity_id") or ""), item)
            all_bindings = [item for key, item in combined.items() if key]
            if constrain_to_hint:
                all_bindings = [
                    item for item in all_bindings
                    if str(item.get("domain") or "").casefold() == namespace_hint.casefold()
                ]
            total = len(all_bindings)
            bindings = [
                {key: value for key, value in item.items() if not key.startswith("_inventory_")}
                for item in (
                    all_bindings[cursor:]
                    if limit is None else all_bindings[cursor:cursor + max(1, int(limit))]
                )
            ]
        return {
            "bindings": bindings,
            "cursor": cursor,
            "next_cursor": cursor + len(bindings) if cursor + len(bindings) < total else None,
            "total": total,
            "source": "memory_v2.home_assistant_inventory",
        }

    def inventory_identity_bindings(self, query: str, *, limit: int | None = None) -> dict:
        """Return exact lexical provider-identity candidates from Memory.

        This is candidate retrieval only.  It does not select a resource,
        operation, provider or effect; the model receives the candidates and
        makes those decisions itself.
        """
        lexical = self._lexical_inventory_bindings(query)
        bindings = [
            {key: value for key, value in item.items() if not key.startswith("_inventory_")}
            for item in (lexical if limit is None else lexical[:max(1, int(limit))])
        ]
        return {
            "bindings": bindings,
            "total": len(lexical),
            "source": "memory_v2.home_assistant_inventory.identity",
        }

    def home_assistant_language_hints(self, query: str, provider: dict, *,
                                      locale="de", limit: int | None = None) -> list[dict]:
        return self.home_assistant_memory.language_hints(
            query, provider, locale=locale, limit=limit,
        )

    def home_assistant_language_profile(self, domain: str, provider: dict, *,
                                        locale="de") -> dict | None:
        return self.home_assistant_memory.language_profile(
            domain, provider, locale=locale,
        )

    def home_assistant_ambiguity_hints(self, query: str, provider: dict, *,
                                       locale="de", limit: int | None = None) -> list[dict]:
        return self.home_assistant_memory.ambiguity_hints(
            query, provider, locale=locale, limit=limit,
        )

    def home_assistant_policy_overview(self, provider: dict) -> dict:
        return self.home_assistant_memory.overview(provider)

    def set_home_assistant_aggregate_policy(self, provider: dict, excluded_areas: list[str],
                                            *, source_ref="ui:home-assistant-policy") -> dict:
        return self.home_assistant_memory.set_aggregate_policy(
            provider, excluded_areas, source_ref=source_ref,
        )

    def apply_home_assistant_aggregate_policy(self, provider: dict, bindings: list[dict], *,
                                              effect: str, explicit_target: bool) -> dict:
        return self.home_assistant_memory.apply_aggregate_policy(
            provider, bindings, effect=effect, explicit_target=explicit_target,
        )

    def device_aliases(self, *, consumer: str = "home_assistant",
                       telemetry_context: dict | None = None) -> dict[str, tuple[str, str]]:
        operation = self._begin(
            consumer=consumer, producer="memory.v2.aliases",
            query_kind="alias.stt" if consumer == "stt" else "alias.provider",
            telemetry_context=telemetry_context,
        )
        aliases = {}
        try:
            with self.database.connect() as connection:
                rows = connection.execute(
                    """SELECT id,payload_json FROM memory_claims
                       WHERE claim_kind='alias' AND lifecycle='active'
                       AND (valid_until IS NULL OR valid_until>?) ORDER BY updated_at DESC""",
                    (_now(),),
                ).fetchall()
            resolved_ids = []
            for row in rows:
                payload = json.loads(row["payload_json"] or "{}")
                alias, target = str(payload.get("alias") or ""), str(payload.get("target") or "")
                if alias and target:
                    aliases[alias.casefold()] = (alias, target)
                    resolved_ids.append(str(row["id"]))
            if operation is not None:
                for claim_id in resolved_ids:
                    operation.resolved(
                        claim_id, kind="alias_read_for_stt" if consumer == "stt" else "claim_resolved",
                        result_count=len(resolved_ids),
                    )
                operation.complete(result_count=len(resolved_ids))
            return aliases
        except BaseException as exc:
            if operation is not None:
                operation.abort(exc)
            raise

    def record_claim_resolution(self, claim_id: str, *, consumer: str,
                                query_kind: str, telemetry_context: dict | None = None) -> None:
        """Record an already known persistent identity without resolving it again."""
        operation = self._begin(
            consumer=consumer, producer="memory.v2.deterministic",
            query_kind=query_kind, telemetry_context=telemetry_context,
        )
        if operation is None:
            return
        operation.resolved(str(claim_id), result_count=1)
        operation.complete(result_count=1)

    def list_memories(self, limit: int | None = None) -> list[str]:
        with self.database.connect() as connection:
            sql = """SELECT display_text FROM memory_claims WHERE lifecycle='active'
                     AND (valid_until IS NULL OR valid_until>?) ORDER BY updated_at DESC"""
            parameters = [_now()]
            if limit is not None:
                sql += " LIMIT ?"
                parameters.append(max(1, int(limit)))
            rows = connection.execute(sql, parameters).fetchall()
        return [str(row[0]) for row in rows]

    def runtime_self_knowledge(self, limit: int | None = None) -> list[dict]:
        """Read the active runtime self-description claims from Memory V2."""
        with self.database.connect() as connection:
            sql = """SELECT id,display_text,payload_json FROM memory_claims
                     WHERE scope='provider:runtime' AND lifecycle='active'
                     AND valid_until IS NULL
                     AND json_extract(payload_json,'$.runtime_self_knowledge')=1
                     ORDER BY canonical_key"""
            parameters = []
            if limit is not None:
                sql += " LIMIT ?"
                parameters.append(max(1, int(limit)))
            rows = connection.execute(sql, parameters).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row["payload_json"] or "{}")
            result.append({
                "memory_id": str(row["id"]),
                "capability_id": str(payload.get("capability_id") or ""),
                "content": str(row["display_text"] or ""),
                "operations": sorted({
                    operation.strip()
                    for source in payload.get("sources", [])
                    if isinstance(source, dict)
                    for operation in str(source.get("operation") or "").split(",")
                    if operation.strip()
                }),
            })
        return result

    @lifecycle_operation("memory.forget", "explicit_forget")
    def forget(self, query: str, *, trace_id: str | None = None,
               turn_id: str | None = None, conversation_id: str | None = None) -> list[str]:
        view = self.compile_view(
            query, "answer", general_memory_needed=True,
            telemetry_context={
                "trace_id": trace_id, "turn_id": turn_id,
                "conversation_id": conversation_id,
            }, query_kind="memory.forget.lookup",
        )
        claims = [claim for claim in view["claims"] if claim["lifecycle"] == "active"]
        if not claims:
            return []
        now = _now()
        retired = []
        with self.database.connect() as connection:
            self.database.assert_runtime_self_knowledge_writable(
                connection, claim_ids=[claim["id"] for claim in claims],
            )
            for claim in claims:
                cursor = connection.execute(
                    """UPDATE memory_claims SET lifecycle='retired',valid_until=?,updated_at=?
                       WHERE id=? AND lifecycle='active'""",
                    (now, now, claim["id"]),
                )
                if cursor.rowcount:
                    retired.append(str(claim.get("display_text") or ""))
        return retired
