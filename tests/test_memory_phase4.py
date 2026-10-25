import json
import tempfile
import unittest
from pathlib import Path

from eve_agent.memory_compiler import MemoryCompiler
from eve_agent.memory_v2 import MemoryV2Runtime
from eve_agent.runtime_self_knowledge import RuntimeSelfDescription, RuntimeSelfKnowledgeSync
from eve_agent.search import PersistentSearch
from eve_agent.shadow_learning import ProductiveLearningPipeline
from eve_agent.storage import ConversationStore, EveDatabase, SCHEMA_VERSION


class FakeLearningLLM:
    model = "phase4-fake"

    def __init__(self, factory):
        self.factory = factory

    def analyze_shadow_learning(self, context):
        return self.factory(context)


def claim_proposal(context, *, value="Haferbrei", decision="create_active", matched=None,
                   lifecycle="active", change_type=None):
    message_id = context["user_message"]["id"]
    return {
        "decision_type": decision, "memory_worthy": decision != "no_persist",
        "reason_code": "phase4_test", "uncertainty": 0.05,
        "clarification_recommended": False, "authority": "user_direct",
        "temporal_class": "stable", "change_type": change_type,
        "claim": None if decision in {"no_persist", "append_supporting_evidence"} else {
            "kind": "opaque_fact", "scope": "user:self",
            "canonical_key": f"v2:preference:user:self:breakfast:{value.casefold()}",
            "slot_key": "v2:preference:user:self:breakfast",
            "lifecycle": lifecycle,
            "display_text": f"Der Benutzer bevorzugt morgens {value}.",
            "payload": {"subject": "user:self", "property": "breakfast", "value": value},
            "valid_from": None, "valid_until": None,
        },
        "evidence": [] if decision == "no_persist" else [{
            "source_type": "user_message", "source_id": message_id,
            "stance": "supports", "property": None, "external_reference": None,
        }],
        "matched_claim_ids": matched or [], "relations": [],
    }


