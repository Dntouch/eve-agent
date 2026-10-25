import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eve_agent.memory_compiler import MemoryCompiler, MemoryNeed
from eve_agent.memory_retrieval_telemetry import MemoryRetrievalTelemetry
from eve_agent.memory_runtime_telemetry import MemoryRuntimeEventReader, MemoryRuntimeRecorder
from eve_agent.memory_v2 import MemoryV2Runtime
from eve_agent.search import PersistentSearch
from eve_agent.storage import EveDatabase, SCHEMA_VERSION


NOW = "2026-10-13T12:00:00+00:00"


class MemoryRetrievalTelemetryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "eve.db"
        self.database = EveDatabase(self.path, lifecycle_audit=False)
        self.recorder = MemoryRuntimeRecorder(self.database, enabled=True)
        self.telemetry = MemoryRetrievalTelemetry(self.recorder)
        self.runtime = MemoryV2Runtime(
            self.database, MemoryCompiler(self.database), telemetry=self.telemetry,
        )

    def tearDown(self):
        self.directory.cleanup()

    def claim(self, claim_id, text, *, lifecycle="active", kind="opaque_fact",
              payload=None, canonical=None, scope="user:default"):
        with self.database.connect(lifecycle_audit=False) as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,'stable',?,?)""",
                (claim_id, kind, scope, canonical or claim_id, text,
                 json.dumps(payload or {}, ensure_ascii=False), lifecycle, NOW, NOW),
            )

    @staticmethod
    def context(trace="trace-a", round_id="round-a"):
        return {"trace_id": trace, "turn_id": trace, "planner_round_id": round_id}

    def items(self, trace="trace-a"):
        return MemoryRuntimeEventReader(self.path).for_trace(trace, limit=100)["items"]

    def test_retrieval_records_real_stages_return_boundary_and_relation(self):
        self.claim("claim-a", "Das Wohnzimmer Licht ist warm")
        self.claim("claim-b", "Die Wohnzimmer Lampe ist dimmbar")
        with self.database.connect(lifecycle_audit=False) as connection:
            connection.execute(
                """INSERT INTO memory_relations
                   (id,from_claim_id,to_claim_id,relation_type,created_at)
                   VALUES ('relation-a','claim-a','claim-b','refines',?)""", (NOW,),
            )

        hits = self.runtime.retrieve(
            "Wohnzimmer Licht", limit=1, telemetry_context=self.context(),
        )
        self.assertEqual(1, len(hits))
        events = self.items()
        kinds = [item["event_kind"] for item in events]
        self.assertIn("claim_retrieved", kinds)
        self.assertIn("claim_eligible", kinds)
        self.assertIn("claim_selected_for_view", kinds)
        returned = [item for item in events if item["event_kind"] == "claim_returned_to_consumer"]
        self.assertEqual([hits[0].memory_id], [item["claim_id"] for item in returned])
        relations = [item for item in events if item["event_kind"] == "relation_traversed_for_retrieval"]
        self.assertEqual(["relation-a"], [item["relation_id"] for item in relations])
        self.assertEqual(1, len({item["operation_id"] for item in events}))
        self.assertEqual({"round-a"}, {
            item["planner_round_id"] for item in events if item["planner_round_id"]
        })

    def test_no_hit_and_excluded_candidate_are_truthfully_distinct(self):
        self.claim("candidate-a", "Geheimer Kandidat Merkur", lifecycle="candidate")
        hits = self.runtime.retrieve(
            "Merkur", telemetry_context=self.context("trace-candidate"),
        )
        self.assertEqual([], hits)
        events = self.items("trace-candidate")
        self.assertIn("claim_retrieved", [item["event_kind"] for item in events])
        self.assertNotIn("claim_eligible", [item["event_kind"] for item in events])
        self.assertNotIn("claim_returned_to_consumer", [item["event_kind"] for item in events])

        empty = self.runtime.retrieve(
            "NiemalsVorhanden", telemetry_context=self.context("trace-empty"),
        )
        self.assertEqual([], empty)
        self.assertEqual(
            {"operation_started", "claim_query_started", "operation_completed"},
            {item["event_kind"] for item in self.items("trace-empty")},
        )

    def test_multiple_retrievals_in_one_turn_have_distinct_operations(self):
        self.claim("claim-a", "Orion Zuhause")
        context = self.context("shared-trace")
        self.runtime.retrieve("Orion", telemetry_context=context)
        self.runtime.retrieve("Orion", telemetry_context=context)
        events = self.items("shared-trace")
        starts = [item for item in events if item["event_kind"] == "operation_started"]
        self.assertEqual(2, len(starts))
        self.assertEqual(2, len({item["operation_id"] for item in starts}))

    def test_disabled_observer_writes_nothing_and_does_not_change_result(self):
        self.claim("claim-a", "Saturn Ring")
        expected = [hit.memory_id for hit in self.runtime.retrieve(
            "Saturn", telemetry_context=self.context("enabled-trace"),
        )]
        disabled = MemoryV2Runtime(
            self.database, MemoryCompiler(self.database),
            telemetry=MemoryRetrievalTelemetry(
                MemoryRuntimeRecorder(self.database, enabled=False)
            ),
        )
        actual = [hit.memory_id for hit in disabled.retrieve(
            "Saturn", telemetry_context=self.context("disabled-trace"),
        )]
        self.assertEqual(expected, actual)
        with self.database.connect(lifecycle_audit=False) as connection:
            self.assertIsNone(connection.execute(
                "SELECT id FROM memory_runtime_traces WHERE id='disabled-trace'"
            ).fetchone())

    def test_event_write_failure_is_fail_open_and_diagnosed(self):
        self.claim("claim-a", "Venus Wissen")
        with patch.object(
            self.recorder, "record_trace_events", side_effect=RuntimeError("write failed"),
        ):
            hits = self.runtime.retrieve(
                "Venus", telemetry_context=self.context("trace-fail-open"),
            )
        self.assertEqual(["claim-a"], [hit.memory_id for hit in hits])
        self.assertEqual("RuntimeError", self.telemetry.diagnostics()[-1]["error_class"])

    def test_retrieval_trace_is_reused_by_required_forget_lifecycle_audit(self):
        self.claim("claim-a", "Pluto Erinnerung")
        audited_database = EveDatabase(self.path)
        recorder = MemoryRuntimeRecorder(audited_database, enabled=True)
        runtime = MemoryV2Runtime(
            audited_database, MemoryCompiler(audited_database),
            telemetry=MemoryRetrievalTelemetry(recorder),
        )
        forgotten = runtime.forget(
            "Pluto Erinnerung", trace_id="trace-forget", turn_id="trace-forget",
        )
        self.assertEqual(["Pluto Erinnerung"], forgotten)
        kinds = {
            item["event_kind"] for item in
            MemoryRuntimeEventReader(self.path).for_trace("trace-forget", limit=100)["items"]
        }
        self.assertIn("claim_returned_to_consumer", kinds)
        self.assertIn("claim_lifecycle_changed", kinds)

    def test_compiler_failure_records_abort_and_preserves_exception(self):
        with patch.object(self.runtime.compiler, "preview", side_effect=ValueError("broken")):
            with self.assertRaisesRegex(ValueError, "broken"):
                self.runtime.retrieve(
                    "Fehler", telemetry_context=self.context("trace-abort"),
                )
        self.assertEqual(
            {"operation_started", "claim_query_started", "operation_aborted"},
            {item["event_kind"] for item in self.items("trace-abort")},
        )

    def test_alias_stt_and_provider_binding_use_exact_claim_ids(self):
        self.claim(
            "alias-a", "Flur Alias", kind="alias",
            payload={"alias": "Flurlicht", "target": "light.flur"},
        )
        self.claim(
            "binding-a", "Flur Licht Ressource", kind="provider_binding",
            canonical="light.flur", payload={
                "provider": "home_assistant", "subject": "Flur Licht",
                "property": "resource", "external_reference": "light.flur",
            },
        )
        aliases = self.runtime.device_aliases(
            consumer="stt", telemetry_context=self.context("trace-alias"),
        )
        self.assertIn("flurlicht", aliases)
        alias_events = self.items("trace-alias")
        resolved = [item for item in alias_events if item["event_kind"] == "alias_read_for_stt"]
        self.assertEqual(["alias-a"], [item["claim_id"] for item in resolved])

        bindings = self.runtime.provider_bindings(
            "Flur Licht", telemetry_context=self.context("trace-binding"),
        )
        self.assertEqual(["binding-a"], [item["memory_id"] for item in bindings])
        returned = [item for item in self.items("trace-binding")
                    if item["event_kind"] == "claim_returned_to_consumer"]
        self.assertEqual(["binding-a"], [item["claim_id"] for item in returned])

    def test_local_knowledge_and_direct_preview_audit_separation(self):
        self.claim("claim-a", "Neptun Wissen")
        search = PersistentSearch(self.database, memory_runtime=self.runtime)
        results = search.knowledge(
            "Neptun", telemetry_context=self.context("trace-local"),
        )
        self.assertEqual(["claim-a"], [item["memory_id"] for item in results])
        started = next(item for item in self.items("trace-local")
                       if item["event_kind"] == "claim_query_started")
        self.assertEqual("local_knowledge.search", started["details"]["query_kind"])

        self.runtime.compiler.preview(MemoryNeed("answer", "Neptun"))
        with self.database.connect(lifecycle_audit=False) as connection:
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM memory_runtime_traces"
            ).fetchone()[0])

    def test_known_semantic_claim_can_be_resolved_without_text_lookup(self):
        self.claim("semantic-a", "Semantische Erfahrung", scope="semantic_links")
        self.runtime.record_claim_resolution(
            "semantic-a", consumer="semantic_links", query_kind="semantic.exact_lookup",
            telemetry_context=self.context("trace-semantic", round_id=None),
        )
        resolved = [item for item in self.items("trace-semantic")
                    if item["event_kind"] == "claim_resolved"]
        self.assertEqual(["semantic-a"], [item["claim_id"] for item in resolved])

    def test_schema_17_upgrade_preserves_existing_runtime_events(self):
        self.recorder.create_trace(trace_id="old-trace", started_at=NOW)
        self.recorder.record_event({
            "trace_id": "old-trace", "event_kind": "operation_started",
            "occurred_at": NOW, "operation_id": "old-operation",
            "producer": "test-suite", "proof_level": "operation_boundary",
            "event_status": "started", "details": {},
        })
        with self.database.connect(lifecycle_audit=False) as connection:
            for name in ("memory_runtime_events_no_update", "memory_runtime_events_no_delete"):
                connection.execute(f"DROP TRIGGER {name}")
            indexes = connection.execute(
                """SELECT name FROM sqlite_master WHERE type='index'
                   AND name LIKE 'memory_runtime_events_%'"""
            ).fetchall()
            for row in indexes:
                connection.execute(f"DROP INDEX {row[0]}")
            connection.execute("ALTER TABLE memory_runtime_events RENAME TO events_v18")
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='events_v18'"
            ).fetchone()[0]
            old_sql = str(sql).replace(
                '"events_v18"', "memory_runtime_events"
            ).replace(
                ",'claim_returned_to_consumer'", ""
            ).replace(
                ",'consumer_boundary'", ""
            )
            connection.execute(old_sql)
            columns = ",".join(
                str(row[1]) for row in connection.execute("PRAGMA table_info(events_v18)")
            )
            connection.execute(
                f"INSERT INTO memory_runtime_events({columns}) "
                f"SELECT {columns} FROM events_v18"
            )
            connection.execute("DROP TABLE events_v18")
            connection.execute("PRAGMA user_version=17")

        migrated = EveDatabase(self.path, lifecycle_audit=False)
        with migrated.connect(lifecycle_audit=False) as connection:
            self.assertEqual(SCHEMA_VERSION, connection.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual("old-operation", connection.execute(
                "SELECT operation_id FROM memory_runtime_events"
            ).fetchone()[0])
            schema = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='memory_runtime_events'"
            ).fetchone()[0]
            self.assertIn("claim_returned_to_consumer", schema)
            self.assertIn("consumer_boundary", schema)


if __name__ == "__main__":
    unittest.main()
