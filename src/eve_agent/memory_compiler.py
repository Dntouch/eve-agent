from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from .memory import cosine_similarity, lexical_vector, redact_sensitive


COMPILER_VERSION = "memory-v2-compiler-production-v3"
RETRIEVAL_VERSION = "structured-fts-v4"
ELIGIBILITY_VERSION = "lifecycle-scope-time-relevance-v5"
PROJECTION_VERSION = "deterministic-coverage-v4"
BUDGET_VERSION = "model-server-context-v1"
_NAMESPACE = uuid.UUID("ef2874db-3956-4fc0-b21a-84fb55d00517")
_WORDS = re.compile(r"[^\W_]{3,}", re.UNICODE)
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokens(text: str) -> list[str]:
    return sorted(set(_WORDS.findall(str(text).casefold())))


def _fts_query_tokens(text: str) -> list[str]:
    """Order tokens by language-neutral structural distinctiveness."""
    ordered = list(dict.fromkeys(_WORDS.findall(str(text).casefold())))
    positions = {token: index for index, token in enumerate(ordered)}
    return sorted(ordered, key=lambda token: (-len(token), positions[token]))


def _token_count(text: str) -> int:
    # Deliberately conservative fallback including structural punctuation.
    return max(1, (len(str(text).encode("utf-8")) + 2) // 3)


def _stable_hash(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class MemoryNeed:
    consumer: str
    query: str
    scopes: tuple[str, ...] = (
        "legacy:unknown", "legacy:global", "user:default", "user:self", "household:default",
    )
    provider: str | None = None
    resources: tuple[str, ...] = ()
    effect: str = "none"
    live_verification_required: bool = False
    historical: bool = False
    audit: bool = False
    target_candidates: tuple[str, ...] = ()
    reference_text: str = ""
    conversation_text: str = ""
    general_memory_needed: bool | None = None


@dataclass
class _Candidate:
    claim: dict
    methods: set[str] = field(default_factory=set)
    reasons: set[str] = field(default_factory=set)
    score: float = 0.0
    requirement: str = "optional"
    conflict: bool = False
    provenance: list[str] = field(default_factory=list)
    relation_ids: set[str] = field(default_factory=set)


class MemoryCompilerCancelled(RuntimeError):
    pass


class MemoryCompiler:
    """Deterministic Memory-v2 compiler shared by preview and persisted audit."""

    def __init__(self, database, diagnostics=None, *, config: dict | None = None):
        defaults = {
            "retrieval_mode": "structured_fts",
        }
        self.database = database
        self.diagnostics = diagnostics
        self.config = {**defaults, **(config or {})}
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._cancel: threading.Event | None = None
        self._generation = 0

    def prioritize_interactive_turn(self) -> None:
        with self._state_lock:
            self._generation += 1
            if self._cancel is not None:
                self._cancel.set()

    def priority_token(self) -> int:
        with self._state_lock:
            return self._generation

    def rebuild_fts(self) -> int:
        """Rebuild the derived index without modifying any Memory-v2 truth row."""
        with self.database.connect() as connection:
            connection.execute("DELETE FROM memory_claims_fts")
            rows = connection.execute(
                "SELECT id,display_text,canonical_key,slot_key,payload_json FROM memory_claims ORDER BY id"
            ).fetchall()
            connection.executemany(
                "INSERT INTO memory_claims_fts(claim_id,display_text,structured_terms) VALUES (?,?,?)",
                [(r["id"], r["display_text"], " ".join(filter(None, (
                    r["canonical_key"], r["slot_key"], r["payload_json"],
                )))) for r in rows],
            )
        return len(rows)

    def compile_turn(self, turn_id: str, consumer: str, *, need: MemoryNeed | None = None,
                     expected_priority_generation: int | None = None,
                     queued_at_monotonic: float | None = None) -> dict:
        if consumer not in {"planner", "native_tool", "answer", "audit"}:
            raise ValueError("Unbekannter Memory-Consumer")
        event = threading.Event()
        with self._lock:
            with self._state_lock:
                self._cancel = event
                stale = (expected_priority_generation is not None and
                         expected_priority_generation != self._generation)
            snapshot = self._snapshot(turn_id)
            need = need or self._derive_need(snapshot, consumer)
            if need.consumer != consumer:
                raise ValueError("MemoryNeed gehört zu einem anderen Consumer")
            try:
                if stale or event.is_set():
                    raise MemoryCompilerCancelled("interactive_priority")
                return self._compile(snapshot, need, event, queued_at_monotonic=queued_at_monotonic)
            except MemoryCompilerCancelled:
                return self._persist(snapshot, need, [], [], "cancelled", "", 0, False,
                                     {"reason": "interactive_priority"})
            except Exception as exc:
                self._diagnostic(exc, turn_id)
                return self._persist(snapshot, need, [], [], "error", "", 0, False,
                                     {"error_class": type(exc).__name__})
            finally:
                with self._state_lock:
                    if self._cancel is event:
                        self._cancel = None

    def preview(self, need: MemoryNeed, *, at: str | None = None,
                tools: list[dict] | None = None, telemetry_operation=None) -> dict:
        """Compile the productive pre-prompt view without writing truth or audit."""
        if need.consumer not in {"planner", "native_tool", "answer", "audit"}:
            raise ValueError("Unbekannter Memory-Consumer")
        with self.database.connect() as connection:
            claims = connection.execute(
                "SELECT id,updated_at,lifecycle FROM memory_claims ORDER BY id"
            ).fetchall()
        snapshot = {
            "turn_id": "preview", "conversation_id": "preview", "at": at or _now(),
            "user": redact_sensitive(need.query), "assistant": "", "route": "preview",
            "flow": {}, "tools": [self._normalize_tool_event(item) for item in (tools or [])],
            "context": [],
            "claim_snapshot": _stable_hash([tuple(row) for row in claims]),
        }
        return self._compile(
            snapshot, need, threading.Event(), persist=False,
            telemetry_operation=telemetry_operation,
        )

    def _snapshot(self, turn_id: str) -> dict:
        with self.database.connect() as connection:
            turn = connection.execute("SELECT * FROM turns WHERE id=?", (str(turn_id),)).fetchone()
            if turn is None:
                raise KeyError("Turn wurde nicht gefunden")
            user = connection.execute("SELECT content FROM messages WHERE id=?", (turn["user_message_id"],)).fetchone()
            assistant = connection.execute(
                "SELECT content,metadata_json FROM messages WHERE id=?", (turn["assistant_message_id"],)
            ).fetchone()
            tools = connection.execute(
                "SELECT id,tool,status,input_json,result_json FROM conversation_tool_events WHERE message_id=? ORDER BY ordinal",
                (turn["assistant_message_id"],),
            ).fetchall()
            context = connection.execute(
                """SELECT prior.role,prior.content FROM messages current
                   JOIN messages prior ON prior.conversation_id=current.conversation_id
                    AND prior.ordinal<current.ordinal
                   WHERE current.id=? ORDER BY prior.ordinal DESC""",
                (turn["user_message_id"],),
            ).fetchall()
            claims = connection.execute(
                "SELECT id,updated_at,lifecycle FROM memory_claims ORDER BY id"
            ).fetchall()
        flow = self._json_object(turn["knowledge_flow_json"])
        metadata = self._json_object(assistant["metadata_json"]) if assistant else {}
        return {
            "turn_id": str(turn_id), "conversation_id": str(turn["conversation_id"]),
            "at": str(turn["created_at"]), "user": redact_sensitive(user["content"] if user else ""),
            "assistant": redact_sensitive(assistant["content"] if assistant else ""),
            "route": str(metadata.get("route") or "unknown"), "flow": flow,
            "tools": [self._normalize_tool_event(row) for row in tools],
            "context": [dict(row) for row in reversed(context)],
            "claim_snapshot": _stable_hash([tuple(row) for row in claims]),
        }

    @staticmethod
    def _json_object(value) -> dict:
        if isinstance(value, dict):
            return dict(value)
        if not isinstance(value, str) or not value.strip():
            return {}
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @classmethod
    def _normalize_tool_event(cls, row) -> dict:
        """Normalize current and historical persistence shapes at one boundary."""
        item = dict(row) if not isinstance(row, dict) else row
        return {
            "id": str(item.get("id") or ""),
            "tool": str(item.get("tool") or "unknown"),
            "status": str(item.get("status") or "unknown"),
            "input": cls._json_object(item.get("input_json", item.get("input"))),
            "result": cls._json_object(item.get("result_json", item.get("result"))),
        }

    def _derive_need(self, snapshot: dict, consumer: str) -> MemoryNeed:
        provider = "home_assistant" if snapshot["route"] == "home" else None
        resources: set[str] = set()
        reference_parts: list[str] = []
        effect, live_required = "none", False
        for tool in snapshot["tools"]:
            inputs, results = tool["input"], tool["result"]
            for value in self._walk_strings({"input": inputs, "result": results}):
                if re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", value):
                    resources.add(value)
                elif value != snapshot["user"]:
                    reference_parts.append(value)
            published_effect = inputs.get("effect") or results.get("effect")
            if published_effect in {"read", "write"}:
                effect = published_effect
            live_required = live_required or bool(inputs.get("live_verification_required"))
        resources.update(re.findall(r"\b[a-z_]+\.[a-z0-9_]+\b", snapshot["user"].casefold()))
        prior_users = [str(item["content"]) for item in snapshot["context"] if item["role"] == "user"]
        conversation_text = prior_users[-1] if prior_users else ""
        return MemoryNeed(consumer=consumer, query=snapshot["user"], provider=provider,
                          resources=tuple(sorted(resources)), effect=effect,
                          live_verification_required=live_required,
                          historical=False,
                          reference_text=" ".join(reference_parts), conversation_text=conversation_text,
                          general_memory_needed=(True if snapshot["route"] == "memory" else None))

    @staticmethod
    def _walk_strings(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from MemoryCompiler._walk_strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from MemoryCompiler._walk_strings(item)
        elif isinstance(value, str):
            yield value

    def _compile(self, snapshot: dict, need: MemoryNeed, event: threading.Event,
                 *, queued_at_monotonic: float | None = None, persist: bool = True,
                 telemetry_operation=None) -> dict:
        started = time.perf_counter()
        candidates = self._retrieve(need)
        traversed_relation_ids = list(dict.fromkeys(
            relation_id
            for candidate in candidates.values()
            for relation_id in sorted(candidate.relation_ids)
        ))
        audit = [(item, "retrieved", "+".join(sorted(item.methods)), "candidate_retrieved")
                 for item in candidates.values()]
        eligible: list[_Candidate] = []
        for candidate in candidates.values():
            if event.is_set():
                raise MemoryCompilerCancelled()
            reason = self._eligibility(candidate.claim, need, snapshot["at"])
            if reason:
                audit.append((candidate, "rejected", "+".join(sorted(candidate.methods)), reason))
            else:
                candidate.provenance = self._provenance(candidate.claim, snapshot)
                eligible.append(candidate)
                audit.append((candidate, "eligible", "+".join(sorted(candidate.methods)), "eligible"))
        anchors = self._subject_anchors(eligible, need)
        claim_token_frequency: dict[str, int] = {}
        for candidate in eligible:
            for token in self._claim_tokens(candidate.claim):
                claim_token_frequency[token] = claim_token_frequency.get(token, 0) + 1
        query_relevance_tokens = self._relevance_tokens(need.query)
        matched_candidate_count = sum(
            bool(self._matched_tokens(query_relevance_tokens, self._claim_tokens(candidate.claim)))
            for candidate in eligible
        )
        has_direct_need = bool(need.resources or need.target_candidates) or any(
            len(self._matched_tokens(query_relevance_tokens, self._claim_tokens(item.claim))) >= 2
            for item in eligible
        )
        relevant: list[_Candidate] = []
        for item in eligible:
            relevance = self._positive_relevance(
                item, need, anchors, allow_conversation_reference=not has_direct_need,
                claim_token_frequency=claim_token_frequency,
                matched_candidate_count=matched_candidate_count,
            )
            if relevance:
                item.reasons.add(relevance)
                relevant.append(item)
            else:
                audit.append((item, "rejected", "+".join(sorted(item.methods)), "no_positive_relevance"))
        if not relevant:
            # Broad-set recovery needs stable structural anchors. Very short
            # tokens dominate many languages but rarely identify a subject.
            informative_query = {
                token for token in _fts_query_tokens(need.query)
                if len(token) >= 4
            }
            query_vector = lexical_vector(need.query)
            fallback: list[tuple[_Candidate, float, set[str]]] = []
            anchor_frequency: dict[str, int] = {}
            for item in eligible:
                if "fts" not in item.methods:
                    continue
                claim_tokens = set(_tokens(str(item.claim.get("display_text") or "")))
                matches = self._bounded_term_matches(informative_query, claim_tokens)
                if matches:
                    similarity = max(0.0, cosine_similarity(
                        query_vector, lexical_vector(item.claim.get("display_text") or ""),
                    ))
                    fallback.append((item, similarity, matches))
                    for token in matches:
                        anchor_frequency[token] = anchor_frequency.get(token, 0) + 1
            qualified = [
                (item, similarity) for item, similarity, matches in fallback
                if similarity >= 0.05
                and any(anchor_frequency.get(token, 0) >= 3 for token in matches)
            ]
            if len(qualified) >= 3 and any(
                similarity >= 0.18 for _item, similarity in qualified
            ):
                for item, similarity in qualified:
                    item.score += similarity
                    item.reasons.add("bounded_semantic_set")
                    relevant.append(item)
        # A relevant slot brings along active competitors so a conflict cannot
        # disappear merely because one value matched the wording more closely.
        relevant_slots = {
            (item.claim["scope"], item.claim["slot_key"])
            for item in relevant if item.claim.get("slot_key")
        }
        for item in eligible:
            slot = (item.claim["scope"], item.claim.get("slot_key"))
            if item not in relevant and item.claim.get("slot_key") and slot in relevant_slots:
                item.reasons.add("relevant_slot_conflict")
                relevant.append(item)
        self._mark_conflicts(relevant)
        query_tokens = self._relevance_tokens(need.query)
        for item in relevant:
            text_tokens = self._claim_tokens(item.claim)
            overlap = self._overlap(query_tokens, text_tokens)
            exact = bool(item.reasons & {
                "required_exact_resource", "required_exact_binding", "required_exact_alias",
            })
            item.requirement = (
                "required" if exact or item.conflict
                else ("useful" if item.reasons & {
                    "subject_property_match", "subject_match", "conversation_reference",
                    "explicit_memory_match", "strong_lexical_match", "single_lexical_match",
                    "bounded_semantic_set",
                } else "optional")
            )
            item.score += (3 if item.requirement == "required" else 2 if item.requirement == "useful" else 1) + overlap
        relevant.sort(key=lambda x: (-x.score, x.claim["id"]))
        rendered, selected, token_count, overflow, projection_rejections = self._project(
            relevant, need, snapshot,
        )
        selected_ids = {x.claim["id"] for x in selected}
        for item in relevant:
            if item.claim["id"] in selected_ids:
                audit.append((item, "would_present", "+".join(sorted(item.methods)),
                              "+".join(sorted(item.reasons))))
            else:
                audit.append((item, "rejected", "+".join(sorted(item.methods)),
                              projection_rejections.get(item.claim["id"], "not_selected")))
        metrics = {
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "queue_wait_ms": round(max(0.0, started - queued_at_monotonic) * 1000, 3)
            if queued_at_monotonic is not None else 0,
            "effect": need.effect, "live_verification_required": need.live_verification_required,
            "provider_calls": 0, "llm_calls": 0, "visible_latency_added_ms": 0,
        }
        status = "would_present" if selected else "empty"
        if telemetry_operation is not None:
            selected_ordinals = {
                item.claim["id"]: ordinal for ordinal, item in enumerate(selected)
            }
            for item in candidates.values():
                method = "+".join(sorted(item.methods)) or "none"
                telemetry_operation.compiler_claim(
                    "claim_retrieved", item.claim["id"], method=method,
                    requirement=item.requirement,
                    token_cost=_token_count(item.claim["display_text"]),
                    rank_score=item.score,
                )
            for item in eligible:
                method = "+".join(sorted(item.methods)) or "none"
                telemetry_operation.compiler_claim(
                    "claim_eligible", item.claim["id"], method=method,
                    requirement=item.requirement,
                    token_cost=_token_count(item.claim["display_text"]),
                    rank_score=item.score,
                )
            for item in selected:
                method = "+".join(sorted(item.methods)) or "none"
                telemetry_operation.compiler_claim(
                    "claim_selected_for_view", item.claim["id"], method=method,
                    requirement=item.requirement,
                    token_cost=_token_count(item.claim["display_text"]),
                    rank_score=item.score,
                    ordinal=selected_ordinals[item.claim["id"]],
                )
            for ordinal, relation_id in enumerate(traversed_relation_ids):
                telemetry_operation.relation(relation_id, ordinal=ordinal)
        if not persist:
            return {
                "status": status, "consumer": need.consumer, "rendered_view": rendered,
                "token_budget": token_count, "token_count": token_count,
                "required_overflow": int(overflow), "candidate_count": len(candidates),
                "eligible_count": sum(1 for x in audit if x[1] == "eligible"),
                "presented_count": len(selected), "metrics": metrics,
                "claims": [{
                    **item.claim, "requirement": item.requirement,
                    "conflict": item.conflict, "provenance": list(item.provenance),
                    "reasons": sorted(item.reasons),
                } for item in selected],
                "candidate_audit": [{
                    "claim_id": item.claim["id"], "scope": item.claim["scope"],
                    "status": status, "methods": method, "reason": reason,
                } for item, status, method, reason in audit],
            }
        return self._persist(snapshot, need, list(candidates.values()), audit, status, rendered,
                             token_count, overflow, metrics)

    @staticmethod
    def _relevance_tokens(text: str) -> set[str]:
        return set(_tokens(text))

    @classmethod
    def _claim_tokens(cls, claim: dict) -> set[str]:
        payload = json.loads(claim.get("payload_json") or "{}")
        relevant_payload = " ".join(str(payload.get(key) or "") for key in (
            "subject", "property", "external_reference", "legacy_memory_key",
        ))
        canonical = str(claim.get("canonical_key") or "")
        if canonical.startswith("legacy:"):
            canonical = ""
        return cls._relevance_tokens(" ".join((
            str(claim.get("display_text") or ""), canonical,
            str(claim.get("slot_key") or ""), relevant_payload,
        )))

    @staticmethod
    def _token_matches(left: str, right: str) -> bool:
        if left == right:
            return True
        if any(char.isdigit() for char in left + right):
            return False
        if min(len(left), len(right)) >= 7 and (left in right or right in left):
            return True
        # A shared word beginning is not evidence of the same term or resource:
        # "eingeladen" and "eingesteckt" must not establish a device identity.
        return False

    @classmethod
    def _matched_tokens(cls, left: set[str], right: set[str]) -> set[str]:
        return {a for a in left if any(cls._token_matches(a, b) for b in right)}

    @classmethod
    def _overlap(cls, left: set[str], right: set[str]) -> float:
        return len(cls._matched_tokens(left, right)) / max(1, len(left))

    @staticmethod
    def _surface_matches(left: set[str], right: set[str]) -> set[str]:
        """Match conservative whole-token stems only after FTS bounds the pool."""
        return {
            token for token in left
            if len(token) >= 4 and any(
                token == other
                or min(len(token), len(other)) >= 4
                and (token.startswith(other) or other.startswith(token))
                for other in right
            )
        }

    @classmethod
    def _bounded_term_matches(cls, query: set[str], claim: set[str]) -> set[str]:
        """Return conservative query anchors for broad semantic-set recovery."""
        return {
            query_token for query_token in query
            if any(
                query_token == claim_token
                or (
                    min(len(query_token), len(claim_token)) >= 4
                    and abs(len(query_token) - len(claim_token)) <= 2
                    and (query_token.startswith(claim_token) or claim_token.startswith(query_token))
                )
                or (
                    min(len(query_token), len(claim_token)) >= 7
                    and (query_token in claim_token or claim_token in query_token)
                )
                for claim_token in claim
            )
        }

    @staticmethod
    def _fts_expression(tokens: list[str]) -> str:
        terms = []
        for token in tokens:
            clean = token.replace('"', "")
            terms.append(f'"{clean}"')
            if len(clean) >= 6:
                terms.append(f'"{clean[:4]}"*')
        return " OR ".join(dict.fromkeys(terms))

    @classmethod
    def _subject_anchors(cls, eligible: list[_Candidate], need: MemoryNeed) -> list[set[str]]:
        query = cls._relevance_tokens(need.query)
        reference = cls._relevance_tokens(need.reference_text)
        anchors = []
        for item in eligible:
            if item.claim["claim_kind"] != "provider_binding":
                continue
            payload = json.loads(item.claim.get("payload_json") or "{}")
            subject = cls._relevance_tokens(str(payload.get("subject") or ""))
            if subject and (cls._matched_tokens(subject, query) or cls._matched_tokens(subject, reference)):
                anchors.append(subject)
        return anchors

    @classmethod
    def _positive_relevance(cls, item: _Candidate, need: MemoryNeed,
                            anchors: list[set[str]], *,
                            allow_conversation_reference: bool = True,
                            claim_token_frequency: dict[str, int] | None = None,
                            matched_candidate_count: int | None = None) -> str | None:
        claim = item.claim
        payload = json.loads(claim.get("payload_json") or "{}")
        reference = str(payload.get("external_reference") or "")
        if reference and (reference in need.resources or reference in need.target_candidates):
            return "required_exact_resource"
        if reference and reference.casefold() in need.query.casefold():
            return "required_exact_binding"

        query = cls._relevance_tokens(need.query)
        reference_tokens = cls._relevance_tokens(need.reference_text)
        context_tokens = cls._relevance_tokens(need.conversation_text)
        claim_tokens = cls._claim_tokens(claim)
        direct = cls._matched_tokens(query, claim_tokens)

        if claim["claim_kind"] == "alias":
            alias_tokens = cls._relevance_tokens(str(payload.get("alias") or ""))
            target_tokens = cls._relevance_tokens(str(payload.get("target") or ""))
            direct_alias = cls._matched_tokens(alias_tokens, query | reference_tokens)
            if alias_tokens and len(direct_alias) == len(alias_tokens):
                return "required_exact_alias"
            contextual_alias = cls._matched_tokens(alias_tokens, context_tokens)
            if (allow_conversation_reference and need.provider and alias_tokens
                    and len(contextual_alias) == len(alias_tokens)
                    and cls._matched_tokens(target_tokens, query | reference_tokens)):
                return "conversation_reference"
            return None

        if claim["claim_kind"] == "provider_binding":
            subject = cls._relevance_tokens(str(payload.get("subject") or ""))
            prop = cls._relevance_tokens(str(payload.get("property") or ""))
            subject_match = cls._matched_tokens(subject, query | reference_tokens)
            property_match = cls._matched_tokens(prop, query | reference_tokens)
            distinctive = {
                token for token in subject
                if sum(any(cls._token_matches(token, other) for other in anchor)
                       for anchor in anchors) == 1
            }
            if distinctive and not cls._matched_tokens(distinctive, query | reference_tokens):
                return None
            if subject and len(subject_match) / len(subject) >= 0.5:
                if property_match or str(payload.get("property") or "").casefold() == "resource":
                    return "required_exact_binding"
                return "subject_match"
            contextual_subject = cls._matched_tokens(subject, context_tokens)
            if (allow_conversation_reference and need.provider and subject
                    and len(contextual_subject) / len(subject) >= 0.5):
                return "conversation_reference"
            if need.provider and not query and reference_tokens and subject_match:
                return "subject_match"
            return None

        if need.resources:
            return (
                "subject_property_match"
                if any(resource.casefold() in str(claim.get("display_text") or "").casefold()
                       for resource in need.resources)
                else None
            )

        if need.consumer in {"planner", "native_tool"} and claim["claim_kind"] == "opaque_fact" and not (
            need.provider or need.resources or need.target_candidates
        ):
            return None

        # A binding constrains a provider lookup, not the subjects of ordinary
        # statements. Even an exact device name can also occur in a general
        # question (e.g. an integration named after its provider).
        if anchors and (need.provider or payload.get("provider")):
            best_anchor = max(anchors, key=lambda anchor: len(cls._matched_tokens(anchor, claim_tokens)))
            anchor_match = cls._matched_tokens(best_anchor, claim_tokens)
            # Once a structured subject is known, thematic neighbours and
            # partial-room matches are not positive relevance.
            if best_anchor and len(anchor_match) == len(best_anchor) and direct:
                return "subject_property_match"
            return None

        display_tokens = cls._relevance_tokens(str(claim.get("display_text") or ""))
        display_matches = cls._matched_tokens(query, display_tokens)
        claim_coverage = len(display_matches) / max(1, len(display_tokens))
        # FTS already bounds this pool. Two exact or conservatively inflected
        # anchors are enough even when the stored statement is a full sentence;
        # requiring a quarter of every sentence made phrasing length behave
        # like a language-specific stop-word list.
        # A complete match of the query in the displayed statement must not
        # disappear merely because that statement contains more words. Keep
        # the coverage guard for partial matches, including generic wording.
        complete_display_match = bool(query) and len(display_matches) == len(query)
        # A deliberate one-term lookup may have several true mentions. Corpus
        # frequency cannot make all of them irrelevant; ranking/pagination
        # handles a broad result set without asserting that names are identities.
        if len(query) == 1 and complete_display_match:
            return "explicit_memory_match" if need.general_memory_needed else "single_lexical_match"
        if (len(direct) >= 2 and cls._overlap(query, claim_tokens) >= 0.3
                and (claim_coverage >= 0.15 or complete_display_match)):
            return "explicit_memory_match" if need.general_memory_needed else "strong_lexical_match"
        if len(direct) == 1:
            matched = next(iter(direct))
            precise = any(
                matched == token
                or min(len(matched), len(token)) >= 7
                and (matched in token or token in matched)
                for token in claim_tokens
            )
            frequency = sum(
                count for token, count in (claim_token_frequency or {}).items()
                if cls._token_matches(matched, token)
            )
            if (precise and len(matched) >= 6 and frequency <= 1
                    and (matched_candidate_count is None or matched_candidate_count == 1)):
                return "explicit_memory_match" if need.general_memory_needed else "single_lexical_match"
        if len(query) == 1 and direct and not need.provider and not need.conversation_text:
            return "weak_entity_match"

        # Opaque facts are never recovered solely from fuzzy conversation
        # overlap. Conversation references require a structured binding/alias.
        return None

    def _retrieve(self, need: MemoryNeed) -> dict[str, _Candidate]:
        """Compatibility surface for diagnostics that inspect candidates only."""
        return self._retrieve_with_relations(need)[0]

    def _retrieve_with_relations(
        self, need: MemoryNeed,
    ) -> tuple[dict[str, _Candidate], list[str]]:
        # Action experiences are consumed exclusively by the exact lookup.
        need = replace(need, scopes=tuple(scope for scope in need.scopes if scope not in {
            "semantic_links", "semantic_actions", "semantic_similarity_relations",
        }))
        retrieval_text = " ".join(filter(None, (
            need.query, need.reference_text,
            need.conversation_text if need.provider else "",
        )))
        tokens = _fts_query_tokens(retrieval_text)
        candidates: dict[str, _Candidate] = {}
        traversed_relation_ids: list[str] = []
        with self.database.connect() as connection:
            scope_placeholders = ",".join("?" for _ in need.scopes) or "''"
            structured_values = list(need.resources) + list(need.target_candidates)
            for value in structured_values:
                rows = connection.execute(
                    f"""SELECT * FROM memory_claims WHERE scope IN ({scope_placeholders}) AND
                       (canonical_key=? OR slot_key=? OR json_extract(payload_json,'$.external_reference')=?)""",
                    (*need.scopes, value, value, value),
                ).fetchall()
                for row in rows:
                    candidates.setdefault(row["id"], _Candidate(dict(row))).methods.add("resource")
            if self.config["retrieval_mode"] != "structured_only" and tokens:
                expression = self._fts_expression(tokens)
                try:
                    rows = connection.execute(
                        f"""SELECT c.*,bm25(memory_claims_fts) AS fts_rank FROM memory_claims_fts
                           JOIN memory_claims c ON c.id=memory_claims_fts.claim_id
                           WHERE memory_claims_fts MATCH ? AND c.scope IN ({scope_placeholders})
                           ORDER BY fts_rank""",
                        (expression, *need.scopes),
                    ).fetchall()
                except Exception:
                    # Bounded degradation for installations where the derived
                    # index is temporarily unavailable; never a Python scan.
                    clauses = " OR ".join("lower(display_text) LIKE ?" for _ in tokens)
                    rows = connection.execute(
                        f"SELECT * FROM memory_claims WHERE scope IN ({scope_placeholders}) AND ({clauses}) "
                        "ORDER BY updated_at DESC,id",
                        (*need.scopes, *[f"%{token}%" for token in tokens]),
                    ).fetchall()
                for row in rows:
                    method = "fts" if "fts_rank" in row.keys() else "bounded_like_fallback"
                    item = candidates.setdefault(row["id"], _Candidate(dict(row)))
                    item.methods.add(method)
                    if method == "fts":
                        item.score = max(item.score, min(2.0, max(0.0, -float(row["fts_rank"]))))
            # A provider filter describes the namespace to search; it is not a
            # relevance signal by itself.  Filling the bounded pool with the
            # first arbitrary provider rows before FTS made dense inventories
            # hide the requested entity.  Only use the broad provider set when
            # there is no textual or structured lookup key at all.
            if need.provider and not tokens and not structured_values:
                rows = connection.execute(
                    f"""SELECT * FROM memory_claims WHERE scope IN ({scope_placeholders})
                       AND claim_kind='provider_binding' AND json_extract(payload_json,'$.provider')=?
                       ORDER BY updated_at DESC,id""",
                    (*need.scopes, need.provider)
                ).fetchall()
                for row in rows:
                    candidates.setdefault(row["id"], _Candidate(dict(row))).methods.add("provider")
            # Follow the complete finite relation component. UNION removes
            # already visited claim IDs, so cycles terminate without a hop cap.
            if candidates:
                source_ids = list(candidates)
                source_json = json.dumps(source_ids)
                related = connection.execute(
                    """SELECT 1 FROM memory_relations r
                       WHERE r.relation_type IN ('supersedes','contradicts','refines')
                         AND (r.from_claim_id IN (SELECT value FROM json_each(?))
                              OR r.to_claim_id IN (SELECT value FROM json_each(?)))
                       LIMIT 1""",
                    (source_json, source_json),
                ).fetchone()
                relation_claims = []
                if related is not None:
                    relation_claims = connection.execute(
                        f"""WITH RECURSIVE graph(claim_id) AS (
                           SELECT value FROM json_each(?)
                           UNION
                           SELECT r.to_claim_id FROM graph g JOIN memory_relations r
                             ON r.from_claim_id=g.claim_id
                           WHERE r.relation_type IN ('supersedes','contradicts','refines')
                           UNION
                           SELECT r.from_claim_id FROM graph g JOIN memory_relations r
                             ON r.to_claim_id=g.claim_id
                           WHERE r.relation_type IN ('supersedes','contradicts','refines')
                         )
                         SELECT c.*
                         FROM graph g JOIN memory_claims c ON c.id=g.claim_id
                         WHERE c.scope IN ({scope_placeholders})""",
                        (source_json, *need.scopes),
                    ).fetchall()
                for row in relation_claims:
                    claim = dict(row)
                    item = candidates.setdefault(claim["id"], _Candidate(claim))
                    item.methods.add("relation")
                if relation_claims:
                    connected_json = json.dumps(list(candidates))
                    relation_rows = connection.execute(
                        """SELECT id,from_claim_id,to_claim_id FROM memory_relations
                           WHERE relation_type IN ('supersedes','contradicts','refines')
                             AND from_claim_id IN (SELECT value FROM json_each(?))
                             AND to_claim_id IN (SELECT value FROM json_each(?))""",
                        (connected_json, connected_json),
                    ).fetchall()
                    for relation in relation_rows:
                        relation_id = str(relation["id"])
                        traversed_relation_ids.append(relation_id)
                        for endpoint in (relation["from_claim_id"], relation["to_claim_id"]):
                            if endpoint in candidates:
                                candidates[endpoint].relation_ids.add(relation_id)
        return candidates, list(dict.fromkeys(traversed_relation_ids))

    @staticmethod
    def _eligibility(claim: dict, need: MemoryNeed, at: str) -> str | None:
        lifecycle = claim["lifecycle"]
        at_time = MemoryCompiler._instant(at)
        valid_from = MemoryCompiler._instant(claim.get("valid_from"))
        valid_until = MemoryCompiler._instant(claim.get("valid_until"))
        if claim["scope"] not in need.scopes:
            return "scope_mismatch"
        if lifecycle == "invalid":
            return None if need.audit else "invalid_audit_only"
        valid_at_turn = (
            valid_until is not None
            and (valid_from is None or at_time is None or at_time >= valid_from)
            and (valid_until is None or at_time is None or at_time < valid_until)
        )
        if lifecycle == "retired" and not (need.historical or need.audit or valid_at_turn):
            return "retired_not_current"
        if lifecycle == "candidate" and not need.audit:
            return "candidate_not_confirmed"
        if valid_from is not None and at_time is not None and at_time < valid_from and not need.historical:
            return "not_yet_valid"
        if valid_until is not None and at_time is not None and at_time >= valid_until and not (need.historical or need.audit):
            return "expired"
        return None

    @staticmethod
    def _instant(value) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _mark_conflicts(items: list[_Candidate]) -> None:
        slots: dict[tuple[str, str], list[_Candidate]] = {}
        for item in items:
            if item.claim.get("slot_key") and item.claim["lifecycle"] == "active":
                slots.setdefault((item.claim["scope"], item.claim["slot_key"]), []).append(item)
        for group in slots.values():
            if len(group) > 1:
                for item in group:
                    item.conflict = True

    def _provenance(self, claim: dict, snapshot: dict) -> list[str]:
        provenance = []
        payload = json.loads(claim.get("payload_json") or "{}")
        if payload.get("runtime_self_knowledge") is True:
            provenance.append("runtime_declared")
        if claim["canonical_key"].startswith("legacy:"):
            provenance.append("legacy_import")
        if claim["lifecycle"] == "candidate":
            provenance.append("model_candidate")
        reference = str(payload.get("external_reference") or "")
        verified = False
        if reference:
            for tool in snapshot["tools"]:
                if tool["status"] == "completed" and self._property_observed(
                    tool["result"], str(payload.get("property") or ""), reference,
                ):
                    verified = True
                    break
            provenance.append("provider_verified" if verified else "stored_not_live_verified")
        if not provenance:
            provenance.append("user_stated")
        return provenance

    @staticmethod
    def _property_observed(value, property_name: str, reference: str) -> bool:
        if isinstance(value, dict):
            flat_values = {str(item) for item in value.values() if not isinstance(item, (dict, list))}
            has_reference = reference in flat_values
            if has_reference and property_name in {
                "existence", "resource", "resource_exists", "entity_id", "external_reference",
            }:
                return True
            if has_reference and property_name and property_name in value:
                return True
            return any(MemoryCompiler._property_observed(item, property_name, reference)
                       for item in value.values() if isinstance(item, (dict, list)))
        if isinstance(value, list):
            return any(MemoryCompiler._property_observed(item, property_name, reference) for item in value)
        return False

    @classmethod
    def _coverage_order(cls, items: list[_Candidate], need: MemoryNeed) -> list[_Candidate]:
        """Order relevant claims by relevance and marginal textual information."""
        required = [item for item in items if item.requirement == "required"]
        remaining = [item for item in items if item.requirement != "required"]
        if not remaining:
            return required

        low = min(item.score for item in remaining)
        high = max(item.score for item in remaining)
        span = high - low
        query_tokens = cls._relevance_tokens(need.query)
        selected_tokens = [cls._claim_tokens(item.claim) for item in required]
        token_sets = {item.claim["id"]: cls._claim_tokens(item.claim) for item in remaining}
        query_matches = {
            item.claim["id"]: cls._matched_tokens(query_tokens, token_sets[item.claim["id"]])
            for item in remaining
        }
        redundancy = {
            item.claim["id"]: max(
                (cls._content_overlap(token_sets[item.claim["id"]], prior)
                 for prior in selected_tokens),
                default=0.0,
            )
            for item in remaining
        }
        covered_query = set().union(*(
            cls._matched_tokens(query_tokens, tokens) for tokens in selected_tokens
        )) if selected_tokens else set()
        ordered = list(required)

        while remaining:
            ranked = []
            for item in remaining:
                identifier = item.claim["id"]
                tokens = token_sets[identifier]
                normalized = (item.score - low) / span if span > 0 else 1.0
                relevance = 0.8 + 0.2 * normalized
                matched_query = query_matches[identifier]
                query_gain = len(matched_query - covered_query) / max(1, len(query_tokens))
                utility = (
                    0.65 * relevance
                    + 0.25 * (1.0 - redundancy[identifier])
                    + 0.10 * query_gain
                )
                token_cost = _token_count(str(item.claim.get("display_text") or ""))
                density = utility / max(1.0, token_cost ** 0.5)
                ranked.append((density, utility, item.score, item.claim["id"],
                               item, tokens, matched_query))
            (_density, _utility, _score, _identifier,
             winner, tokens, matched_query) = sorted(
                ranked, key=lambda row: (-row[0], -row[1], -row[2], row[3]),
            )[0]
            ordered.append(winner)
            selected_tokens.append(tokens)
            covered_query.update(matched_query)
            remaining.remove(winner)
            for item in remaining:
                identifier = item.claim["id"]
                redundancy[identifier] = max(
                    redundancy[identifier],
                    cls._content_overlap(token_sets[identifier], tokens),
                )
        return ordered

    @classmethod
    def _content_overlap(cls, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        matched_left = cls._matched_tokens(left, right)
        matched_right = cls._matched_tokens(right, left)
        intersection = max(len(matched_left), len(matched_right))
        return intersection / max(1, len(left) + len(right) - intersection)

    def _project(self, items: list[_Candidate], need: MemoryNeed, snapshot: dict):
        selected: list[_Candidate] = []
        lines = [f"memory_view consumer={need.consumer} effect={need.effect}"]
        seen: set[tuple[str, str]] = set()
        seen_references: set[str] = set()
        rejected: dict[str, str] = {}
        overflow = False
        for item in self._coverage_order(items, need):
            claim = item.claim
            fingerprint = (claim["slot_key"] or "", claim["display_text"].casefold())
            if fingerprint in seen and not item.conflict:
                rejected[claim["id"]] = "duplicate_content"
                continue
            seen.add(fingerprint)
            marker = []
            if item.conflict:
                marker.append("conflicted")
            if claim["lifecycle"] != "active":
                marker.append(claim["lifecycle"])
            marker.extend(item.provenance)
            payload = json.loads(claim.get("payload_json") or "{}")
            external_reference = str(payload.get("external_reference") or "")
            if external_reference:
                if external_reference in seen_references:
                    rejected[claim["id"]] = "duplicate_reference"
                    continue
                seen_references.add(external_reference)
            elif any(reference and reference in claim["display_text"] for reference in seen_references):
                rejected[claim["id"]] = "duplicate_reference"
                continue
            detail = claim["display_text"]
            if claim["claim_kind"] == "provider_binding":
                detail = " | ".join(filter(None, (
                    str(payload.get("subject") or ""), str(payload.get("property") or ""),
                    str(payload.get("external_reference") or ""),
                ))) or detail
            line = f"- [{item.requirement};{','.join(marker)}] {detail}"
            lines.append(line)
            selected.append(item)
        rendered = "\n".join(lines) if selected else ""
        return rendered, selected, _token_count(rendered) if rendered else 0, overflow, rejected

    def _persist(self, snapshot: dict, need: MemoryNeed, candidates: list[_Candidate], audit: list,
                 status: str, rendered: str, token_count: int, overflow: bool, metrics: dict) -> dict:
        audit_started = time.perf_counter()
        budget = token_count
        config_snapshot = _stable_hash({"config": self.config, "need": need.__dict__})
        identity = ":".join((snapshot["turn_id"], need.consumer, COMPILER_VERSION,
                             snapshot["claim_snapshot"], config_snapshot))
        evaluation_id = str(uuid.uuid5(_NAMESPACE, identity))
        legacy_tokens = 0
        overlap = 0
        with self.database.connect() as connection:
            inserted = connection.execute(
                """INSERT OR IGNORE INTO memory_compiler_evaluations
                   (id,turn_id,consumer,compiler_version,retrieval_version,eligibility_version,
                    projection_version,budget_version,claim_snapshot,config_snapshot,status,
                    token_budget,token_count,token_method,required_overflow,candidate_count,
                    eligible_count,presented_count,legacy_count,legacy_token_count,
                    legacy_overlap_count,rendered_view,metrics_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (evaluation_id, snapshot["turn_id"], need.consumer, COMPILER_VERSION,
                 RETRIEVAL_VERSION, ELIGIBILITY_VERSION, PROJECTION_VERSION, BUDGET_VERSION,
                 snapshot["claim_snapshot"], config_snapshot, status, budget, token_count,
                 "utf8_bytes_div_3_conservative", int(overflow), len(candidates),
                 sum(1 for x in audit if x[1] == "eligible"),
                 sum(1 for x in audit if x[1] == "would_present"), 0,
                 legacy_tokens, overlap, rendered, json.dumps(metrics, ensure_ascii=False), _now()),
            )
            for item, stage, method, reason in audit:
                connection.execute(
                    """INSERT OR IGNORE INTO memory_compiler_claim_audit
                       (evaluation_id,claim_id,stage,method,reason,requirement_class,token_cost,rank_score)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (evaluation_id, item.claim["id"], stage, method or "none", reason,
                     item.requirement, _token_count(item.claim["display_text"]), item.score),
                )
                if stage == "would_present" and need.consumer in {"planner", "native_tool", "answer"}:
                    connection.execute(
                        """INSERT OR IGNORE INTO memory_compiler_usage
                           (turn_id,consumer,claim_id,usage,created_at)
                           VALUES (?,?,?,'presented',?)""",
                        (snapshot["turn_id"], need.consumer, item.claim["id"], _now()),
                    )
            if inserted.rowcount:
                metrics["audit_write_ms"] = round((time.perf_counter() - audit_started) * 1000, 3)
                connection.execute(
                    "UPDATE memory_compiler_evaluations SET metrics_json=? WHERE id=?",
                    (json.dumps(metrics, ensure_ascii=False), evaluation_id),
                )
            row = connection.execute(
                "SELECT * FROM memory_compiler_evaluations WHERE id=?", (evaluation_id,)
            ).fetchone()
        result = dict(row)
        result["metrics"] = json.loads(result.pop("metrics_json"))
        return result

    def report(self, *, turn_id: str | None = None) -> dict:
        where = " WHERE compiler_version=?"
        values: tuple = (COMPILER_VERSION,)
        if turn_id:
            where += " AND turn_id=?"
            values += (str(turn_id),)
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memory_compiler_evaluations" + where + " ORDER BY created_at,id", values
            ).fetchall()
        return {
            "compiler_version": COMPILER_VERSION,
            "evaluations": [dict(row) for row in rows],
            "summary": {
                "evaluation_count": len(rows),
                "would_present": sum(row["presented_count"] for row in rows),
                "required_overflows": sum(row["required_overflow"] for row in rows),
                "provider_calls": 0, "llm_calls": 0,
            },
        }

    def _diagnostic(self, exc: Exception, turn_id: str) -> None:
        if self.diagnostics:
            try:
                self.diagnostics.record("memory_compiler", "compile", "error",
                                        "Memory-v2-Compilation fehlgeschlagen",
                                        exception=exc, correlation=str(turn_id))
            except Exception:
                pass