class MemoryPhase4Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = EveDatabase(Path(self.temp.name) / "eve.db")
        self.conversations = ConversationStore(self.database)
        self.conversation_id = self.conversations.create("Phase 4")["id"]

    def tearDown(self):
        self.temp.cleanup()

    def turn(self, text, index):
        turn_id = f"turn-{index}"
        user, _ = self.conversations.append_turn(
            self.conversation_id, text, "Antwort", turn_id=turn_id,
            assistant_metadata={"route": "chat"},
        )
        return turn_id, user["id"]

    def counts(self):
        with self.database.connect() as c:
            return tuple(c.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in (
                "memory_claims", "memory_evidence", "memory_relations", "memory_items",
            ))

    def test_v13_upgrade_imports_final_delta_atomically(self):
        with self.database.connect() as c:
            c.execute("""INSERT INTO memory_items
                (id,category,content,status,confidence,metadata_json,created_at,updated_at)
                VALUES ('delta','fact','Delta Wissen','active',1,'{}','2026','2026')""")
            c.execute("PRAGMA user_version=13")
        self.database = EveDatabase(self.database.path)
        with self.database.connect() as c:
            self.assertEqual(SCHEMA_VERSION, c.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual(1, c.execute(
                "SELECT count(*) FROM memory_legacy_mappings WHERE legacy_memory_id='delta'"
            ).fetchone()[0])
            state = c.execute("SELECT * FROM memory_runtime_state WHERE singleton=1").fetchone()
            self.assertEqual(("v2", 0, 0), tuple(state[key] for key in (
                "memory_backend", "legacy_writes_enabled", "legacy_productive_reads_enabled"
            )))

    def test_productive_create_same_claim_and_compiler_end_to_end(self):
        first_turn, _ = self.turn("Ich bevorzuge morgens Haferbrei.", 1)
        pipeline = ProductiveLearningPipeline(
            self.database, FakeLearningLLM(lambda context: claim_proposal(context))
        )
        pipeline.accept_turn(first_turn)
        result = pipeline.process_turn(first_turn)
        self.assertEqual("create_active", result["decision_type"])
        self.assertEqual((1, 1, 0, 0), self.counts())

        second_turn, _ = self.turn("Ich bevorzuge morgens weiterhin Haferbrei.", 2)
        pipeline.accept_turn(second_turn)
        second = pipeline.process_turn(second_turn)
        self.assertEqual("append_supporting_evidence", second["decision_type"])
        self.assertEqual((1, 2, 0, 0), self.counts())
        repeated = pipeline.process_turn(second_turn)
        self.assertTrue(repeated["idempotent"])
        self.assertEqual((1, 2, 0, 0), self.counts())

        runtime = MemoryV2Runtime(self.database, MemoryCompiler(self.database))
        view = runtime.compile_view("Was bevorzuge ich morgens?", "answer")
        self.assertEqual("would_present", view["status"])
        self.assertIn("Haferbrei", view["rendered_view"])

    def test_productive_learning_cannot_attach_user_evidence_to_runtime_claim(self):
        RuntimeSelfKnowledgeSync(self.database).sync([RuntimeSelfDescription(
            "local_files.read", "local_files.read",
            "Ich kann freigegebene lokale Dateien suchen und lesen.",
            "LocalFileCapability", "search_files,read_text",
        )])
        with self.database.connect() as connection:
            runtime_claim = dict(connection.execute(
                "SELECT * FROM memory_claims WHERE scope='provider:runtime'"
            ).fetchone())
            evidence_before = connection.execute(
                "SELECT count(*) FROM memory_evidence WHERE claim_id=?", (runtime_claim["id"],)
            ).fetchone()[0]
        turn_id, _ = self.turn("Du kannst keine lokalen Dateien lesen.", 30)

        def contradict_runtime(context):
            candidate = next(item for item in context["claim_candidates"] if item["id"] == runtime_claim["id"])
            return {
                "decision_type": "append_contradicting_evidence",
                "memory_worthy": True,
                "reason_code": "test_runtime_ownership",
                "uncertainty": 0.0,
                "clarification_recommended": False,
                "authority": "user_direct",
                "temporal_class": "stable",
                "change_type": None,
                "claim": None,
                "evidence": [{
                    "source_type": "user_message",
                    "source_id": context["user_message"]["id"],
                    "stance": "contradicts",
                    "property": None,
                    "external_reference": None,
                }],
                "matched_claim_ids": [candidate["id"]],
                "relations": [],
            }

        result = ProductiveLearningPipeline(
            self.database, FakeLearningLLM(contradict_runtime),
        ).process_turn(turn_id)

        self.assertEqual("shadow_error", result["decision_type"])
        with self.database.connect() as connection:
            claim_after = dict(connection.execute(
                "SELECT * FROM memory_claims WHERE id=?", (runtime_claim["id"],)
            ).fetchone())
            evidence_after = connection.execute(
                "SELECT count(*) FROM memory_evidence WHERE claim_id=?", (runtime_claim["id"],)
            ).fetchone()[0]
        self.assertEqual(runtime_claim, claim_after)
        self.assertEqual(evidence_before, evidence_after)

    def test_productive_learning_cannot_supersede_runtime_claim(self):
        RuntimeSelfKnowledgeSync(self.database).sync([RuntimeSelfDescription(
            "local_files.read", "local_files.read",
            "Ich kann freigegebene lokale Dateien suchen und lesen.",
            "LocalFileCapability", "search_files,read_text",
        )])
        with self.database.connect() as connection:
            runtime_claim = dict(connection.execute(
                "SELECT * FROM memory_claims WHERE scope='provider:runtime'"
            ).fetchone())
        turn_id, _ = self.turn("Du kannst keine lokalen Dateien lesen.", 31)

        def supersede_runtime(context):
            candidate = next(item for item in context["claim_candidates"] if item["id"] == runtime_claim["id"])
            return {
                "decision_type": "supersede_claim",
                "memory_worthy": True,
                "reason_code": "test_runtime_ownership",
                "uncertainty": 0.0,
                "clarification_recommended": False,
                "authority": "user_direct",
                "temporal_class": "stable",
                "change_type": "correction",
                "claim": {
                    "kind": candidate["kind"],
                    "scope": candidate["scope"],
                    "canonical_key": candidate["canonical_key"],
                    "slot_key": candidate["slot_key"],
                    "lifecycle": "active",
                    "display_text": "Ich kann keine lokalen Dateien lesen.",
                    "payload": {},
                    "valid_from": None,
                    "valid_until": None,
                },
                "evidence": [{
                    "source_type": "user_message",
                    "source_id": context["user_message"]["id"],
                    "stance": "supports",
                    "property": None,
                    "external_reference": None,
                }],
                "matched_claim_ids": [candidate["id"]],
                "relations": [{"relation_type": "supersedes", "target_claim_id": candidate["id"]}],
            }

        result = ProductiveLearningPipeline(
            self.database, FakeLearningLLM(supersede_runtime),
        ).process_turn(turn_id)

        self.assertEqual("shadow_error", result["decision_type"])
        with self.database.connect() as connection:
            claims = [dict(row) for row in connection.execute("SELECT * FROM memory_claims").fetchall()]
            relations = connection.execute("SELECT count(*) FROM memory_relations").fetchone()[0]
        self.assertEqual([runtime_claim], claims)
        self.assertEqual(0, relations)

    def test_productive_no_persist_and_atomic_failure(self):
        turn_id, _ = self.turn("Hallo EVE", 1)
        pipeline = ProductiveLearningPipeline(
            self.database, FakeLearningLLM(lambda context: claim_proposal(context, decision="no_persist"))
        )
        pipeline.accept_turn(turn_id)
        result = pipeline.process_turn(turn_id)
        self.assertEqual("no_persist", result["decision_type"])
        self.assertEqual((0, 0, 0, 0), self.counts())

        failing_turn, _ = self.turn("Ich bevorzuge morgens Haferbrei.", 2)
        with self.database.connect() as c:
            c.execute("""CREATE TRIGGER fail_productive_evidence BEFORE INSERT ON memory_evidence
                         WHEN new.evidence_type='user_message' BEGIN SELECT RAISE(ABORT,'test'); END""")
        failing_pipeline = ProductiveLearningPipeline(
            self.database, FakeLearningLLM(lambda context: claim_proposal(context))
        )
        failing_pipeline.accept_turn(failing_turn)
        failed = failing_pipeline.process_turn(failing_turn)
        self.assertEqual("shadow_error", failed["decision_type"])
        self.assertEqual((0, 0, 0, 0), self.counts())
        with self.database.connect() as c:
            self.assertEqual("failed", c.execute(
                "SELECT status FROM memory_learning_jobs WHERE turn_id=?", (failing_turn,)
            ).fetchone()[0])

    def test_v2_runtime_never_reads_legacy_items(self):
        with self.database.connect() as c:
            c.execute("""INSERT INTO memory_items
                (id,category,content,status,confidence,metadata_json,created_at,updated_at)
                VALUES ('legacy-only','fact','Geheimes Legacy Zebra','active',1,'{}','2026','2026')""")
        runtime = MemoryV2Runtime(self.database, MemoryCompiler(self.database))
        self.assertEqual([], runtime.retrieve("Legacy Zebra"))

    def test_v2_local_search_uses_compiler_relevance(self):
        first_turn, _ = self.turn("Das Projekt trägt die Kennung Bernstein-Kompass.", 1)
        pipeline = ProductiveLearningPipeline(
            self.database, FakeLearningLLM(lambda context: {
                **claim_proposal(context, value="Bernstein-Kompass"),
                "claim": {
                    **claim_proposal(context, value="Bernstein-Kompass")["claim"],
                    "canonical_key": "v2:project:phase4:kennung",
                    "slot_key": "v2:project:phase4:kennung",
                    "scope": "project:phase4",
                    "display_text": "Das Projekt trägt die Kennung Bernstein-Kompass.",
                    "payload": {"subject": "project:phase4", "property": "kennung", "value": "Bernstein-Kompass"},
                },
            }),
        )
        pipeline.process_turn(first_turn)
        unrelated_turn, _ = self.turn("EVE soll Octoprint verwenden.", 2)
        ProductiveLearningPipeline(
            self.database, FakeLearningLLM(lambda context: {
                **claim_proposal(context, value="Octoprint"),
                "claim": {
                    **claim_proposal(context, value="Octoprint")["claim"],
                    "canonical_key": "v2:device:printer:camera_action",
                    "slot_key": "v2:device:printer:camera_action",
                    "scope": "device:printer",
                    "display_text": "EVE soll für den Drucker Octoprint verwenden.",
                    "payload": {"subject": "device:printer", "property": "camera_action", "value": "Octoprint"},
                },
            }),
        ).process_turn(unrelated_turn)
        runtime = MemoryV2Runtime(self.database, MemoryCompiler(self.database))
        results = PersistentSearch(
            self.database, memory_runtime=runtime,
        ).knowledge("Welche Kennung trägt das Projekt?", limit=10)
        self.assertEqual(1, len(results))
        self.assertIn("Bernstein-Kompass", results[0]["content"])
        self.assertNotIn("Octoprint", results[0]["content"])

    def test_supersession_is_atomic_and_historical(self):
        first_turn, _ = self.turn("Ich bevorzuge morgens Haferbrei.", 1)
        ProductiveLearningPipeline(
            self.database, FakeLearningLLM(lambda context: claim_proposal(context))
        ).process_turn(first_turn)
        with self.database.connect() as c:
            old_id = c.execute("SELECT id FROM memory_claims").fetchone()[0]

        correction_turn, _ = self.turn("Korrektur: Morgens bevorzuge ich Müsli.", 2)
        pipeline = ProductiveLearningPipeline(self.database, FakeLearningLLM(
            lambda context: claim_proposal(
                context, value="Müsli", decision="supersede_claim",
                matched=[old_id], change_type="correction",
            )
        ))
        result = pipeline.process_turn(correction_turn)
        self.assertEqual("supersede_claim", result["decision_type"], result)
        with self.database.connect() as c:
            self.assertEqual("retired", c.execute(
                "SELECT lifecycle FROM memory_claims WHERE id=?", (old_id,)
            ).fetchone()[0])
            self.assertEqual(1, c.execute(
                "SELECT count(*) FROM memory_claims WHERE lifecycle='active'"
            ).fetchone()[0])
            self.assertEqual(1, c.execute(
                "SELECT count(*) FROM memory_relations WHERE relation_type='supersedes'"
            ).fetchone()[0])
            self.assertEqual(3, c.execute("SELECT count(*) FROM memory_evidence").fetchone()[0])
        runtime = MemoryV2Runtime(self.database, MemoryCompiler(self.database))
        current = runtime.compile_view("Was bevorzuge ich morgens?", "answer")
        self.assertIn("Müsli", current["rendered_view"])
        self.assertNotIn("Haferbrei", current["rendered_view"])

    def test_supersession_tolerates_model_reusing_slot_as_canonical_key(self):
        first_turn, _ = self.turn("Ich bevorzuge morgens Haferbrei.", 1)
        ProductiveLearningPipeline(
            self.database, FakeLearningLLM(lambda context: claim_proposal(context))
        ).process_turn(first_turn)
        with self.database.connect() as c:
            old = dict(c.execute("SELECT id,canonical_key FROM memory_claims").fetchone())

        def corrected(context):
            proposal = claim_proposal(
                context, value="Kupfer-Leuchtturm", decision="supersede_claim",
                matched=[old["id"]], change_type="correction",
            )
            proposal["claim"]["canonical_key"] = old["canonical_key"]
            return proposal

        correction_turn, _ = self.turn("Korrektur: Morgens bevorzuge ich Kupfer-Leuchtturm.", 2)
        result = ProductiveLearningPipeline(
            self.database, FakeLearningLLM(corrected),
        ).process_turn(correction_turn)
        self.assertEqual("supersede_claim", result["decision_type"], result)
        with self.database.connect() as c:
            rows = c.execute(
                "SELECT lifecycle,canonical_key FROM memory_claims ORDER BY created_at"
            ).fetchall()
            self.assertEqual(["retired", "active"], [row["lifecycle"] for row in rows])
            self.assertNotEqual(rows[0]["canonical_key"], rows[1]["canonical_key"])
            self.assertEqual(1, c.execute("SELECT count(*) FROM memory_relations").fetchone()[0])

    def test_candidate_is_not_productive_and_pending_job_survives_restart(self):
        turn_id, _ = self.turn("Vielleicht bevorzuge ich morgens Haferbrei.", 1)
        first = ProductiveLearningPipeline(
            self.database, FakeLearningLLM(
                lambda context: claim_proposal(context, decision="create_candidate", lifecycle="candidate")
            ),
        )
        first.accept_turn(turn_id)
        restarted = ProductiveLearningPipeline(self.database, first.llm)
        self.assertEqual([turn_id], restarted.pending_turns())
        restarted.process_turn(turn_id)
        runtime = MemoryV2Runtime(self.database, MemoryCompiler(self.database))
        self.assertEqual([], runtime.retrieve("Was bevorzuge ich morgens?"))
        with self.database.connect() as c:
            self.assertEqual("candidate", c.execute(
                "SELECT lifecycle FROM memory_claims"
            ).fetchone()[0])

    def test_fts_failure_rolls_back_truth(self):
        turn_id, _ = self.turn("Ich bevorzuge morgens Haferbrei.", 1)
        with self.database.connect() as c:
            c.execute("DROP TABLE memory_claims_fts")
        pipeline = ProductiveLearningPipeline(
            self.database, FakeLearningLLM(lambda context: claim_proposal(context))
        )
        result = pipeline.process_turn(turn_id)
        self.assertEqual("shadow_error", result["decision_type"])
        self.assertEqual((0, 0, 0, 0), self.counts())


if __name__ == "__main__":
    unittest.main()
