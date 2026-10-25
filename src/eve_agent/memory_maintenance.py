from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone


ANALYZER_VERSION = "memory-maintenance-v2"
_PRODUCT_TABLES = (
    "memory_claims", "memory_observations", "memory_evidence", "memory_relations",
    "memory_learning_decisions", "memory_learning_decision_claims", "memory_legacy_mappings",
    "memory_compiler_usage", "memory_learning_jobs",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=lambda item: {"blob_sha256": hashlib.sha256(bytes(item)).hexdigest()}
        if isinstance(item, (bytes, bytearray, memoryview)) else str(item),
    )


def _decode(row) -> dict:
    item = dict(row)
    for key in tuple(item):
        if key.endswith("_json") and isinstance(item[key], str):
            try:
                item[key.removesuffix("_json")] = json.loads(item.pop(key))
            except ValueError:
                pass
    return item


class MemoryMaintenance:
    """Explainable Memory-v2 audits whose only writes target maintenance tables."""

    def __init__(self, database, *, analysis_hook=None):
        self.database = database
        self.analysis_hook = analysis_hook

    def start(self) -> dict:
        started = time.perf_counter()
        started_at = _now()
        run_id = str(uuid.uuid4())
        snapshot_hash = self.product_digest()
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_maintenance_runs
                   (id,status,snapshot_hash,analyzer_version,started_at)
                   VALUES (?,'running',?,?,?)""",
                (run_id, snapshot_hash, ANALYZER_VERSION, started_at),
            )
        try:
            snapshot = self._snapshot()
            findings, warnings = self._analyze(snapshot)
            if self.analysis_hook is not None:
                self.analysis_hook(snapshot, findings)
            after_hash = self.product_digest()
            if after_hash != snapshot_hash:
                raise RuntimeError("productive_memory_changed_during_audit")
            completed_at = _now()
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            counts = self._persist_findings(run_id, findings, completed_at)
            summary = {
                "by_problem_class": dict(sorted(Counter(item["problem_class"] for item in findings).items())),
                "by_confidence": dict(sorted(Counter(item["confidence"] for item in findings).items())),
                "dry_run": True,
                "productive_snapshot_unchanged": True,
                "distinct_findings_total": counts["distinct_findings_total"],
            }
            with self.database.connect() as connection:
                connection.execute(
                    """UPDATE memory_maintenance_runs SET status='completed',completed_at=?,duration_ms=?,
                       active_claims=?,historical_claims=?,relations_checked=?,finding_count=?,
                       summary_json=?,warnings_json=? WHERE id=?""",
                    (completed_at, duration_ms, snapshot["active_claims"], snapshot["historical_claims"],
                     len(snapshot["relations"]), len(findings), _json(summary), _json(warnings), run_id),
                )
            return self.run(run_id)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            with self.database.connect() as connection:
                connection.execute(
                    """UPDATE memory_maintenance_runs SET status='failed',completed_at=?,duration_ms=?,
                       error_class=?,warnings_json=? WHERE id=?""",
                    (_now(), duration_ms, type(exc).__name__, _json([str(exc)[:240]]), run_id),
                )
            return self.run(run_id)

    def product_digest(self) -> str:
        digest = hashlib.sha256()
        with self.database.connect() as connection:
            for table in _PRODUCT_TABLES:
                columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]
                digest.update(table.encode())
                if not columns:
                    continue
                quoted = ",".join('"' + item.replace('"', '""') + '"' for item in columns)
                rows = connection.execute(f"SELECT {quoted} FROM {table} ORDER BY {quoted}").fetchall()
                for row in rows:
                    digest.update(_json([row[item] for item in columns]).encode())
        return digest.hexdigest()

    def _snapshot(self) -> dict:
        with self.database.connect() as connection:
            claims = [_decode(row) for row in connection.execute(
                "SELECT * FROM memory_claims ORDER BY id"
            ).fetchall()]
            relations = [_decode(row) for row in connection.execute(
                "SELECT * FROM memory_relations ORDER BY id"
            ).fetchall()]
            usage = {
                str(row["claim_id"]): {
                    "presented": int(row["presented"]), "used": int(row["used"]),
                    "last_used_at": row["last_used_at"],
                }
                for row in connection.execute(
                    """SELECT claim_id,
                       sum(CASE WHEN usage='presented' THEN 1 ELSE 0 END) AS presented,
                       sum(CASE WHEN usage='used' THEN 1 ELSE 0 END) AS used,
                       max(CASE WHEN usage='used' THEN created_at END) AS last_used_at
                       FROM memory_compiler_usage GROUP BY claim_id"""
                ).fetchall()
            }
            orphan_rows = self._orphan_rows(connection)
            foreign_keys = [dict(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()]
        return {
            "claims": claims, "relations": relations, "usage": usage,
            "orphans": orphan_rows, "foreign_keys": foreign_keys,
            "active_claims": sum(item["lifecycle"] == "active" for item in claims),
            "historical_claims": sum(item["lifecycle"] in {"retired", "invalid"} for item in claims),
        }

    @staticmethod
    def _orphan_rows(connection) -> list[dict]:
        checks = (
            ("relation_from", """SELECT r.id,r.from_claim_id AS claim_id FROM memory_relations r
                LEFT JOIN memory_claims c ON c.id=r.from_claim_id WHERE c.id IS NULL"""),
            ("relation_to", """SELECT r.id,r.to_claim_id AS claim_id FROM memory_relations r
                LEFT JOIN memory_claims c ON c.id=r.to_claim_id WHERE c.id IS NULL"""),
            ("evidence_claim", """SELECT e.id,e.claim_id FROM memory_evidence e
                LEFT JOIN memory_claims c ON c.id=e.claim_id WHERE c.id IS NULL"""),
            ("evidence_observation", """SELECT e.id,e.claim_id FROM memory_evidence e
                LEFT JOIN memory_observations o ON o.id=e.observation_id
                WHERE e.observation_id IS NOT NULL AND o.id IS NULL"""),
            ("usage_claim", """SELECT u.turn_id||':'||u.consumer||':'||u.claim_id AS id,u.claim_id
                FROM memory_compiler_usage u LEFT JOIN memory_claims c ON c.id=u.claim_id WHERE c.id IS NULL"""),
        )
        return [
            {"kind": kind, **dict(row)}
            for kind, sql in checks for row in connection.execute(sql).fetchall()
        ]

    def _analyze(self, snapshot: dict) -> tuple[list[dict], list[str]]:
        claims = snapshot["claims"]
        active = [item for item in claims if item["lifecycle"] == "active"]
        by_id = {item["id"]: item for item in claims}
        findings: list[dict] = []

        semantic_groups = defaultdict(list)
        for claim in active:
            payload = claim.get("payload") if isinstance(claim.get("payload"), dict) else {}
            # Opaque payloads can contain provenance only. Their statement is
            # part of their identity; equal labels do not mean equal facts.
            statement = claim["display_text"] if claim["claim_kind"] == "opaque_fact" else None
            semantic_groups[(claim["scope"], claim["claim_kind"], _json(payload), statement)].append(claim)
        for group in semantic_groups.values():
            if len(group) > 1:
                findings.append(self._finding(
                    "possible_duplicate", "same_structured_claim", group, "merge", "high",
                    "Mehrere aktive Claims besitzen dieselbe Scope-, Typ- und Payload-Semantik.", snapshot,
                    {"semantic_basis": ["scope", "claim_kind", "payload", "display_text"]
                     if group[0]["claim_kind"] == "opaque_fact"
                     else ["scope", "claim_kind", "payload"]},
                ))

        slots = defaultdict(list)
        for claim in active:
            if claim.get("slot_key"):
                slots[(claim["scope"], claim["claim_kind"], claim["slot_key"])].append(claim)
        for group in slots.values():
            signatures = {_json(item.get("payload") or {}) for item in group}
            if len(group) > 1 and len(signatures) > 1:
                findings.append(self._finding(
                    "potential_contradiction", "active_slot_conflict", group, "review", "high",
                    "Mehrere aktive Claims belegen denselben vorhandenen Slot mit unterschiedlichen Payloads.",
                    snapshot, {"slot_key": group[0]["slot_key"]},
                ))

        successors = defaultdict(list)
        for relation in snapshot["relations"]:
            if relation["relation_type"] == "supersedes":
                successors[relation["to_claim_id"]].append(relation["from_claim_id"])

        def has_active_successor(claim):
            pending, visited = list(successors[claim["id"]]), {claim["id"]}
            while pending:
                identifier = pending.pop()
                if identifier in visited:
                    continue
                visited.add(identifier)
                successor = by_id.get(identifier)
                if not successor or successor["scope"] != claim["scope"] or successor.get("slot_key") != claim.get("slot_key"):
                    continue
                if successor["lifecycle"] == "active":
                    return True
                if successor["lifecycle"] == "retired":
                    pending.extend(successors[identifier])
            return False

        for relation in snapshot["relations"]:
            left, right = by_id.get(relation["from_claim_id"]), by_id.get(relation["to_claim_id"])
            if relation["relation_type"] == "contradicts" and left and right:
                if left["lifecycle"] == right["lifecycle"] == "active":
                    findings.append(self._finding(
                        "potential_contradiction", "explicit_active_contradiction", [left, right],
                        "review", "high", "Eine bestehende contradicts-Relation verbindet zwei aktive Claims.",
                        snapshot, {"relation_id": relation["id"]},
                    ))
            if relation["relation_type"] == "supersedes" and left and right:
                violations = []
                if left["lifecycle"] != "active" and not (
                    left["lifecycle"] == "retired" and has_active_successor(left)
                ): violations.append("source_not_active")
                if right["lifecycle"] != "retired": violations.append("target_not_retired")
                if left["scope"] != right["scope"]: violations.append("scope_mismatch")
                if left.get("slot_key") != right.get("slot_key"): violations.append("slot_mismatch")
                if violations:
                    findings.append(self._finding(
                        "suspicious_history", "inconsistent_supersession", [left, right],
                        "repair_relation", "high", "Eine Supersession verletzt bestehende Lifecycle-/Identitätsinvarianten.",
                        snapshot, {"relation_id": relation["id"], "violations": violations},
                    ))

        supersession_edges = {
            item["from_claim_id"]: item["to_claim_id"] for item in snapshot["relations"]
            if item["relation_type"] == "supersedes"
        }
        for start in sorted(supersession_edges):
            path, current = [], start
            while current in supersession_edges and current not in path:
                path.append(current)
                current = supersession_edges[current]
            if current in path:
                cycle = path[path.index(current):]
                findings.append(self._finding(
                    "suspicious_history", "supersession_cycle",
                    [by_id[item] for item in cycle if item in by_id], "repair_relation", "high",
                    "Die bestehenden Supersession-Relationen bilden einen unzulässigen Zyklus.",
                    snapshot, {"cycle": cycle}, identity_extra=":".join(sorted(cycle)),
                ))

        scopes = defaultdict(list)
        for claim in active:
            payload = claim.get("payload") if isinstance(claim.get("payload"), dict) else {}
            subject = payload.get("subject")
            if payload.get("inventory_source") and payload.get("external_reference"):
                subject = payload["external_reference"]
            if subject:
                scopes[(claim["scope"], claim["claim_kind"], str(subject))].append(claim)
        for group in scopes.values():
            if len(group) >= 3 and len({item.get("slot_key") for item in group}) == len(group):
                findings.append(self._finding(
                    "consolidation_candidate", "related_claim_cluster", group, "review", "low",
                    "Mindestens drei aktive Claims beschreiben dasselbe Subjekt in getrennten Slots; eine verlustfreie Strukturprüfung ist möglich.",
                    snapshot, {"information_must_be_preserved": True},
                ))

        for orphan in snapshot["orphans"]:
            claim = by_id.get(orphan.get("claim_id"))
            findings.append(self._finding(
                "orphaned_data", orphan["kind"], [claim] if claim else [], "repair_relation", "high",
                "Ein Datensatz referenziert nach dem bestehenden Schema kein vorhandenes Zielobjekt.", snapshot,
                {"record_id": orphan["id"], "missing_claim_id": orphan.get("claim_id")},
                identity_extra=orphan["id"],
            ))
        warnings = []
        if snapshot["foreign_keys"]:
            warnings.append(f"foreign_key_violations:{len(snapshot['foreign_keys'])}")
        return self._deduplicate(findings), warnings

    def _finding(self, problem_class, category, claims, action, confidence, rationale,
                 snapshot, evidence, *, identity_extra="") -> dict:
        claim_ids = sorted(str(item["id"]) for item in claims if item)
        usage = {claim_id: snapshot["usage"].get(claim_id, {
            "presented": 0, "used": 0, "last_used_at": None,
        }) for claim_id in claim_ids}
        evidence = {**evidence, "usage": usage, "usage_is_signal_only": True}
        key = hashlib.sha256(_json([
            ANALYZER_VERSION, problem_class, category, claim_ids, action, identity_extra,
        ]).encode()).hexdigest()
        return {
            "finding_key": key, "problem_class": problem_class, "category": category,
            "affected_claim_ids": claim_ids, "rationale": rationale,
            "proposed_action": action, "confidence": confidence, "evidence": evidence,
        }

    @staticmethod
    def _deduplicate(findings: list[dict]) -> list[dict]:
        return list({item["finding_key"]: item for item in findings}.values())

    def _persist_findings(self, run_id: str, findings: list[dict], observed_at: str) -> dict:
        with self.database.connect() as connection:
            for item in findings:
                finding_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "eve:" + item["finding_key"]))
                connection.execute(
                    """INSERT INTO memory_maintenance_findings
                       (id,finding_key,problem_class,category,affected_claim_ids_json,rationale,
                        proposed_action,confidence,evidence_json,first_seen_at,last_seen_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(finding_key) DO UPDATE SET
                         rationale=excluded.rationale,evidence_json=excluded.evidence_json,
                         confidence=excluded.confidence,last_seen_at=excluded.last_seen_at""",
                    (finding_id, item["finding_key"], item["problem_class"], item["category"],
                     _json(item["affected_claim_ids"]), item["rationale"], item["proposed_action"],
                     item["confidence"], _json(item["evidence"]), observed_at, observed_at),
                )
                connection.execute(
                    """INSERT OR IGNORE INTO memory_maintenance_run_findings
                       (run_id,finding_id,observed_at) VALUES (?,?,?)""",
                    (run_id, finding_id, observed_at),
                )
            total = int(connection.execute(
                "SELECT count(*) FROM memory_maintenance_findings"
            ).fetchone()[0])
        return {"distinct_findings_total": total}

    def runs(self, limit: int = 20) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memory_maintenance_runs ORDER BY started_at DESC LIMIT ?",
                (min(max(int(limit), 1), 100),),
            ).fetchall()
        return [_decode(row) for row in rows]

    def run(self, run_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_maintenance_runs WHERE id=?", (str(run_id),)
            ).fetchone()
            if row is None:
                raise KeyError("Maintenance-Lauf wurde nicht gefunden")
            findings = connection.execute(
                """SELECT f.* FROM memory_maintenance_findings f
                   JOIN memory_maintenance_run_findings rf ON rf.finding_id=f.id
                   WHERE rf.run_id=? ORDER BY f.problem_class,f.confidence DESC,f.id""",
                (str(run_id),),
            ).fetchall()
        result = _decode(row)
        result["findings"] = [_decode(item) for item in findings]
        return result

    def finding(self, finding_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_maintenance_findings WHERE id=?", (str(finding_id),)
            ).fetchone()
            if row is None:
                raise KeyError("Maintenance-Finding wurde nicht gefunden")
            runs = [str(item[0]) for item in connection.execute(
                "SELECT run_id FROM memory_maintenance_run_findings WHERE finding_id=? ORDER BY observed_at",
                (str(finding_id),),
            ).fetchall()]
        result = _decode(row)
        result["run_ids"] = runs
        return result
