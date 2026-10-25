from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .storage import _RUNTIME_SELF_KNOWLEDGE_WRITER
from .memory_lifecycle import lifecycle_operation


_NAMESPACE = uuid.UUID("a83ed154-8934-4bdf-a8dd-f65764234349")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(kind: str, *parts: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, "|".join((kind, *parts))))


def _fingerprint(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class RuntimeSelfDescription:
    runtime_id: str
    capability_id: str
    statement: str
    component: str
    operation: str

    def normalized(self) -> "RuntimeSelfDescription":
        values = [str(value).strip() for value in (
            self.runtime_id, self.capability_id, self.statement, self.component, self.operation,
        )]
        if not all(values) or len(values[2]) > 1000:
            raise ValueError("Ungültige Runtime-Self-Description")
        return RuntimeSelfDescription(*values)


def collect_runtime_self_descriptions(runtime) -> list[RuntimeSelfDescription]:
    """Inspect the actually assembled runtime; components describe only themselves."""
    objects, seen = [runtime], set()
    objects.extend(vars(runtime).values())
    descriptions = []
    for component in objects:
        if component is None or id(component) in seen:
            continue
        seen.add(id(component))
        provider = getattr(component, "self_descriptions", None)
        if not callable(provider):
            continue
        for item in provider():
            if not isinstance(item, RuntimeSelfDescription):
                raise TypeError("Self-Descriptions müssen RuntimeSelfDescription verwenden")
            descriptions.append(item.normalized())
    return sorted(descriptions, key=lambda item: (item.capability_id, item.runtime_id))


class RuntimeSelfKnowledgeSync:
    SCOPE = "provider:runtime"

    def __init__(self, database, diagnostics=None):
        self.database, self.diagnostics = database, diagnostics

    @lifecycle_operation("memory.runtime_self_knowledge", "runtime_self_knowledge_sync")
    def sync(self, descriptions: list[RuntimeSelfDescription]) -> dict:
        normalized = [item.normalized() for item in descriptions]
        by_runtime = {item.runtime_id: item for item in normalized}
        if len(by_runtime) != len(normalized):
            raise ValueError("Runtime-Self-Description-IDs müssen eindeutig sein")
        grouped: dict[str, list[RuntimeSelfDescription]] = {}
        for item in normalized:
            grouped.setdefault(item.capability_id, []).append(item)
        for capability_id, items in grouped.items():
            if len({item.statement for item in items}) != 1:
                raise ValueError(f"Widersprüchliche Self-Descriptions für {capability_id}")

        result = {"descriptions": len(normalized), "created": 0, "unchanged": 0,
                  "superseded": 0, "unsupported": 0, "warnings": []}
        now = _now()
        with self.database.connect() as connection:
            self.database.assert_runtime_self_knowledge_writable(
                connection, writer=_RUNTIME_SELF_KNOWLEDGE_WRITER,
            )
            active_rows = connection.execute(
                """SELECT * FROM memory_claims WHERE scope=? AND lifecycle='active'
                   AND json_extract(payload_json,'$.runtime_self_knowledge')=1""",
                (self.SCOPE,),
            ).fetchall()
            active_by_capability = {
                json.loads(row["payload_json"])["capability_id"]: row for row in active_rows
            }
            for capability_id, items in sorted(grouped.items()):
                statement = items[0].statement
                sources = [{
                    "runtime_id": item.runtime_id, "component": item.component,
                    "operation": item.operation,
                    "fingerprint": _fingerprint({
                        "statement": item.statement, "component": item.component,
                        "operation": item.operation,
                    }),
                } for item in sorted(items, key=lambda value: value.runtime_id)]
                semantic_fingerprint = _fingerprint({"capability_id": capability_id, "statement": statement})
                current = active_by_capability.get(capability_id)
                if current is not None and current["display_text"] == statement:
                    payload = json.loads(current["payload_json"])
                    payload["sources"] = sources
                    payload["runtime_fingerprint"] = semantic_fingerprint
                    encoded_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                    if encoded_payload != current["payload_json"]:
                        connection.execute(
                            "UPDATE memory_claims SET payload_json=?,updated_at=? WHERE id=?",
                            (encoded_payload, now, current["id"]),
                        )
                    claim_id = current["id"]
                    result["unchanged"] += 1
                else:
                    claim_id = _id("claim", capability_id, semantic_fingerprint)
                    payload = {"runtime_self_knowledge": True, "capability_id": capability_id,
                               "runtime_fingerprint": semantic_fingerprint, "sources": sources}
                    connection.execute(
                        """INSERT OR IGNORE INTO memory_claims
                           (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,
                            lifecycle,valid_from,verification_policy,created_at,updated_at)
                           VALUES (?,'opaque_fact',?,?,?,?,?,'active',?,'configuration',?,?)""",
                        (claim_id, self.SCOPE, f"v2:runtime-self:{capability_id}:{semantic_fingerprint[:16]}",
                         f"runtime-self:{capability_id}", statement,
                         json.dumps(payload, ensure_ascii=False, sort_keys=True), now, now, now),
                    )
                    connection.execute(
                        """UPDATE memory_claims SET display_text=?,payload_json=?,lifecycle='active',
                           valid_until=NULL,updated_at=? WHERE id=?""",
                        (statement, json.dumps(payload, ensure_ascii=False, sort_keys=True), now, claim_id),
                    )
                    if current is not None:
                        connection.execute(
                            "UPDATE memory_claims SET lifecycle='retired',valid_until=?,updated_at=? WHERE id=?",
                            (now, now, current["id"]),
                        )
                        connection.execute(
                            """INSERT OR IGNORE INTO memory_relations
                               (id,from_claim_id,to_claim_id,relation_type,created_at)
                               VALUES (?,?,?,'supersedes',?)""",
                            (_id("relation", claim_id, current["id"]), claim_id, current["id"], now),
                        )
                        result["superseded"] += 1
                    else:
                        result["created"] += 1
                self._sync_sources(connection, claim_id, capability_id, statement, sources, now)

            current_capabilities = set(grouped)
            for capability_id, row in active_by_capability.items():
                if capability_id in current_capabilities:
                    continue
                connection.execute(
                    "UPDATE memory_claims SET lifecycle='retired',valid_until=?,updated_at=? WHERE id=?",
                    (now, now, row["id"]),
                )
                connection.execute(
                    "UPDATE memory_evidence SET effective_until=? WHERE claim_id=? AND effective_until IS NULL",
                    (now, row["id"]),
                )
                result["unsupported"] += 1
        if self.diagnostics:
            self.diagnostics.record(
                "runtime_self_knowledge", "sync", "ok",
                "Runtime-Self-Knowledge synchronisiert: "
                f"{result['descriptions']} Quellen, {result['created']} neu, "
                f"{result['unchanged']} unverändert, {result['superseded']} ersetzt, "
                f"{result['unsupported']} entfernt, {len(result['warnings'])} Warnungen",
            )
        return result

    @staticmethod
    def _sync_sources(connection, claim_id: str, capability_id: str, statement: str,
                      sources: list[dict], now: str) -> None:
        current_sources = {
            (source["runtime_id"], source["fingerprint"]) for source in sources
        }
        existing = connection.execute(
            """SELECT id,source_ref,payload_json FROM memory_evidence
               WHERE claim_id=? AND evidence_type='runtime_self_knowledge'""",
            (claim_id,),
        ).fetchall()
        for row in existing:
            payload = json.loads(row["payload_json"] or "{}")
            if (row["source_ref"], payload.get("fingerprint")) not in current_sources:
                connection.execute(
                    "UPDATE memory_evidence SET effective_until=? WHERE id=? AND effective_until IS NULL",
                    (now, row["id"]),
                )
        for source in sources:
            observation_id = _id("observation", source["runtime_id"], source["fingerprint"])
            connection.execute(
                """INSERT OR IGNORE INTO memory_observations
                   (id,source_role,source_type,external_ref,excerpt,structured_value_json,
                    observed_at,scope,metadata_json,created_at)
                   VALUES (?,'provider','provider_result',?,?,?,?,?,?,?)""",
                (observation_id, source["runtime_id"], statement,
                 json.dumps(source, ensure_ascii=False, sort_keys=True), now,
                 RuntimeSelfKnowledgeSync.SCOPE,
                 json.dumps({"runtime_self_knowledge": True, "capability_id": capability_id}), now),
            )
            evidence_id = _id("evidence", claim_id, observation_id)
            connection.execute(
                """INSERT OR IGNORE INTO memory_evidence
                   (id,claim_id,observation_id,stance,evidence_type,source_ref,excerpt,payload_json,
                    observed_at,effective_from,created_at)
                   VALUES (?,?,?,'supports','runtime_self_knowledge',?,?,?,?,?,?)""",
                (evidence_id, claim_id, observation_id, source["runtime_id"], statement,
                 json.dumps(source, ensure_ascii=False, sort_keys=True), now, now, now),
            )
            connection.execute(
                "UPDATE memory_evidence SET effective_until=NULL WHERE id=?",
                (evidence_id,),
            )
