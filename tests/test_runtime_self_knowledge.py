import json
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eve_agent.cli import build
from eve_agent.config import DEFAULTS
from eve_agent.runtime_self_knowledge import (
    RuntimeSelfDescription,
    RuntimeSelfKnowledgeSync,
    collect_runtime_self_descriptions,
)
from eve_agent.storage import EveDatabase, SCHEMA_VERSION
from eve_agent.scheduler import ScheduledTasks
from eve_agent.memory_compiler import MemoryCompiler, MemoryNeed
from eve_agent.memory_v2 import MemoryV2Runtime


def description(runtime_id="provider.search", capability_id="search", statement="Ich kann suchen.",
                component="Provider", operation="search"):
    return RuntimeSelfDescription(runtime_id, capability_id, statement, component, operation)


class _Component:
    @staticmethod
    def self_descriptions():
        return [description()]


class _Runtime:
    def __init__(self):
        self.component = _Component()
        self.unregistered = object()


class RuntimeSelfKnowledgeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = EveDatabase(Path(self.temporary.name) / "eve.db")
        self.sync = RuntimeSelfKnowledgeSync(self.database)

    def tearDown(self):
        self.temporary.cleanup()

    def _rows(self, table):
        with self.database.connect() as connection:
            return [dict(row) for row in connection.execute(f"SELECT * FROM {table}").fetchall()]

    def _sync_retrieval_fixture(self):
        self.sync.sync([
            description(
                "local_files.read", "local_files.read",
                "Ich kann freigegebene lokale Dateien suchen, lesen und als Ressource öffnen.",
                "LocalFileCapability", "search_files,read_text,open_resource",
            ),
            description(
                "work_tasks.context", "tasks.context",
                "Ich kann Arbeitsaufgaben mit Chat-Kontext verknüpfen.",
                "WorkTaskCapability", "add_context_link",
            ),
            description(
                "web.research", "web.research",
                "Ich kann das Web durchsuchen und öffentliche Seiten lesen.",
                "WebResearch", "search,read_urls",
            ),
            description(
                "memory.search", "memory.search",
                "Ich kann gespeichertes Wissen durchsuchen und abrufen.",
                "MemoryV2Runtime", "compile_view,retrieve",
            ),
        ])
        compiler = MemoryCompiler(self.database)
        return MemoryV2Runtime(self.database, compiler), compiler

    @staticmethod
    def _runtime_claims(view):
        return [claim for claim in view["claims"] if claim["scope"] == "provider:runtime"]

    def test_collects_only_descriptions_exposed_by_assembled_runtime(self):
        self.assertEqual([description()], collect_runtime_self_descriptions(_Runtime()))

    def test_initial_sync_persists_claim_and_exact_provider_provenance(self):
        result = self.sync.sync([description()])
        self.assertEqual(1, result["created"])
        claim = self._rows("memory_claims")[0]
        self.assertEqual("provider:runtime", claim["scope"])
        self.assertEqual("active", claim["lifecycle"])
        self.assertTrue(json.loads(claim["payload_json"])["runtime_self_knowledge"])
        observation = self._rows("memory_observations")[0]
        self.assertEqual("provider", observation["source_role"])
        self.assertEqual("provider_result", observation["source_type"])
        self.assertEqual("provider.search", observation["external_ref"])
        evidence = self._rows("memory_evidence")[0]
        self.assertEqual("runtime_self_knowledge", evidence["evidence_type"])
        self.assertEqual("provider.search", evidence["source_ref"])

    def test_restart_is_idempotent(self):
        self.sync.sync([description()])
        result = RuntimeSelfKnowledgeSync(self.database).sync([description()])
        self.assertEqual(1, result["unchanged"])
        self.assertEqual(1, len(self._rows("memory_claims")))
        self.assertEqual(1, len(self._rows("memory_observations")))
        self.assertEqual(1, len(self._rows("memory_evidence")))

    def test_changed_statement_supersedes_old_claim(self):
        self.sync.sync([description()])
        result = self.sync.sync([description(statement="Ich kann sehr genau suchen.")])
        self.assertEqual(1, result["superseded"])
        claims = {row["display_text"]: row for row in self._rows("memory_claims")}
        self.assertEqual("retired", claims["Ich kann suchen."]["lifecycle"])
        self.assertEqual("active", claims["Ich kann sehr genau suchen."]["lifecycle"])
        relation = self._rows("memory_relations")[0]
        self.assertEqual("supersedes", relation["relation_type"])
        self.assertEqual(claims["Ich kann sehr genau suchen."]["id"], relation["from_claim_id"])

    def test_new_capability_is_added_without_changing_existing_claim(self):
        self.sync.sync([description()])
        first_id = self._rows("memory_claims")[0]["id"]
        result = self.sync.sync([
            description(),
            description("provider.read", "read", "Ich kann lesen.", operation="read"),
        ])
        self.assertEqual(1, result["created"])
        self.assertEqual(1, result["unchanged"])
        claims = self._rows("memory_claims")
        self.assertEqual(2, len(claims))
        self.assertIn(first_id, {row["id"] for row in claims})

    def test_removed_last_source_retires_but_return_reactivates(self):
        self.sync.sync([description()])
        self.assertEqual(1, self.sync.sync([])["unsupported"])
        self.assertEqual("retired", self._rows("memory_claims")[0]["lifecycle"])
        self.sync.sync([description()])
        self.assertEqual(1, len(self._rows("memory_claims")))
        self.assertEqual("active", self._rows("memory_claims")[0]["lifecycle"])
        self.assertIsNone(self._rows("memory_evidence")[0]["effective_until"])

    def test_claim_remains_while_another_runtime_source_supports_it(self):
        sources = [description("a.search"), description("b.search")]
        self.sync.sync(sources)
        self.sync.sync([sources[1]])
        claim = self._rows("memory_claims")[0]
        self.assertEqual("active", claim["lifecycle"])
        active_evidence = [row for row in self._rows("memory_evidence") if row["effective_until"] is None]
        self.assertEqual(["b.search"], [row["source_ref"] for row in active_evidence])

    def test_changed_source_contract_replaces_only_its_evidence(self):
        self.sync.sync([description(operation="search")])
        self.sync.sync([description(operation="search,read")])
        evidence = self._rows("memory_evidence")
        self.assertEqual(2, len(evidence))
        self.assertEqual(1, len([row for row in evidence if row["effective_until"] is None]))

    def test_runtime_claim_does_not_replace_same_user_statement(self):
        now = "2026-01-01T00:00:00+00:00"
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                    valid_from,verification_policy,created_at,updated_at)
                   VALUES ('user-claim','opaque_fact','user:self','user:search',?,'{}','active',
                           ?,'stable',?,?)""",
                (description().statement, now, now, now),
            )
        self.sync.sync([description()])
        claims = self._rows("memory_claims")
        self.assertEqual(2, len(claims))
        self.assertEqual({"user:self", "provider:runtime"}, {row["scope"] for row in claims})

    def test_independent_descriptions_are_not_composed_into_new_capabilities(self):
        self.sync.sync([
            description("web.search", "web", "Ich kann im Web suchen."),
            description("files.read", "files", "Ich kann Dateien lesen."),
        ])
        statements = {row["display_text"] for row in self._rows("memory_claims")}
        self.assertEqual({"Ich kann im Web suchen.", "Ich kann Dateien lesen."}, statements)

    def test_sync_keeps_schema_and_foreign_keys_intact(self):
        self.sync.sync([description()])
        with self.database.connect() as connection:
            self.assertEqual(SCHEMA_VERSION, connection.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual([], connection.execute("PRAGMA foreign_key_check").fetchall())

    def test_normal_writer_cannot_change_runtime_claim_payload_or_lifecycle(self):
        self.sync.sync([description()])
        claim = self._rows("memory_claims")[0]
        original = dict(claim)
        for operation in ("payload", "retire", "delete"):
            with self.subTest(operation=operation), self.assertRaises(PermissionError):
                with self.database.connect() as connection:
                    self.database.assert_runtime_self_knowledge_writable(
                        connection, claim_ids=[claim["id"]],
                    )
        with self.assertRaises(PermissionError):
            with self.database.connect() as connection:
                self.database.assert_runtime_self_knowledge_writable(connection, proposed_claim={
                    "scope": "provider:runtime", "payload": {"runtime_self_knowledge": True},
                })
        self.assertEqual(original, self._rows("memory_claims")[0])

    def test_normal_writer_cannot_attach_user_evidence_or_relations_to_runtime_claim(self):
        self.sync.sync([description()])
        claim = self._rows("memory_claims")[0]
        with self.assertRaises(PermissionError):
            with self.database.connect() as connection:
                self.database.assert_runtime_self_knowledge_writable(
                    connection, claim_ids=[claim["id"]],
                )
        with self.assertRaises(PermissionError):
            with self.database.connect() as connection:
                self.database.assert_runtime_self_knowledge_writable(
                    connection, claim_ids=[claim["id"]],
                )
        self.assertEqual(1, len(self._rows("memory_evidence")))
        self.assertEqual([], self._rows("memory_relations"))

    def test_normal_claims_remain_writable(self):
        now = "2026-01-01T00:00:00+00:00"
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                    valid_from,verification_policy,created_at,updated_at)
                   VALUES ('normal','opaque_fact','user:self','user:normal','Alt','{}','active',
                           ?,'stable',?,?)""",
                (now, now, now),
            )
            connection.execute(
                "UPDATE memory_claims SET display_text='Neu',updated_at=? WHERE id='normal'", (now,),
            )
        self.assertEqual("Neu", self._rows("memory_claims")[0]["display_text"])

    def test_specific_runtime_knowledge_is_compiled_through_normal_memory(self):
        runtime, _compiler = self._sync_retrieval_fixture()
        view = runtime.compile_view("Kannst du auf Dateien auf deinem Rechner zugreifen?", "answer")
        claims = self._runtime_claims(view)
        self.assertEqual(1, len(claims))
        self.assertIn("lokale Dateien", claims[0]["display_text"])
        self.assertIn("single_lexical_match", claims[0]["reasons"])
        self.assertIn("runtime_declared", view["rendered_view"])

    def test_free_phrasings_find_relevant_runtime_knowledge(self):
        runtime, _compiler = self._sync_retrieval_fixture()
        for query in (
            "Hast du Zugriff auf freigegebene lokale Dokumente?",
            "Ist es dir möglich, lokale Dateien zu lesen?",
        ):
            with self.subTest(query=query):
                claims = self._runtime_claims(runtime.compile_view(query, "answer"))
                self.assertTrue(any("lokale Dateien" in claim["display_text"] for claim in claims))

    def test_task_context_knowledge_is_compiled_without_creating_a_link(self):
        runtime, _compiler = self._sync_retrieval_fixture()
        before = len(self._rows("work_item_context_links"))
        view = runtime.compile_view("Kannst du Aufgaben mit alten Unterhaltungen verbinden?", "answer")
        self.assertTrue(any(
            "Chat-Kontext verknüpfen" in claim["display_text"]
            for claim in self._runtime_claims(view)
        ))
        self.assertEqual(before, len(self._rows("work_item_context_links")))

    def test_broad_question_gets_bounded_runtime_overview(self):
        runtime, _compiler = self._sync_retrieval_fixture()
        claims = self._runtime_claims(runtime.compile_view("Was kannst du eigentlich alles?", "answer"))
        self.assertGreaterEqual(len(claims), 3)
        self.assertLessEqual(len(claims), 10)
        self.assertTrue(all("bounded_semantic_set" in claim["reasons"] for claim in claims))

    def test_smalltalk_and_unknown_specific_ability_do_not_inject_runtime_claims(self):
        runtime, _compiler = self._sync_retrieval_fixture()
        for query in ("Moin EVE.", "Kannst du PDFs bearbeiten?"):
            with self.subTest(query=query):
                self.assertEqual([], self._runtime_claims(runtime.compile_view(query, "answer")))

    def test_home_read_query_does_not_receive_runtime_claim_flood(self):
        runtime, _compiler = self._sync_retrieval_fixture()
        claims = self._runtime_claims(runtime.compile_view("Wie warm ist es im Wohnzimmer?", "answer"))
        self.assertEqual([], claims)

    def test_normal_personal_memory_still_uses_same_retrieval(self):
        runtime, _compiler = self._sync_retrieval_fixture()
        now = "2026-01-01T00:00:00+00:00"
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                    valid_from,verification_policy,created_at,updated_at)
                   VALUES ('tesla-name','opaque_fact','user:self','user:tesla-name',?,'{}','active',
                           ?,'stable',?,?)""",
                ("Mein Tesla heißt Wattson.", now, now, now),
            )
        view = runtime.compile_view("Wie heißt mein Tesla?", "answer")
        self.assertTrue(any(claim["id"] == "tesla-name" for claim in view["claims"]))

    def test_preview_exposes_candidate_rejection_diagnostics(self):
        runtime, compiler = self._sync_retrieval_fixture()
        need = MemoryNeed(
            "answer", "Kannst du auf Dateien zugreifen?",
            scopes=runtime._scopes_for_query("Kannst du auf Dateien zugreifen?"),
        )
        view = compiler.preview(need)
        self.assertTrue(view["candidate_audit"])
        self.assertTrue(any(item["scope"] == "provider:runtime" for item in view["candidate_audit"]))

    def test_build_runs_sync_after_runtime_components_are_assembled(self):
        root = Path(self.temporary.name) / "runtime-root"
        root.mkdir()
        cfg = copy.deepcopy(DEFAULTS)
        cfg["paths"] = {
            "database": str(root / "data" / "eve.db"),
            "runtime": str(root / "runtime"),
        }

        def scheduler_without_threads(database, home_assistant, **_kwargs):
            return ScheduledTasks(database, home_assistant, start_monitor=False, title_normalizer=None)

        with patch("eve_agent.cli.ScheduledTasks", side_effect=scheduler_without_threads):
            _, _, _, agent, _ = build(root, cfg)
        self.assertGreater(agent.runtime_self_knowledge_report["descriptions"], 0)
        self.assertEqual(
            agent.runtime_self_knowledge_report["descriptions"],
            agent.runtime_self_knowledge_report["created"],
        )
        with agent.memory.database.connect() as connection:
            self.assertGreater(connection.execute(
                """SELECT count(*) FROM memory_claims
                   WHERE json_extract(payload_json,'$.runtime_self_knowledge')=1"""
            ).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
