import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from eve_agent.config import DEFAULTS
from eve_agent.memory_compiler import MemoryCompiler
from eve_agent.memory_v2 import MemoryV2Runtime
from eve_agent.runtime_self_knowledge import RuntimeSelfDescription, RuntimeSelfKnowledgeSync
from eve_agent.semantic_links import SemanticLinks
from eve_agent.shadow_learning import ProductiveLearningPipeline
from eve_agent.storage import ConversationStore, EveDatabase


NOW = "2026-10-13T12:00:00+00:00"


class _ProviderLearningCall:
    model = "fixture"

    def analyze_shadow_learning(self, context):
        user = context["user_message"]
        tool = context["tool_events"][0]
        return {
            "decision_type": "create_active", "memory_worthy": True,
            "reason_code": "grounded_provider_relation", "uncertainty": 0.0,
            "clarification_recommended": False, "authority": "provider",
            "temporal_class": "stable", "change_type": None,
            "claim": {
                "kind": "provider_binding", "scope": "household:default",
                "canonical_key": "v2:model-selected", "slot_key": "v2:model-selected",
                "display_text": "Rollo Schlafzimmer", "valid_from": None,
                "valid_until": None, "payload": {
                    "provider": "home_assistant", "subject": "Rollo Schlafzimmer",
                    "property": "resource", "external_reference": "cover.bedroom",
                },
            },
            "evidence": [
                {"source_type": "user_message", "source_id": user["id"],
                 "stance": "supports", "property": None, "external_reference": None},
                {"source_type": "provider_result", "source_id": tool["id"],
                 "stance": "supports", "property": "entity_id",
                 "external_reference": "cover.bedroom"},
            ],
            "matched_claim_ids": [], "relations": [],
        }


class MemoryLifecycleTelemetryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "eve.db"
        self.database = EveDatabase(self.path)

    def events(self, claim_id=None):
        with self.database.connect() as connection:
            where, values = (" WHERE claim_id=?", (claim_id,)) if claim_id else ("", ())
            return [dict(row) | {"details": json.loads(row["details_json"])} for row in
                    connection.execute(
                        "SELECT * FROM memory_runtime_events" + where + " ORDER BY rowid",
                        values,
                    ).fetchall()]

    def insert_claim(self, claim_id="claim-a", lifecycle="candidate", payload="{}"):
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES (?,'opaque_fact','test',?,'private claim text',?,?,'stable',?,?)""",
                (claim_id, claim_id, payload, lifecycle, NOW, NOW),
            )

    def test_creation_activation_payload_update_retirement_invalidation_and_restore(self):
        self.insert_claim()
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE memory_claims SET lifecycle='active',updated_at=? WHERE id='claim-a'",
                ("2026-10-13T12:00:01+00:00",),
            )
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE memory_claims SET payload_json=?,updated_at=? WHERE id='claim-a'",
                ('{"nested":{"status":"kept","token":"must-not-leak"}}',
                 "2026-10-13T12:00:02+00:00"),
            )
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE memory_claims SET lifecycle='retired',updated_at=? WHERE id='claim-a'",
                ("2026-10-13T12:00:03+00:00",),
            )
            connection.execute(
                "UPDATE memory_claims SET lifecycle='active',updated_at=? WHERE id='claim-a'",
                ("2026-10-13T12:00:04+00:00",),
            )
            connection.execute(
                "UPDATE memory_claims SET lifecycle='invalid',updated_at=? WHERE id='claim-a'",
                ("2026-10-13T12:00:05+00:00",),
            )
        events = self.events("claim-a")
        self.assertEqual(
            ["created", "activated", "updated", "retired", "restored", "invalidated"],
            [item["details"]["change_kind"] for item in events],
        )
        self.assertIn("payload_json", events[2]["details"]["changed_fields"])
        encoded = json.dumps(events, ensure_ascii=False)
        self.assertNotIn("private claim text", encoded)
        self.assertNotIn("must-not-leak", encoded)
        self.assertNotIn("nested", encoded)

    def test_noop_update_and_failed_mutation_create_no_event(self):
        self.insert_claim()
        before = len(self.events())
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE memory_claims SET lifecycle=lifecycle WHERE id='claim-a'"
            )
        self.assertEqual(before, len(self.events()))
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_claim()
        self.assertEqual(before, len(self.events()))

    def test_event_failure_rolls_back_claim_and_trace(self):
        with patch(
            "eve_agent.memory_lifecycle.MemoryRuntimeRecorder.record_events",
            side_effect=sqlite3.OperationalError("injected telemetry failure"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                self.insert_claim("rolled-back")
        with self.database.connect() as connection:
            self.assertIsNone(connection.execute(
                "SELECT id FROM memory_claims WHERE id='rolled-back'"
            ).fetchone())
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM memory_runtime_traces"
            ).fetchone()[0])

    def test_multiple_changes_in_one_transaction_are_distinct_and_atomic(self):
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES ('multi','opaque_fact','test','multi','x','{}','candidate','stable',?,?)""",
                (NOW, NOW),
            )
            connection.execute(
                "UPDATE memory_claims SET lifecycle='active',updated_at=? WHERE id='multi'",
                ("2026-10-13T12:00:01+00:00",),
            )
        events = self.events("multi")
        self.assertEqual(["created", "activated"], [e["details"]["change_kind"] for e in events])
        self.assertEqual(2, len({event["id"] for event in events}))

    def test_historical_claims_are_not_backfilled(self):
        historical = EveDatabase(self.path, lifecycle_audit=False)
        with historical.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES ('historical','opaque_fact','test','historical','old','{}',
                           'active','stable',?,?)""", (NOW, NOW),
            )
        reopened = EveDatabase(self.path)
        with reopened.connect() as connection:
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM memory_runtime_events"
            ).fetchone()[0])

    def test_optional_runtime_telemetry_off_does_not_disable_lifecycle_audit(self):
        self.assertFalse(DEFAULTS["memory_runtime_telemetry"]["enabled"])
        self.assertEqual("required", DEFAULTS["memory_runtime_telemetry"]["lifecycle_audit"])
        self.insert_claim()
        self.assertEqual(1, len(self.events("claim-a")))

    def test_runtime_self_knowledge_is_idempotent_and_uses_technical_trace(self):
        sync = RuntimeSelfKnowledgeSync(self.database)
        item = RuntimeSelfDescription(
            "provider.search", "search", "Ich kann suchen.", "Provider", "search",
        )
        sync.sync([item])
        first = len(self.events())
        sync.sync([item])
        self.assertEqual(first, len(self.events()))
        event = self.events()[0]
        self.assertEqual("memory.runtime_self_knowledge", event["producer"])
        self.assertIsNone(event["turn_id"])

    def test_forget_has_turn_provenance_and_inactive_or_missing_is_noop(self):
        self.insert_claim(lifecycle="active")
        runtime = MemoryV2Runtime(self.database, MemoryCompiler(self.database))
        claim = {"id": "claim-a", "display_text": "private claim text", "lifecycle": "active"}
        runtime.compile_view = lambda *args, **kwargs: {"claims": [claim]}
        trace = "12345678123456781234567812345678"
        self.assertEqual(["private claim text"], runtime.forget(
            "claim", trace_id=trace, turn_id=trace,
        ))
        event = self.events("claim-a")[-1]
        self.assertEqual("retired", event["details"]["change_kind"])
        self.assertEqual(trace, event["trace_id"])
        self.assertEqual(trace, event["turn_id"])
        count = len(self.events())
        self.assertEqual([], runtime.forget("claim", trace_id=trace, turn_id=trace))
        runtime.compile_view = lambda *args, **kwargs: {"claims": []}
        self.assertEqual([], runtime.forget("missing", trace_id=trace, turn_id=trace))
        self.assertEqual(count, len(self.events()))

    def test_semantic_supersession_keeps_relation_reference(self):
        links = SemanticLinks(self.database)
        context = {"conversation_id": "c", "history": [], "focus": [], "pending": None,
                   "task_active": False}
        provider = {"provider": "home_assistant", "endpoint": "http://ha"}
        plan = {"effect": "write", "context_required": False,
                "actions": [{"type": "call_service", "entity_id": "light.a",
                             "service": "light.turn_on"}]}
        old = links.learn("Licht", context, provider, plan, {"status": "success"}, source_ref="turn:1")
        links.decide(old, confirmed=True, source_ref="turn:1")
        new = links.learn("Licht", context, provider, plan, {"status": "success"}, source_ref="turn:2")
        links.decide(new, confirmed=True, source_ref="turn:2", supersedes=old)
        old_event = self.events(old)[-1]
        self.assertEqual("superseded", old_event["details"]["change_kind"])
        self.assertTrue(old_event["details"]["relation_ids"])

    def test_productive_learning_links_real_turn_and_model_decision(self):
        conversations = ConversationStore(self.database)
        conversation_id = conversations.create("Lifecycle")["id"]
        turn_id = "turn-provider-lifecycle"
        conversations.append_turn(
            conversation_id,
            "Ist das Rollo geschlossen?",
            "Ja.",
            turn_id=turn_id,
            assistant_metadata={"route": "home"},
            tool_events=[{
                "tool": "home_assistant", "status": "completed", "summary": "gelesen",
                "input": {"actions": ["get_state"]},
                "result": {"status": "success", "resolved_resources": [{
                    "entity_id": "cover.bedroom", "name": "Rollo Schlafzimmer",
                    "namespace": "cover",
                }]},
            }],
        )
        result = ProductiveLearningPipeline(
            self.database, _ProviderLearningCall(),
        ).process_turn(turn_id)
        event = self.events(result["claim_id"])[0]
        self.assertEqual(turn_id, event["trace_id"])
        self.assertEqual(turn_id, event["turn_id"])
        self.assertEqual(result["id"], event["learning_decision_id"])
        self.assertTrue(event["details"]["evidence_ids"])

    def test_concurrent_updates_preserve_the_real_state_chain(self):
        self.insert_claim(lifecycle="active", payload='{"count":0}')
        errors = []

        def update(number):
            try:
                with self.database.connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        """UPDATE memory_claims
                           SET payload_json=json_set(payload_json,'$.count',
                               json_extract(payload_json,'$.count')+1),updated_at=?
                           WHERE id='claim-a'""",
                        (f"2026-10-13T12:00:0{number}+00:00",),
                    )
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [threading.Thread(target=update, args=(index,)) for index in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([], errors)
        updates = [event for event in self.events("claim-a")
                   if event["details"]["change_kind"] == "updated"]
        self.assertEqual(2, len(updates))
        self.assertEqual(updates[0]["state_after"], updates[1]["state_before"])
        with self.database.connect() as connection:
            self.assertEqual(2, json.loads(connection.execute(
                "SELECT payload_json FROM memory_claims WHERE id='claim-a'"
            ).fetchone()[0])["count"])


if __name__ == "__main__":
    unittest.main()
