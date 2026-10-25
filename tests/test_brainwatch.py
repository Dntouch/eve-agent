import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from eve_agent.brainwatch import (
    BrainwatchInspector, MEMORY_EXPLORER_JSON_BUDGET, MemoryExplorerInspector,
)
from eve_agent.storage import ConversationStore, EveDatabase
from eve_agent.memory_runtime_telemetry import MemoryRuntimeRecorder


class BrainwatchInspectorTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "eve.db"
        self.database = EveDatabase(self.path)
        self.store = ConversationStore(self.database)
        self.conversation = self.store.create("Kühlschrank und EVE")
        with self.database.connect() as db:
            db.execute(
                "INSERT INTO memory_items(id,content,category,status,confidence,created_at,updated_at,metadata_json) VALUES(?,?,?,?,?,?,?,?)",
                ("memory-1", "Der Kühlschrank besitzt eine E14-Lampe", "fact", "active", .9, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "{}"),
            )
        self.user, self.assistant = self.store.append_turn(
            self.conversation["id"], "Das Foto zeigt eine E14-Lampe.", "Ja, E14 ist erkennbar.",
            turn_id="turn-1", source_memory_ids=["memory-1"],
            memory_retrievals=[{"memory_id": "memory-1", "position": 0, "method": "hybrid", "score": .82}],
            knowledge_flow={"stages": [{"kind": "vision", "status": "observed"}]},
            assistant_metadata={"route": "web", "sources": [{"title": "Beispiel", "url": "https://Example.test/source#fragment", "snippet": "Kurz"}], "token": "must-not-leak"},
        )
        self.inspector = BrainwatchInspector(self.path)

    def snapshot(self):
        with closing(sqlite3.connect(self.path)) as db:
            return list(db.execute("SELECT id,content,metadata_json FROM messages ORDER BY ordinal")), list(db.execute("SELECT id,source_message_id FROM memory_items"))

    def test_search_is_namespaced_bounded_and_read_only(self):
        before = self.snapshot()
        result = self.inspector.search("Kühlschrank", limit=999)
        self.assertTrue(result["nodes"])
        self.assertTrue(all(":" in node["id"] for node in result["nodes"]))
        self.assertLessEqual(len(result["nodes"]), 30)
        self.assertEqual(before, self.snapshot())

    def test_new_turn_lineage_memory_origin_and_retrieval_are_real(self):
        graph = self.inspector.neighbors("turn:turn-1")
        relationships = {(edge["source"], edge["target"], edge["type"]) for edge in graph["edges"]}
        self.assertIn((f"message:{self.user['id']}", "turn:turn-1", "input_of"), relationships)
        self.assertIn(("turn:turn-1", f"message:{self.assistant['id']}", "output_of"), relationships)
        self.assertIn(("memory:memory-1", "turn:turn-1", "retrieved_for"), relationships)
        retrieval = next(edge for edge in graph["edges"] if edge["type"] == "retrieved_for")
        self.assertEqual("retrieval", retrieval["category"])
        self.assertEqual(.82, retrieval["metadata"]["score"])
        self.assertIn("keine Kausalitätsbehauptung", retrieval["metadata"]["evidence"])
        memory = self.inspector.neighbors("memory:memory-1")
        self.assertTrue(any(edge["source"] == f"message:{self.user['id']}" for edge in memory["edges"]))

    def test_historical_message_has_no_invented_turn(self):
        historical_user, _ = self.store.append_turn(self.conversation["id"], "Historisch", "Ohne Lineage")
        node = self.inspector.node(f"message:{historical_user['id']}")["nodes"][0]
        graph = self.inspector.neighbors(node["id"])
        self.assertFalse(node["metadata"]["turn_lineage_recorded"])
        self.assertFalse(any(edge["category"] in {"lineage", "retrieval"} for edge in graph["edges"]))

    def test_web_source_is_available_not_claimed_as_evidence_and_secrets_are_absent(self):
        graph = self.inspector.neighbors(f"message:{self.assistant['id']}")
        edge = next(edge for edge in graph["edges"] if edge["type"] == "source_available_for_message")
        self.assertNotEqual("used_as_evidence", edge["type"])
        encoded = json.dumps(graph, ensure_ascii=False)
        self.assertNotIn("must-not-leak", encoded)
        web = next(node for node in graph["nodes"] if node["type"] == "web-source")
        self.assertTrue(web["id"].startswith("web-source:"))
        self.assertEqual("example.test", web["metadata"]["host"])

    def test_paging_limits_and_allowlists(self):
        first = self.inspector.neighbors(f"conversation:{self.conversation['id']}", limit=1)
        self.assertEqual(1, len(first["edges"]))
        self.assertTrue(first["page"]["has_more"])
        second = self.inspector.neighbors(f"conversation:{self.conversation['id']}", cursor=first["page"]["next_cursor"], limit=1)
        self.assertNotEqual(first["edges"][0]["id"], second["edges"][0]["id"])
        with self.assertRaises(ValueError):
            self.inspector.neighbors("turn:turn-1", categories=["invented"])
        with self.assertRaises(ValueError):
            self.inspector.node("sqlite:messages")

    def test_database_connection_refuses_writes(self):
        connection = self.inspector._connect()
        self.addCleanup(connection.close)
        with self.assertRaises(sqlite3.OperationalError):
            connection.execute("DELETE FROM messages")


