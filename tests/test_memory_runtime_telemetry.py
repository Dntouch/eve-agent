import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from eve_agent.memory_runtime_telemetry import (
    EVENT_CONTRACT_VERSION,
    MemoryRuntimeEventReader,
    MemoryRuntimeRecorder,
    TelemetryContractError,
    TelemetryDedupeConflict,
)
from eve_agent.storage import EveDatabase, SCHEMA_VERSION


NOW = "2026-10-13T12:00:00+00:00"


class MemoryRuntimeTelemetryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "data" / "eve.db"
        # Phase-5B tests exercise the isolated recorder itself.  Productive
        # lifecycle capture has its own Phase-5D regression suite.
        self.database = EveDatabase(self.path, lifecycle_audit=False)
        self.recorder = MemoryRuntimeRecorder(self.database, enabled=True)
        with self.database.connect() as connection:
            for claim_id, canonical_key in (("claim-a", "a"), ("claim-b", "b")):
                connection.execute(
                    """INSERT INTO memory_claims
                       (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                        verification_policy,created_at,updated_at)
                       VALUES (?,'opaque_fact','test',?,'Test','{}','active','stable',?,?)""",
                    (claim_id, canonical_key, NOW, NOW),
                )
            connection.execute(
                """INSERT INTO memory_relations
                   (id,from_claim_id,to_claim_id,relation_type,created_at)
                   VALUES ('relation-a','claim-a','claim-b','refines',?)""",
                (NOW,),
            )

    def tearDown(self):
        self.directory.cleanup()

    def trace(self, trace_id="trace-a"):
        return self.recorder.create_trace(trace_id=trace_id, started_at=NOW)

    @staticmethod
    def technical(operation="operation-a", **changes):
        event = {
            "trace_id": "trace-a", "event_kind": "operation_started",
            "occurred_at": NOW, "operation_id": operation, "producer": "test-suite",
            "proof_level": "operation_boundary", "event_status": "started", "details": {},
        }
        event.update(changes)
        return event

    @staticmethod
    def claim(operation="operation-a", **changes):
        event = {
            "trace_id": "trace-a", "event_kind": "claim_retrieved",
            "occurred_at": NOW, "operation_id": operation, "producer": "test-suite",
            "proof_level": "compiler_evaluation", "event_status": "completed",
            "claim_id": "claim-a", "compiler_evaluation_id": "evaluation-a",
            "consumer": "planner", "details": {"retrieval_method": "exact"},
        }
        event.update(changes)
        return event

    def test_empty_tables_and_trace_without_persisted_turn(self):
        with self.database.connect() as connection:
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM memory_runtime_traces"
            ).fetchone()[0])
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM memory_runtime_events"
            ).fetchone()[0])
        self.assertEqual("trace-a", self.trace())
        result = self.recorder.record_event(self.technical(turn_id="turn-not-yet-persisted"))
        self.assertTrue(result["id"])

    def test_trace_creation_is_idempotent_and_conflicts_are_visible(self):
        self.assertEqual("trace-a", self.trace())
        self.assertEqual("trace-a", self.trace())
        with self.assertRaises(TelemetryDedupeConflict):
            self.recorder.create_trace(
                trace_id="trace-a", started_at="2026-10-13T12:00:01+00:00",
            )

    def test_claim_relation_and_technical_subject_contracts(self):
        self.trace()
        self.recorder.record_event(self.claim(operation="claim-operation"))
        self.recorder.record_event({
            **self.technical(operation="relation-operation"),
            "event_kind": "relation_traversed_for_retrieval",
            "proof_level": "relation_traversal", "event_status": "completed",
            "relation_id": "relation-a", "compiler_evaluation_id": "evaluation-a",
            "consumer": "planner", "details": {},
        })
        self.recorder.record_event(self.technical(operation="technical-operation"))
        with self.assertRaisesRegex(TelemetryContractError, "claim event"):
            self.recorder.record_event(self.claim(claim_id=None))
        with self.assertRaisesRegex(TelemetryContractError, "technical event"):
            self.recorder.record_event(self.technical(claim_id="claim-a"))

    def test_validation_rejects_unknown_kinds_missing_ids_proof_status_and_time(self):
        self.trace()
        cases = (
            (self.technical(event_kind="used"), "event_kind"),
            (self.technical(operation_id=None), "operation_id"),
            (self.technical(proof_level="actual_llm_use"), "proof_level"),
            (self.technical(event_status="maybe"), "event_status"),
            (self.technical(occurred_at=None), "occurred_at"),
        )
        for event, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                TelemetryContractError, message
            ):
                self.recorder.record_event(event)

    def test_stable_ids_identical_retry_and_conflicting_dedupe(self):
        self.trace()
        event = self.claim()
        first = self.recorder.record_event(event)
        second = self.recorder.record_event(dict(event))
        self.assertEqual(first, second)
        with self.assertRaises(TelemetryDedupeConflict):
            self.recorder.record_event(self.claim(details={"retrieval_method": "hybrid"}))
        with self.database.connect() as connection:
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM memory_runtime_events"
            ).fetchone()[0])

    def test_real_retries_have_distinct_attempt_identity(self):
        self.trace()
        base = {
            **self.technical(), "event_kind": "llm_transport_result",
            "proof_level": "transport_result", "event_status": "failed",
            "outcome_status": "error", "llm_call_id": "llm-call-a",
            "attempt_id": "attempt-1", "attempt_no": 1,
            "details": {"http_status": 503},
        }
        first = self.recorder.record_event(base)
        second = self.recorder.record_event({**base, "attempt_id": "attempt-2", "attempt_no": 2})
        self.assertNotEqual(first["id"], second["id"])

    def test_batch_is_atomic_on_foreign_key_failure(self):
        self.trace()
        with self.assertRaises(sqlite3.IntegrityError):
            self.recorder.record_events([
                self.technical(operation="valid-first"),
                self.claim(operation="invalid-second", claim_id="missing-claim"),
            ])
        with self.database.connect() as connection:
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM memory_runtime_events"
            ).fetchone()[0])

    def test_external_connection_batch_and_lifecycle_failure_share_transaction(self):
        self.trace()
        with self.assertRaises(sqlite3.IntegrityError):
            with self.database.connect() as connection:
                connection.execute(
                    """INSERT INTO memory_claims
                       (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                        verification_policy,created_at,updated_at)
                       VALUES ('claim-new','opaque_fact','test','new','New','{}','active','stable',?,?)""",
                    (NOW, NOW),
                )
                self.recorder.record_event({
                    **self.claim(operation="lifecycle", claim_id="claim-new"),
                    "event_kind": "claim_lifecycle_changed", "proof_level": "atomic_lifecycle",
                    "state_before": "candidate", "state_after": "active",
                    "reason_code": "confirmed", "learning_decision_id": "missing-decision",
                    "details": {"change_kind": "activated", "changed_fields": ["lifecycle"]},
                }, connection=connection)
        with self.database.connect() as connection:
            self.assertIsNone(connection.execute(
                "SELECT id FROM memory_claims WHERE id='claim-new'"
            ).fetchone())

    def test_database_constraints_and_append_only_triggers(self):
        self.trace()
        self.recorder.record_event(self.technical())
        with self.database.connect() as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO memory_runtime_events
                       (id,trace_id,event_kind,occurred_at,recorded_at,operation_id,producer,
                        proof_level,event_status,details_json,dedupe_key,record_digest)
                       VALUES ('bad','trace-a','trace_started',?,?,?,'raw-test',
                               'trace_boundary','invalid','{}',?,?)""",
                    (NOW, NOW, "bad-operation", "a" * 64, "b" * 64),
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute(
                    "UPDATE memory_runtime_events SET producer='changed' WHERE trace_id='trace-a'"
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute("DELETE FROM memory_runtime_traces WHERE id='trace-a'")

    def test_nested_redaction_forbidden_content_and_payload_bounds(self):
        self.trace()
        event = {
            **self.technical(), "event_kind": "llm_transport_result",
            "proof_level": "transport_result", "event_status": "completed",
            "outcome_status": "success", "llm_call_id": "llm-call-a",
            "attempt_id": "attempt-a", "attempt_no": 1,
            "details": {"metrics": {
                "auth_token": "token-secret", "X-API-Key": "key-secret",
                "endpoint": "https://user:pass@example.test/path?token=leak#fragment",
            }},
        }
        self.recorder.record_event(event)
        item = MemoryRuntimeEventReader(self.path).for_trace("trace-a")["items"][0]
        encoded = json.dumps(item)
        self.assertNotIn("token-secret", encoded)
        self.assertNotIn("key-secret", encoded)
        self.assertNotIn("user:pass", encoded)
        self.assertNotIn("?token", encoded)
        self.assertEqual("[REDACTED]", item["details"]["metrics"]["auth_token"])
        with self.assertRaisesRegex(TelemetryContractError, "not permitted"):
            self.recorder.record_event({**event, "operation_id": "prompt-copy", "details": {
                "metrics": {"raw-provider-response": "full-response"},
            }})
        with self.assertRaisesRegex(TelemetryContractError, "byte budget"):
            self.recorder.record_event({**event, "operation_id": "oversize", "details": {
                "metrics": {f"metric_{index}": 10 ** 300 for index in range(64)},
            }}, best_effort=False)
        with self.assertRaisesRegex(TelemetryContractError, "technical identifiers"):
            self.recorder.record_event({**event, "operation_id": "free-text", "details": {
                "metrics": {"innocent_name": "vollständiger freier Benutzertext"},
            }})
        with self.assertRaisesRegex(TelemetryContractError, "non-finite"):
            self.recorder.record_event({**event, "operation_id": "not-json", "details": {
                "metrics": {"latency": float("nan")},
            }})
        with self.assertRaisesRegex(TelemetryContractError, "maximum depth"):
            self.recorder.record_event({**event, "operation_id": "too-deep", "details": {
                "metrics": {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}},
            }})

    def test_read_only_queries_filters_and_pagination(self):
        self.trace()
        events = []
        for index in range(3):
            events.append(self.claim(
                operation=f"operation-{index}", turn_id="turn-a",
                occurred_at=f"2026-10-13T12:00:0{index}+00:00",
                details={"retrieval_method": "exact", "rank_score": index / 10},
            ))
        self.recorder.record_events(events)
        reader = MemoryRuntimeEventReader(self.path)
        first = reader.for_claim(
            "claim-a", limit=2, event_kind="claim_retrieved",
            proof_level="compiler_evaluation", event_status="completed",
        )
        self.assertEqual(2, len(first["items"]))
        self.assertTrue(first["page"]["has_more"])
        second = reader.for_claim(
            "claim-a", limit=2, event_kind="claim_retrieved",
            proof_level="compiler_evaluation", event_status="completed",
            cursor=first["page"]["next_cursor"],
        )
        self.assertEqual(1, len(second["items"]))
        self.assertEqual(3, len(reader.for_turn("turn-a")["items"]))
        self.assertEqual(3, len(reader.for_trace("trace-a")["items"]))
        with closing(reader._connect()) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM memory_runtime_events")

    def test_ingestion_cursor_delivers_late_persisted_event_once(self):
        self.trace()
        self.recorder.record_event(self.technical(
            operation="already-persisted", turn_id="turn-live",
            occurred_at="2026-10-13T12:00:10+00:00",
        ))
        reader = MemoryRuntimeEventReader(self.path)
        tail = reader.ingested_events("turn-live", tail=True, limit=2)
        self.assertEqual([], tail["items"])
        self.assertEqual("append_only_rowid", tail["page"]["cursor_basis"])

        late = self.recorder.record_event(self.technical(
            operation="late-write", turn_id="turn-live",
            occurred_at="2026-10-13T12:00:01+00:00",
        ))
        page = reader.ingested_events(
            "turn-live", cursor=tail["page"]["poll_cursor"], limit=2,
        )
        self.assertEqual([late["id"]], [item["id"] for item in page["items"]])
        repeat = reader.ingested_events(
            "turn-live", cursor=page["page"]["poll_cursor"], limit=2,
        )
        self.assertEqual([], repeat["items"])
        with self.assertRaisesRegex(ValueError, "cursor"):
            reader.ingested_events(
                "another-turn", cursor=page["page"]["poll_cursor"], limit=2,
            )

    def test_relation_llm_and_action_readers(self):
        self.trace()
        relation = {
            **self.technical(operation="relation-op"),
            "event_kind": "relation_bound_to_plan", "proof_level": "validated_binding",
            "event_status": "completed", "relation_id": "relation-a",
            "planner_round_id": "round-a", "plan_id": "plan-a",
        }
        transport = {
            **self.technical(operation="llm-op"),
            "event_kind": "llm_transport_result", "proof_level": "transport_result",
            "event_status": "completed", "outcome_status": "success",
            "llm_call_id": "call-a", "attempt_id": "attempt-a", "attempt_no": 1,
        }
        action = {
            **self.claim(operation="action-op"), "event_kind": "claim_bound_to_action",
            "proof_level": "validated_binding", "plan_id": "plan-a",
            "planner_round_id": "round-a", "action_id": "action-a", "action_index": 0,
            "provider": "home-assistant", "target_resource_id": "light.hall",
            "details": {"executor": "home-assistant"},
        }
        self.recorder.record_events([relation, transport, action])
        reader = MemoryRuntimeEventReader(self.path)
        self.assertEqual(1, len(reader.for_relation("relation-a")["items"]))
        self.assertEqual(1, len(reader.for_llm_call("call-a")["items"]))
        self.assertEqual(1, len(reader.for_action("action-a")["items"]))
        self.assertEqual(action["event_kind"], reader.event(
            reader.for_action("action-a")["items"][0]["id"]
        )["event_kind"])
        filtered = reader.events(
            planner_round_id="round-a", plan_id="plan-a", action_id="action-a",
            consumer="planner", order="desc", timestamp_from="2026-10-13",
            timestamp_to="2026-10-13T23:59:59+00:00",
        )
        self.assertEqual(["claim_bound_to_action"], [item["event_kind"] for item in filtered["items"]])
        transport_filtered = reader.events(
            llm_call_id="call-a", attempt_id="attempt-a", event_kinds=("llm_transport_result",),
        )
        self.assertEqual(1, len(transport_filtered["items"]))
        with self.assertRaises(ValueError):
            reader.events(order="newest")

    def test_descending_keyset_pagination_is_stable_and_bound_to_filters(self):
        self.trace()
        self.recorder.record_events([
            self.claim(operation=f"operation-{index}", turn_id="turn-a",
                       occurred_at=f"2026-10-13T12:00:0{index}+00:00")
            for index in range(3)
        ])
        reader = MemoryRuntimeEventReader(self.path)
        first = reader.events(claim_id="claim-a", order="desc", limit=2)
        second = reader.events(
            claim_id="claim-a", order="desc", limit=2, cursor=first["page"]["next_cursor"],
        )
        self.assertEqual(3, len(first["items"] + second["items"]))
        timestamps = [item["occurred_at"] for item in first["items"] + second["items"]]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))
        self.assertFalse({item["id"] for item in first["items"]} & {item["id"] for item in second["items"]})
        with self.assertRaisesRegex(ValueError, "does not match"):
            reader.events(turn_id="turn-a", order="desc", limit=2, cursor=first["page"]["next_cursor"])

    def test_disabled_recorder_never_accesses_database(self):
        class UnusableDatabase:
            def connect(self):
                raise AssertionError("disabled telemetry accessed the database")

        recorder = MemoryRuntimeRecorder(UnusableDatabase(), enabled=False)
        self.assertIsNone(recorder.create_trace(trace_id="disabled"))
        self.assertEqual([], recorder.record_events([{"invalid": True}]))
        self.assertEqual([], recorder.diagnostics())

    def test_best_effort_failure_is_diagnosable_and_fail_open(self):
        result = self.recorder.record_event(self.technical(), best_effort=True)
        self.assertIsNone(result)
        diagnostics = self.recorder.diagnostics()
        self.assertEqual("record_events", diagnostics[0]["operation"])
        self.assertEqual("IntegrityError", diagnostics[0]["error_class"])

    def test_indexed_synthetic_batch_remains_bounded(self):
        self.trace()
        events = []
        for index in range(100):
            stamp = f"2026-10-13T12:{index // 60:02d}:{index % 60:02d}+00:00"
            common = {"turn_id": f"turn-{index % 8}", "occurred_at": stamp}
            events.extend((
                self.claim(
                    operation=f"claim-{index}", claim_id=f"claim-{'a' if index % 2 else 'b'}",
                    compiler_evaluation_id=f"evaluation-{index % 12}", **common,
                    details={"retrieval_method": "synthetic", "rank_score": index / 100},
                ),
                {
                    **self.technical(operation=f"relation-{index}", **common),
                    "event_kind": "relation_bound_to_plan", "proof_level": "validated_binding",
                    "event_status": "completed", "relation_id": "relation-a",
                    "planner_round_id": f"round-{index % 6}", "plan_id": f"plan-{index}",
                },
                {
                    **self.technical(operation=f"llm-{index}", **common),
                    "event_kind": "llm_transport_result", "proof_level": "transport_result",
                    "event_status": "completed", "outcome_status": "success",
                    "llm_call_id": f"call-{index % 10}", "attempt_id": f"attempt-{index}",
                    "attempt_no": 1,
                },
                {
                    **self.claim(
                        operation=f"action-{index}",
                        claim_id=f"claim-{'a' if index % 2 else 'b'}", **common,
                    ),
                    "event_kind": "claim_bound_to_action", "proof_level": "validated_binding",
                    "planner_round_id": f"round-{index % 6}", "plan_id": f"plan-{index}",
                    "action_id": f"action-{index}", "action_index": index % 3,
                    "provider": "home-assistant", "target_resource_id": f"light.test_{index}",
                    "details": {"executor": "home-assistant"},
                },
            ))
        started = time.perf_counter()
        self.recorder.record_events(events)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 5.0)
        with self.database.connect() as connection:
            plan = " ".join(str(tuple(row)) for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM memory_runtime_events "
                "WHERE claim_id=? ORDER BY occurred_at,id LIMIT 50", ("claim-a",),
            ))
        self.assertIn("memory_runtime_events_claim_time", plan)


class MemoryRuntimeTelemetryMigrationTest(unittest.TestCase):
    def test_v16_migration_is_backed_up_idempotent_and_preserves_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data" / "eve.db"
            database = EveDatabase(path)
            with database.connect(lifecycle_audit=False) as connection:
                connection.execute(
                    """INSERT INTO memory_claims
                       (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                        verification_policy,created_at,updated_at)
                       VALUES ('preserved','opaque_fact','test','preserved','Keep','{}',
                               'active','stable',?,?)""", (NOW, NOW),
                )
                for name in (
                    "memory_runtime_events_no_delete", "memory_runtime_events_no_update",
                    "memory_runtime_traces_no_delete", "memory_runtime_traces_no_update",
                ):
                    connection.execute(f"DROP TRIGGER {name}")
                connection.execute("DROP TABLE memory_runtime_events")
                connection.execute("DROP TABLE memory_runtime_traces")
                connection.execute("PRAGMA user_version = 16")

            migrated = EveDatabase(path)
            backups = list((path.parent / "backups").glob(
                f"eve-schema-v16-to-v{SCHEMA_VERSION}-*.db"
            ))
            self.assertEqual(1, len(backups))
            with closing(sqlite3.connect(backups[0])) as backup:
                self.assertEqual(16, backup.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual("preserved", backup.execute(
                    "SELECT id FROM memory_claims WHERE id='preserved'"
                ).fetchone()[0])
            with migrated.connect() as connection:
                self.assertEqual(SCHEMA_VERSION, connection.execute(
                    "PRAGMA user_version"
                ).fetchone()[0])
                self.assertEqual("preserved", connection.execute(
                    "SELECT id FROM memory_claims WHERE id='preserved'"
                ).fetchone()[0])
            EveDatabase(path)
            self.assertEqual(1, len(list(
                (path.parent / "backups").glob(
                    f"eve-schema-v16-to-v{SCHEMA_VERSION}-*.db"
                )
            )))


if __name__ == "__main__":
    unittest.main()