class WorkingMemoryGraphTest(unittest.TestCase):
    def setUp(self):
        from eve_agent.working_memory import WorkingMemoryStore
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = EveDatabase(Path(self.temp.name) / 'eve.db')
        self.work = WorkingMemoryStore(self.database)
        self.inspector = MemoryExplorerInspector(self.database.path)

    def make_work(self, retention='temporary_learning', calls=1):
        from datetime import datetime, timezone
        wid = self.work.create(retention_class=retention)
        source_turn = 'learning-' + wid
        store = ConversationStore(self.database)
        conversation = store.create('Learning')
        store.append_turn(conversation['id'], 'Learn', 'Accepted', turn_id=source_turn)
        now = datetime.now(timezone.utc).isoformat()
        with self.database.connect() as c:
            c.execute("INSERT INTO memory_learning_jobs(turn_id,status,accepted_at,started_at,updated_at) "
                      "VALUES (?,'running',?,?,?)", (source_turn, now, now, now))
        tid, request = self.work.begin_turn(wid, None, {'private': 'DO-NOT-PUBLISH-CONTENT',
                                           'trace_id': 'conversation-learning:' + source_turn},
                                           'conversation-learning:' + source_turn)
        for i in range(calls):
            call = self.work.start_call(wid, tid, str(i), 'working_memory', 'read', 'read',
                                        {'reference': request['reference'], 'pointer': '/private'})
            self.work.finish_call(wid, tid, call, {'content': 'DO-NOT-PUBLISH-CONTENT'})
        return wid, tid, request

    def test_graph_contains_exact_work_objects_and_accesses_without_content_or_claims(self):
        wid, tid, request = self.make_work(calls=2)
        self.make_work(retention='standard')
        before = self.database.path.read_bytes()
        data = self.inspector.working_memory_graph()
        self.assertEqual(before, self.database.path.read_bytes())
        self.assertFalse(data['durable_claims'])
        self.assertNotIn('DO-NOT-PUBLISH-CONTENT', json.dumps(data))
        self.assertEqual({node['workspace_id'] for node in data['nodes']}, {wid})
        self.assertEqual(len(data['nodes']), 5)
        self.assertEqual(len(data['edges']), 4)
        self.assertEqual(len(data['events']), 2)
        self.assertEqual(data['turns'][0]['reads'], 2)
        ids = {node['id'] for node in data['nodes']}
        for edge in data['edges']:
            self.assertIn(edge['from_claim_id'], ids)
            self.assertIn(edge['to_claim_id'], ids)
        self.assertIn('work:' + request['reference'], ids)

    def test_recent_projection_is_bounded_and_old_completed_work_disappears(self):
        _, tid, _ = self.make_work(calls=20)
        data = self.inspector.working_memory_graph()
        self.assertEqual(data['turns'][0]['reads'], 20)
        self.assertEqual(data['turns'][0]['shown_calls'], 12)
        self.assertLessEqual(len(json.dumps(data, ensure_ascii=False).encode()), MEMORY_EXPLORER_JSON_BUDGET)
        with self.database.connect() as c:
            c.execute("UPDATE memory_work_turns SET status='completed',updated_at='2000-01-01' WHERE id=?", (tid,))
        self.assertEqual(self.inspector.working_memory_graph()['nodes'], [])

    def test_transport_budget_keeps_whole_calls_with_resolvable_endpoints(self):
        for _ in range(3):
            self.make_work(calls=15)
        data = self.inspector.working_memory_graph()
        self.assertLessEqual(len(json.dumps(data, ensure_ascii=False).encode()), MEMORY_EXPLORER_JSON_BUDGET)
        ids = {node['id'] for node in data['nodes']}
        edges = {edge['id'] for edge in data['edges']}
        for event in data['events']:
            self.assertTrue(set(event['node_ids']) <= ids)
            self.assertTrue(set(event['edge_ids']) <= edges)
        self.assertEqual(sum(turn['shown_calls'] for turn in data['turns']), len(data['events']))

    def test_observation_reference_resolves_to_canonical_work_object(self):
        wid, tid, request = self.make_work()
        call = self.work.start_call(wid, tid, 'observation', 'working_memory', 'read', 'read',
                                   {'reference': request['observation_id']})
        self.work.finish_call(wid, tid, call, {'content': 'private'})
        data = self.inspector.working_memory_graph()
        root = next(node for node in data['nodes'] if node['id'] == 'work:' + request['reference'])
        self.assertEqual(root['object_id'], request['reference'])
        self.assertEqual(sum(edge['from_claim_id'] == root['id'] for edge in data['edges']), 2)

    def test_restarted_attempt_excludes_abandoned_running_work(self):
        _, tid, _ = self.make_work()
        with self.database.connect() as c:
            c.execute("UPDATE memory_learning_jobs SET started_at='2999-01-01'")
        self.assertEqual(self.inspector.working_memory_graph()['nodes'], [])
        with self.database.connect() as c:
            c.execute("UPDATE memory_learning_jobs SET started_at='2000-01-01',status='failed'")
        self.assertEqual(self.inspector.working_memory_graph()['nodes'], [])


class MemoryExplorerInspectorTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "eve.db"
        self.database = EveDatabase(self.path)
        self.store = ConversationStore(self.database)
        self.conversation = self.store.create("Memory-Navigation")
        self.turn_a_user, self.turn_a_assistant = self.store.append_turn(
            self.conversation["id"], "Turn A", "Antwort A", turn_id="turn-a",
        )
        self.turn_b_user, self.turn_b_assistant = self.store.append_turn(
            self.conversation["id"], "Turn B", "Antwort B", turn_id="turn-b",
        )
        self.inspector = MemoryExplorerInspector(self.path)
        claims = [
            ("claim-a", "opaque_fact", "user:self", "fact:a", None, "Alpha Erinnerung",
             '{"profile":{"password":"must-not-leak","note":"sichtbar"},"url":"https://user:secret@example.test/path?token=bad#part"}',
             "active", None, None, "stable", "2026-01-01", "2026-01-04"),
            ("claim-b", "provider_binding", "provider:test", "binding:b", "device.b",
             "Beta Bindung", '{"provider":"test","external_reference":"device.b"}',
             "retired", "2026-01-01", "2026-01-03", "configuration", "2026-01-02", "2026-01-04"),
            ("claim-c", "alias", "household:default", "alias:c", "alias:c",
             "Gamma Alias", '{"alias":"Gamma","target":"device.b"}',
             "candidate", None, None, "unknown", "2026-01-03", "2026-01-03"),
            ("claim-d", "opaque_fact", "project:test", "fact:d", None, "Delta ohne Relation",
             '{}', "invalid", None, None, "dynamic", "2026-01-04", "2026-01-02"),
        ]
        with self.database.connect() as db:
            db.executemany(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,
                    lifecycle,valid_from,valid_until,verification_policy,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", claims,
            )
            db.executemany(
                """INSERT INTO memory_observations
                   (id,source_role,source_type,external_ref,excerpt,structured_value_json,
                    observed_at,scope,metadata_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [
                    ("obs-full", "external", "external", "fixture:full", "vollständig",
                     '{"authorization":"Bearer must-not-leak"}', "2026-01-05", "test", "{}", "2026-01-05"),
                    ("obs-partial", "unknown", "turn", None, "teilweise", "{}",
                     "2026-01-04", "test", "{}", "2026-01-04"),
                ],
            )
            db.executemany(
                """INSERT INTO memory_evidence
                   (id,claim_id,observation_id,stance,evidence_type,source_ref,excerpt,
                    payload_json,observed_at,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [
                    ("evidence-full", "claim-a", "obs-full", "supports", "external_fact",
                     "source:full", "API key: must-not-leak", '{"secret":"must-not-leak","result":"ok"}',
                     "2026-01-05", "2026-01-05"),
                    ("evidence-partial", "claim-a", "obs-partial", "supports", "turn_note",
                     None, None, '{}', "2026-01-04", "2026-01-04"),
                    ("evidence-none", "claim-a", None, "contradicts", "manual_note",
                     None, None, '{}', "2026-01-03", "2026-01-03"),
                ],
            )
            db.executemany(
                "INSERT INTO memory_relations(id,from_claim_id,to_claim_id,relation_type,evidence_id,created_at) VALUES (?,?,?,?,?,?)",
                [
                    ("relation-history", "claim-a", "claim-b", "supersedes", "evidence-full", "2026-01-06"),
                    ("relation-refines", "claim-c", "claim-a", "refines", None, "2026-01-05"),
                ],
            )

    def add_turn_link_fixture(self):
        evaluation_values = (
            "eval-a", "turn-a", "planner", "compiler-v", "retrieval-v", "eligibility-v",
            "projection-v", "budget-v", "snapshot", "config", "would_present", 100, 10,
            "test", 0, 2, 2, 1, 0, 0, 0, "view", "{}", "2026-02-08T12:00:00Z",
        )
        with self.database.connect() as db:
            db.execute(
                """INSERT INTO conversation_tool_events
                   (id,conversation_id,message_id,ordinal,tool,status,summary,input_json,result_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                ("tool-a", self.conversation["id"], self.turn_a_assistant["id"], 0,
                 "fixture", "success", "Test", "{}", "{}", "2026-02-01T12:00:00Z"),
            )

            db.executemany(
                """INSERT INTO memory_observations
                   (id,source_role,source_type,message_id,turn_id,tool_event_id,external_ref,
                    excerpt,structured_value_json,observed_at,scope,metadata_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    ("obs-turn-b", "user", "turn", None, "turn-b", None, None,
                     "Turn B", "{}", "2026-02-02", "test", "{}", "2026-02-02"),
                    ("obs-tool-a", "tool", "tool_event", None, None, "tool-a", None,
                     "Tool A", "{}", "2026-02-03", "test", "{}", "2026-02-03"),
                ],
            )
            db.executemany(
                """INSERT INTO memory_evidence
                   (id,claim_id,observation_id,stance,evidence_type,source_message_id,
                    source_turn_id,tool_event_id,source_ref,excerpt,payload_json,observed_at,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    ("e-direct-a", "claim-a", None, "supports", "dialog_occurrence", None,
                     "turn-a", None, "turn:a", None, "{}", "2026-02-04", "2026-02-04"),
                    ("e-message-b", "claim-a", None, "supports", "user_message",
                     self.turn_b_user["id"], None, None, "message:b", None, "{}",
                     "2026-02-05", "2026-02-05"),
                    ("e-observation-b", "claim-b", "obs-tool-a", "supports", "provider_result",
                     None, None, None, "tool:a", None, "{}", "2026-02-06", "2026-02-06"),
                    ("e-reuse-b", "claim-a", "obs-turn-b", "supports", "reuse_result", None,
                     "turn-b", None, "reuse", None, '{"token":"must-not-leak"}',
                     "2026-02-07", "2026-02-07"),
                ],
            )
            db.execute(
                """INSERT INTO memory_learning_decisions
                   (id,observation_id,decision_type,method,policy_version,model_version,
                    rationale,metadata_json,uncertainty,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                ("decision-a", "obs-turn-b", "append_supporting_evidence", "deterministic",
                 "policy", None, "stored", "{}", 0.1, "2026-02-08"),
            )
            db.execute(
                "INSERT INTO memory_learning_decision_claims(decision_id,claim_id) VALUES (?,?)",
                ("decision-a", "claim-b"),
            )
            db.execute(
                """INSERT INTO memory_learning_jobs
                   (turn_id,status,decision_id,attempt_count,error_class,accepted_at,started_at,
                    completed_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                ("turn-a", "applied", "decision-a", 1, None, "2026-02-08", "2026-02-08",
                 "2026-02-08", "2026-02-08"),
            )
            db.execute(
                """INSERT INTO memory_compiler_evaluations
                   (id,turn_id,consumer,compiler_version,retrieval_version,eligibility_version,
                    projection_version,budget_version,claim_snapshot,config_snapshot,status,
                    token_budget,token_count,token_method,required_overflow,candidate_count,
                    eligible_count,presented_count,legacy_count,legacy_token_count,
                    legacy_overlap_count,rendered_view,metrics_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                evaluation_values,
            )
            db.executemany(
                """INSERT INTO memory_compiler_claim_audit
                   (evaluation_id,claim_id,stage,method,reason,requirement_class,token_cost,rank_score)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [
                    ("eval-a", "claim-a", "retrieved", "fts", "Authorization: Bearer must-not-leak", "useful", 3, 0.8),
                    ("eval-a", "claim-a", "would_present", "budget", "selected", "useful", 3, 0.8),
                ],
            )
            db.executemany(
                """INSERT INTO memory_compiler_usage
                   (turn_id,consumer,claim_id,usage,created_at) VALUES (?,?,?,?,?)""",
                [
                    ("turn-a", "planner", "claim-a", "presented", "2026-02-09"),
                    ("turn-a", "planner", "claim-a", "used", "2026-02-09"),
                ],
            )

    def test_graph_revision_detects_edits_without_timestamp_or_count_change(self):
        before = self.inspector.graph_revision()
        self.assertEqual(before, self.inspector.graph_revision())
        with self.database.connect() as db:
            db.execute("UPDATE memory_claims SET display_text='Corrected' WHERE id='claim-a'")
        after = self.inspector.graph_revision()
        self.assertNotEqual(before, after)
        self.assertEqual(set(after), {"revision"})
        with self.database.connect() as db:
            db.execute("UPDATE memory_relations SET relation_type='refines'")
        self.assertNotEqual(after, self.inspector.graph_revision())

    def test_statistics_count_persisted_memory_home_assistant_and_tool_rows(self):
        with self.database.connect() as db:
            db.executemany(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,
                    lifecycle,verification_policy,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    ("ha-light", "provider_binding", "provider:home-assistant:test", "ha:light", "light.kitchen", "Küchenlicht",
                     '{"inventory_source":"home_assistant","provider_metadata":{"domain":"light","area":"Küche","availability":"unavailable"}}',
                     "active", "configuration", "2026-02-01", "2026-02-01"),
                    ("ha-language", "opaque_fact", "provider:home-assistant:language:de", "ha:language:light", None, "Licht-Sprachprofil",
                     '{"kind":"home_assistant_language_profile","domain":"light"}',
                     "active", "configuration", "2026-02-01", "2026-02-01"),
                ],
            )
            db.execute(
                "INSERT INTO memory_relations(id,from_claim_id,to_claim_id,relation_type,created_at) VALUES (?,?,?,?,?)",
                ("ha-grounding", "ha-light", "ha-language", "refines", "2026-02-01"),
            )
            db.executemany(
                """INSERT INTO conversation_tool_events
                   (id,conversation_id,message_id,ordinal,tool,status,summary,input_json,result_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [
                    (f"tool-{index}", self.conversation["id"], self.turn_a_assistant["id"], index,
                     "home_assistant" if index < 3 else "web", status, status, "{}", "{}", "2026-02-01")
                    for index, status in enumerate(("completed", "error", "rejected", "outcome_uncertain"))
                ],
            )
        result = self.inspector.statistics()
        self.assertEqual("persisted_database_rows", result["source"])
        self.assertEqual(6, result["memory"]["claims"])
        self.assertEqual(3, result["memory"]["relations"])
        self.assertEqual(1, result["home_assistant"]["active_entities"])
        self.assertEqual(1, result["home_assistant"]["relations"])
        self.assertEqual(1, result["home_assistant"]["language_profiles"])
        self.assertEqual({"name": "light", "entities": 1}, result["home_assistant"]["largest_domain"])
        self.assertEqual(4, result["tools"]["total"])
        self.assertEqual(1, result["tools"]["successful"])
        self.assertEqual(1, result["tools"]["failed"])
        self.assertEqual(1, result["tools"]["rejected"])
        self.assertEqual(1, result["tools"]["uncertain"])
        self.assertEqual(0.25, result["tools"]["success_rate"])
        self.assertEqual("home_assistant", result["fun_facts"]["busiest_tool"])
        self.assertEqual(2, result["fun_facts"]["most_connected_claim"]["relations"])

    def test_browse_without_query_and_stable_keyset_pagination(self):
        first = self.inspector.claims(limit=2)
        self.assertEqual(["claim:claim-b", "claim:claim-a"], [item["id"] for item in first["items"]])
        self.assertEqual("browse", first["search_mode"])
        self.assertTrue(first["page"]["has_more"])
        second = self.inspector.claims(limit=2, cursor=first["page"]["next_cursor"])
        self.assertEqual(["claim:claim-c", "claim:claim-d"], [item["id"] for item in second["items"]])
        self.assertFalse(second["page"]["has_more"])

    def test_search_filters_and_no_hits(self):
        result = self.inspector.claims(query="Beta", claim_kind="provider_binding",
                                       lifecycle="retired", scope="provider:test", limit=10)
        self.assertEqual(["claim:claim-b"], [item["id"] for item in result["items"]])
        self.assertEqual("fts", result["search_mode"])
        self.assertEqual([], self.inspector.claims(query="nichtvorhanden", limit=10)["items"])
        self.assertEqual(["claim:claim-d"], [item["id"] for item in
                         self.inspector.claims(verification_policy="dynamic", limit=10)["items"]])

    def test_empty_memory_is_a_valid_page(self):
        empty_path = Path(self.temp_dir.name) / "empty.db"
        EveDatabase(empty_path)
        result = MemoryExplorerInspector(empty_path).claims(limit=20)
        self.assertEqual([], result["items"])
        self.assertEqual({"limit": 20, "has_more": False, "next_cursor": None}, result["page"])

    def test_claim_detail_redacts_nested_payload_and_exposes_real_counts(self):
        result = self.inspector.claim("claim-a")
        claim = result["claim"]
        self.assertEqual("claim:claim-a", claim["id"])
        self.assertEqual("[REDACTED]", claim["payload"]["profile"]["password"])
        encoded = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("must-not-leak", encoded)
        self.assertNotIn("?token=bad", encoded)
        self.assertEqual({"evidence": 3, "relations_incoming": 1, "relations_outgoing": 1}, result["counts"])
        self.assertEqual("stored_supersedes_relations_only", result["history"]["basis"])
        self.assertFalse(result["history"]["complete_change_history_available"])
        self.assertEqual("memory-relation:relation-history", result["history"]["items"][0]["id"])

    def test_evidence_distinguishes_provenance_completeness_and_redacts(self):
        result = self.inspector.evidence("claim-a", limit=10)
        by_id = {item["evidence_id"]: item for item in result["items"]}
        self.assertEqual("available", by_id["evidence-full"]["provenance_status"])
        self.assertEqual("partial", by_id["evidence-partial"]["provenance_status"])
        self.assertEqual("not_recorded", by_id["evidence-none"]["provenance_status"])
        self.assertEqual("external", by_id["evidence-full"]["observation"]["source_type"])
        self.assertNotIn("must-not-leak", json.dumps(result))

    def test_relations_are_bidirectional_persisted_rows_with_evidence(self):
        result = self.inspector.relations("claim-a", limit=10)
        by_id = {item["relation_id"]: item for item in result["items"]}
        history = by_id["relation-history"]
        self.assertEqual("outgoing", history["direction"])
        self.assertEqual("supersedes", history["relation_type"])
        self.assertEqual("user:self", history["from_claim"]["scope"])
        self.assertEqual("provider_binding", history["to_claim"]["claim_kind"])
        self.assertEqual("evidence:evidence-full", history["evidence"]["id"])
        self.assertEqual("incoming", by_id["relation-refines"]["direction"])
        self.assertEqual("stored_relation_only", by_id["relation-refines"]["interpretation"])
        self.assertEqual([], self.inspector.relations("claim-d", limit=10)["items"])

    def test_memory_graph_projects_only_persisted_claims_and_relations(self):
        result = self.inspector.memory_graph(node_limit=4, edge_limit=10)
        self.assertEqual(
            {"claim:claim-a", "claim:claim-b", "claim:claim-c", "claim:claim-d"},
            {node["id"] for node in result["nodes"]},
        )
        self.assertEqual(
            {"memory-relation:relation-history", "memory-relation:relation-refines"},
            {edge["id"] for edge in result["edges"]},
        )
        self.assertIn("claim:claim-d", {node["id"] for node in result["nodes"]})
        self.assertTrue(all(edge["source_table"] == "memory_relations" for edge in result["edges"]))
        self.assertFalse(result["layout_contract"]["position_is_semantic"])
        self.assertFalse(result["layout_contract"]["activity_included"])
        self.assertLess(len(json.dumps(result, ensure_ascii=False).encode("utf-8")), 64 * 1024)
        self.assertNotIn("must-not-leak", json.dumps(result, ensure_ascii=False))

    def test_memory_graph_filters_paginates_and_binds_cursor(self):
        first = self.inspector.memory_graph(node_limit=2, edge_limit=10)
        self.assertTrue(first["page"]["has_more"])
        self.assertEqual(["claim:claim-d", "claim:claim-c"], [n["id"] for n in first["nodes"][:2]])
        second = self.inspector.memory_graph(
            node_limit=2, edge_limit=10, cursor=first["page"]["next_cursor"],
        )
        self.assertEqual(["claim:claim-b", "claim:claim-a"], [n["id"] for n in second["nodes"][:2]])
        scoped = self.inspector.memory_graph(scope="project:test", node_limit=10, edge_limit=10)
        self.assertEqual(["claim:claim-d"], [node["id"] for node in scoped["nodes"]])
        active_facts = self.inspector.memory_graph(
            claim_kind="opaque_fact", lifecycle="active", node_limit=10, edge_limit=10,
        )
        self.assertEqual(["claim:claim-a"], [node["id"] for node in active_facts["nodes"]])
        refined = self.inspector.memory_graph(
            relation_type="refines", node_limit=10, edge_limit=10,
        )
        self.assertEqual(["memory-relation:relation-refines"], [edge["id"] for edge in refined["edges"]])
        with self.assertRaises(ValueError):
            self.inspector.memory_graph(
                lifecycle="active", node_limit=2, edge_limit=10,
                cursor=first["page"]["next_cursor"],
            )

    def test_memory_graph_anchor_is_bounded_and_relation_exact(self):
        result = self.inspector.memory_graph(
            anchor_claim_id="claim-a", depth=1, node_limit=10, edge_limit=10,
        )
        self.assertEqual(
            {"claim:claim-a", "claim:claim-b", "claim:claim-c"},
            {node["id"] for node in result["nodes"]},
        )
        self.assertEqual(2, result["coverage"]["loaded_relations"])
        self.assertIsNone(result["page"]["next_cursor"])
        with self.assertRaises(ValueError):
            self.inspector.memory_graph(anchor_claim_id="claim-a", depth=4)
        with self.assertRaises(ValueError):
            self.inspector.memory_graph(anchor_claim_id="claim-a", lifecycle="retired")
        for kwargs in ({"node_limit": 401}, {"edge_limit": 801}, {"relation_type": "similar"}):
            with self.assertRaises(ValueError):
                self.inspector.memory_graph(**kwargs)

    def test_memory_graph_relations_pages_every_persisted_relation(self):
        first = self.inspector.memory_graph_relations(limit=1)
        self.assertEqual(2, first["matching_relations"])
        self.assertEqual(1, len(first["items"]))
        self.assertTrue(first["page"]["has_more"])
        second = self.inspector.memory_graph_relations(
            limit=1, cursor=first["page"]["next_cursor"],
        )
        self.assertEqual(1, len(second["items"]))
        self.assertFalse(second["page"]["has_more"])
        self.assertEqual(
            {"memory-relation:relation-history", "memory-relation:relation-refines"},
            {first["items"][0]["id"], second["items"][0]["id"]},
        )

    def test_invalid_parameters_and_cursor_binding_are_rejected(self):
        for kwargs in ({"claim_kind": "invented"}, {"lifecycle": "deleted"},
                       {"verification_policy": "sometimes"}, {"limit": 0}, {"scope": "bad\nvalue"}):
            with self.assertRaises(ValueError):
                self.inspector.claims(**kwargs)
        page = self.inspector.claims(limit=1)
        with self.assertRaises(ValueError):
            self.inspector.claims(limit=1, lifecycle="active", cursor=page["page"]["next_cursor"])
        with self.assertRaises(ValueError):
            self.inspector.relations("claim-a", relation_type="similar")

    def test_memory_explorer_connection_refuses_writes(self):
        connection = self.inspector._connect()
        self.addCleanup(connection.close)
        with self.assertRaises(sqlite3.OperationalError):
            connection.execute("UPDATE memory_claims SET lifecycle='retired'")

    def test_claim_turns_and_turn_memory_share_persisted_provenance(self):
        self.add_turn_link_fixture()
        claim_links = self.inspector.claim_turns("claim-a", limit=50)
        turn_links = self.inspector.turn_memory("turn-a", limit=50)
        claim_projection = {
            (item["claim_id"], item["turn_id"], item["origin_class"],
             item["source"]["persistent_source_id"], item["source"]["source_path"])
            for item in claim_links["items"] if item["turn_id"] == "turn:turn-a"
        }
        turn_projection = {
            (item["claim_id"], item["turn_id"], item["origin_class"],
             item["source"]["persistent_source_id"], item["source"]["source_path"])
            for item in turn_links["items"] if item["claim_id"] == "claim:claim-a"
        }
        self.assertEqual(claim_projection, turn_projection)
        self.assertTrue({
            "evidence_source_turn", "compiler_retrieved", "compiler_would_present",
            "usage_presented",
        } <= {item["origin_class"] for item in turn_links["items"]})
        self.assertFalse(any(item["compiler_stage"] == "used" for item in turn_links["items"]))
        self.assertFalse(turn_links["semantics"]["actual_use_proven"])
        self.assertFalse(turn_links["semantics"]["legacy_turn_memory_retrievals_included"])
        self.assertNotIn("must-not-leak", json.dumps(turn_links))
        retrieved = next(item for item in turn_links["items"]
                         if item["origin_class"] == "compiler_retrieved")
        self.assertIn("keine Aussage über Auswahl oder Verwendung", retrieved["interpretation"])
        selected = next(item for item in turn_links["items"]
                        if item["origin_class"] == "compiler_would_present")
        self.assertIn("kein sicherer Prompt-Nachweis", selected["interpretation"])

    def test_turn_links_resolve_message_tool_and_observation_references(self):
        self.add_turn_link_fixture()
        claim_a = self.inspector.claim_turns("claim-a", limit=50)
        self.assertNotIn(
            "evidence-none",
            {item["source"]["persistent_source_id"] for item in claim_a["items"]},
        )
        message = next(item for item in claim_a["items"]
                       if item["source"]["persistent_source_id"] == "e-message-b")
        self.assertEqual("turn:turn-b", message["turn_id"])
        self.assertEqual(f"message:{self.turn_b_user['id']}", message["source"]["message_id"])
        turn_a = self.inspector.turn_memory("turn-a", limit=50)
        observation = next(item for item in turn_a["items"]
                           if item["source"]["persistent_source_id"] == "obs-tool-a")
        self.assertEqual("claim:claim-b", observation["claim_id"])
        self.assertEqual("observation_turn", observation["origin_class"])
        self.assertEqual("tool-event:tool-a", observation["source"]["tool_event_id"])
        reuse = [item for item in claim_a["items"]
                 if item["origin_class"] == "semantic_reuse_result"]
        self.assertGreaterEqual(len(reuse), 2)
        self.assertNotIn("must-not-leak", json.dumps(reuse))

    def test_turn_links_keep_multiple_sources_and_support_bound_filters_and_pagination(self):
        self.add_turn_link_fixture()
        first = self.inspector.claim_turns("claim-a", limit=2)
        self.assertTrue(first["page"]["has_more"])
        second = self.inspector.claim_turns(
            "claim-a", limit=2, cursor=first["page"]["next_cursor"],
        )
        self.assertFalse({item["id"] for item in first["items"]} &
                         {item["id"] for item in second["items"]})
        selected = self.inspector.turn_memory(
            "turn-a", origin_class="compiler_would_present", consumer="planner", limit=10,
        )
        self.assertEqual(1, len(selected["items"]))
        self.assertEqual("would_present", selected["items"][0]["compiler_stage"])
        with self.assertRaises(ValueError):
            self.inspector.claim_turns("claim-a", origin_class="used")
        with self.assertRaises(ValueError):
            self.inspector.turn_memory("turn-a", consumer="unknown")
        with self.assertRaises(ValueError):
            self.inspector.claim_turns(
                "claim-a", origin_class="compiler_retrieved",
                cursor=first["page"]["next_cursor"],
            )

    def test_turn_links_handle_empty_and_missing_targets(self):
        self.assertEqual([], self.inspector.claim_turns("claim-d")["items"])
        with self.assertRaises(KeyError):
            self.inspector.claim_turns("missing")
        with self.assertRaises(KeyError):
            self.inspector.turn_memory("missing")

    def test_turn_link_payload_budget_preserves_keyset_pagination(self):
        self.add_turn_link_fixture()
        with self.database.connect() as db:
            db.executemany(
                """INSERT INTO memory_compiler_claim_audit
                   (evaluation_id,claim_id,stage,method,reason,requirement_class,token_cost,rank_score)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [
                    ("eval-a", "claim-a", "retrieved", "fixture", f"reason-{index}-" + "x" * 5000,
                     "optional", 5, 0.1)
                    for index in range(60)
                ],
            )
        first = self.inspector.claim_turns(
            "claim-a", origin_class="compiler_retrieved", limit=50,
        )
        self.assertIn("page", first)
        self.assertTrue(first["page"]["has_more"])
        self.assertLessEqual(
            len(json.dumps(first, ensure_ascii=False).encode("utf-8")),
            MEMORY_EXPLORER_JSON_BUDGET,
        )
        second = self.inspector.claim_turns(
            "claim-a", origin_class="compiler_retrieved", limit=50,
            cursor=first["page"]["next_cursor"],
        )
        self.assertFalse(
            {item["id"] for item in first["items"]}
            & {item["id"] for item in second["items"]},
        )

    def test_memory_events_project_real_sources_fidelity_and_redaction(self):
        self.add_turn_link_fixture()
        with self.database.connect() as db:
            db.executemany(
                """INSERT INTO memory_compiler_claim_audit
                   (evaluation_id,claim_id,stage,method,reason,requirement_class,token_cost,rank_score)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [
                    ("eval-a", "claim-b", "eligible", "rules", "eligible", "useful", 2, 0.5),
                    ("eval-a", "claim-b", "rejected", "rules", "secret=must-not-leak", "optional", 2, 0.4),
                    ("eval-a", "claim-b", "cancelled", "rules", "cancelled", None, None, None),
                    ("eval-a", "claim-b", "error", "rules", "error", None, None, None),
                ],
            )
        first = self.inspector.events(limit=50)
        kinds = {item["event_kind"] for item in first["items"]}
        self.assertTrue({
            "claim_created", "evidence_created", "observation_recorded", "relation_stored",
            "learning_decision", "learning_job_accepted", "learning_job_started",
            "learning_job_completed", "learning_job_updated", "compiler_evaluation",
            "compiler_retrieved", "compiler_eligible", "compiler_would_present",
            "compiler_rejected", "compiler_cancelled", "compiler_error",
            "usage_presented", "semantic_reuse_result",
        } <= kinds)
        self.assertEqual(
            {"direct_event", "state_timestamp", "derived_link"},
            {item["fidelity"] for item in first["items"]},
        )
        self.assertFalse(any(item["event_kind"] == "used" for item in first["items"]))
        self.assertFalse(any(item["compiler_stage"] == "used" for item in first["items"]))
        self.assertNotIn("must-not-leak", json.dumps(first))
        audit = [item for item in first["items"] if item["source_table"] == "memory_compiler_claim_audit"]
        self.assertEqual(len(audit), len({item["event_id"] for item in audit}))
        self.assertTrue(all(item["event_id"].startswith("memory-compiler-audit:") for item in audit))
        presented = next(item for item in first["items"] if item["event_kind"] == "usage_presented")
        self.assertFalse(presented["metadata"]["actual_prompt_inclusion_proven"])
        self.assertFalse(first["semantics"]["actual_use_proven"])

    def test_memory_events_filter_and_keyset_pagination_are_stable(self):
        self.add_turn_link_fixture()
        first = self.inspector.events(limit=4)
        repeated = self.inspector.events(limit=4)
        self.assertEqual(
            [item["event_id"] for item in first["items"]],
            [item["event_id"] for item in repeated["items"]],
        )
        second = self.inspector.events(limit=4, cursor=first["page"]["next_cursor"])
        self.assertTrue(first["page"]["has_more"])
        self.assertFalse({item["event_id"] for item in first["items"]} &
                         {item["event_id"] for item in second["items"]})
        timestamps = [item["timestamp"] for item in first["items"] + second["items"]]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))
        claim = self.inspector.events(claim_id="claim-a", fidelity="derived_link", limit=20)
        self.assertTrue(claim["items"])
        self.assertTrue(all("claim:claim-a" in item["claim_ids"] for item in claim["items"]))
        self.assertTrue(all(item["fidelity"] == "derived_link" for item in claim["items"]))
        turn = self.inspector.events(
            turn_id="turn-a", event_kind="compiler_would_present", consumer="planner",
            compiler_stage="would_present", scope="user:self", limit=20,
        )
        self.assertEqual(["compiler_would_present"], [item["event_kind"] for item in turn["items"]])
        window = self.inspector.events(
            timestamp_from="2026-02-08", timestamp_to="2026-02-08T23:59:59Z", limit=50,
        )
        self.assertTrue(window["items"])
        self.assertTrue(all("2026-02-08" <= item["timestamp"] <= "2026-02-08T23:59:59Z"
                            for item in window["items"]))

    def test_memory_events_validate_filters_and_handle_empty_or_missing_optional_sources(self):
        for kwargs in (
            {"event_kind": "used"}, {"fidelity": "guessed"}, {"consumer": "unknown"},
            {"compiler_stage": "presented"}, {"timestamp_from": "yesterday"},
            {"timestamp_from": "2026-02-02", "timestamp_to": "2026-01-01"},
            {"claim_id": "bad/id"},
        ):
            with self.assertRaises(ValueError):
                self.inspector.events(**kwargs)
        empty_path = Path(self.temp_dir.name) / "empty-events.db"
        EveDatabase(empty_path)
        self.assertEqual([], MemoryExplorerInspector(empty_path).events()["items"])
        with self.database.connect() as db:
            db.execute("DROP TABLE memory_compiler_usage")
        result = self.inspector.events(event_kind="usage_presented")
        self.assertEqual([], result["items"])

    def test_memory_events_payload_budget_preserves_cursor_with_large_audit(self):
        self.add_turn_link_fixture()
        with self.database.connect() as db:
            db.executemany(
                """INSERT INTO memory_compiler_claim_audit
                   (evaluation_id,claim_id,stage,method,reason,requirement_class,token_cost,rank_score)
                   VALUES (?,?,?,?,?,?,?,?)""",
                [
                    ("eval-a", "claim-a", "retrieved", "fixture", f"timeline-{index}-" + "x" * 5000,
                     "optional", 5, 0.1)
                    for index in range(60)
                ],
            )
        first = self.inspector.events(event_kind="compiler_retrieved", limit=50)
        self.assertTrue(first["page"]["has_more"])
        self.assertIsNotNone(first["page"]["next_cursor"])
        self.assertLessEqual(
            len(json.dumps(first, ensure_ascii=False).encode("utf-8")),
            MEMORY_EXPLORER_JSON_BUDGET,
        )
        second = self.inspector.events(
            event_kind="compiler_retrieved", limit=50, cursor=first["page"]["next_cursor"],
        )
        self.assertFalse({item["event_id"] for item in first["items"]} &
                         {item["event_id"] for item in second["items"]})

    def test_runtime_events_claim_counts_detail_and_turn_groups_use_persisted_facts(self):
        recorder = MemoryRuntimeRecorder(self.database, enabled=True)
        recorder.create_trace(trace_id="trace-runtime", started_at="2026-03-01T10:00:00Z")
        base = {
            "trace_id": "trace-runtime", "turn_id": "turn-a", "producer": "brainwatch-test",
            "event_status": "completed", "claim_id": "claim-a", "consumer": "planner",
        }
        events = [
            {**base, "event_kind": "claim_retrieved", "occurred_at": "2026-03-01T10:00:01Z",
             "operation_id": "retrieve", "proof_level": "compiler_evaluation",
             "compiler_evaluation_id": "evaluation-runtime", "details": {"retrieval_method": "exact"}},
            {**base, "event_kind": "claim_returned_to_consumer", "occurred_at": "2026-03-01T10:00:02Z",
             "operation_id": "retrieve", "proof_level": "consumer_boundary",
             "compiler_evaluation_id": "evaluation-runtime", "ordinal": 0, "details": {}},
            {**base, "event_kind": "claim_bound_to_plan", "occurred_at": "2026-03-01T10:00:03Z",
             "operation_id": "plan", "proof_level": "validated_binding",
             "planner_round_id": "round-runtime", "plan_id": "plan-runtime", "details": {}},
            {**base, "event_kind": "action_completed_with_claim", "occurred_at": "2026-03-01T10:00:04Z",
             "operation_id": "action", "proof_level": "action_result", "outcome_status": "success",
             "planner_round_id": "round-runtime", "plan_id": "plan-runtime",
             "action_id": "action-runtime", "action_index": 1, "provider": "home-assistant",
             "target_resource_id": "light.hall", "details": {"executor": "home-assistant"}},
            {"trace_id": "trace-runtime", "turn_id": "turn-a", "producer": "brainwatch-test",
             "event_status": "completed", "event_kind": "relation_traversed_for_retrieval",
             "occurred_at": "2026-03-01T10:00:05Z", "operation_id": "retrieve",
             "proof_level": "relation_traversal", "relation_id": "relation-history",
             "compiler_evaluation_id": "evaluation-runtime", "consumer": "planner", "details": {}},
        ]
        recorded = recorder.record_events(events)
        page = self.inspector.runtime_events(
            trace_id="trace-runtime", category="actions", sort="desc", limit=10,
        )
        self.assertEqual(["action_completed_with_claim"], [item["event_kind"] for item in page["items"]])
        self.assertEqual("runtime", page["items"][0]["event_source"])
        self.assertEqual("action_result", page["items"][0]["proof_level"])
        detail = self.inspector.runtime_event(recorded[3]["id"])
        self.assertTrue(detail["causal_targets"]["claim_id"]["persisted_target_exists"])
        self.assertEqual("action-runtime", detail["action_id"])
        claim = self.inspector.claim_runtime("claim-a", sort="asc", limit=20)
        self.assertEqual(1, claim["activity_counts"]["retrieval"])
        self.assertEqual(1, claim["activity_counts"]["consumer_return"])
        self.assertEqual(1, claim["activity_counts"]["plan_binding"])
        self.assertEqual(1, claim["activity_counts"]["successful_action"])
        self.assertEqual(1, claim["activity_counts"]["relation_traversal"])
        self.assertFalse(claim["semantics"]["universal_used_count"])
        turn = self.inspector.turn_runtime("turn-a", sort="asc", limit=20)
        self.assertEqual(["round-runtime"], turn["causal_groups"]["planner_round_id"])
        self.assertEqual("loaded_event_window_only", turn["semantics"]["groups_cover"])

    def test_runtime_events_allow_trace_without_turn_and_validate_filters(self):
        recorder = MemoryRuntimeRecorder(self.database, enabled=True)
        recorder.create_trace(trace_id="trace-no-turn", started_at="2026-03-02T10:00:00Z")
        recorder.record_event({
            "trace_id": "trace-no-turn", "event_kind": "operation_started",
            "occurred_at": "2026-03-02T10:00:01Z", "operation_id": "op-no-turn",
            "producer": "brainwatch-test", "proof_level": "operation_boundary",
            "event_status": "started", "details": {},
        })
        page = self.inspector.runtime_events(trace_id="trace-no-turn")
        self.assertIsNone(page["items"][0]["turn_id"])
        with self.assertRaises(ValueError):
            self.inspector.runtime_events(proof_level="guessed")
        with self.assertRaises(KeyError):
            self.inspector.runtime_event("missing")

    def test_turn_runtime_live_uses_persistence_cursor_and_public_projection(self):
        recorder = MemoryRuntimeRecorder(self.database, enabled=True)
        recorder.create_trace(trace_id="trace-live", started_at="2026-03-02T11:00:00Z")
        recorder.record_event({
            "trace_id": "trace-live", "turn_id": "turn-live", "producer": "brainwatch-test",
            "event_kind": "operation_started", "occurred_at": "2026-03-02T11:00:10Z",
            "operation_id": "already-there", "proof_level": "operation_boundary",
            "event_status": "started", "details": {},
        })
        tail = self.inspector.turn_runtime_live("turn:turn-live", tail=True, limit=10)
        self.assertEqual([], tail["items"])
        self.assertTrue(tail["semantics"]["persisted_events_only"])
        self.assertTrue(tail["semantics"]["late_writes_visible"])

        recorded = recorder.record_event({
            "trace_id": "trace-live", "turn_id": "turn-live", "producer": "brainwatch-test",
            "event_kind": "claim_retrieved", "occurred_at": "2026-03-02T11:00:01Z",
            "operation_id": "late-retrieval", "proof_level": "compiler_evaluation",
            "event_status": "completed", "claim_id": "claim-a",
            "compiler_evaluation_id": "evaluation-live", "consumer": "planner",
            "details": {"retrieval_method": "exact"},
        })
        page = self.inspector.turn_runtime_live(
            "turn-live", cursor=tail["page"]["poll_cursor"], limit=10,
        )
        self.assertEqual([f"runtime-event:{recorded['id']}"], [item["event_id"] for item in page["items"]])
        self.assertEqual(["claim:claim-a"], page["items"][0]["claim_ids"])
        self.assertEqual("turn:turn-live", page["items"][0]["turn_id"])

    def test_runtime_projection_obeys_response_budget_and_preserves_cursor(self):
        recorder = MemoryRuntimeRecorder(self.database, enabled=True)
        recorder.create_trace(trace_id="trace-budget", started_at="2026-03-03T10:00:00Z")
        recorder.record_events([{
            "trace_id": "trace-budget", "event_kind": "llm_transport_result",
            "occurred_at": f"2026-03-03T10:00:{index:02d}Z", "operation_id": f"transport-{index}",
            "producer": "brainwatch-test", "proof_level": "transport_result",
            "event_status": "completed", "outcome_status": "success",
            "llm_call_id": f"call-{index}", "attempt_id": f"attempt-{index}", "attempt_no": 1,
            "details": {"metrics": {f"metric_{metric}": metric for metric in range(60)}},
        } for index in range(60)])
        first = self.inspector.runtime_events(trace_id="trace-budget", limit=50)
        self.assertLessEqual(len(json.dumps(first, ensure_ascii=False).encode("utf-8")), 64 * 1024)
        self.assertTrue(first["page"]["has_more"])
        self.assertIsNotNone(first["page"]["next_cursor"])
        second = self.inspector.runtime_events(
            trace_id="trace-budget", limit=50, cursor=first["page"]["next_cursor"],
        )
        self.assertFalse({item["event_id"] for item in first["items"]} &
                         {item["event_id"] for item in second["items"]})
