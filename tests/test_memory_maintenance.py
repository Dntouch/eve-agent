import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from eve_agent.memory_maintenance import MemoryMaintenance
from eve_agent.storage import ConversationStore, EveDatabase


class MemoryMaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "eve.db"
        self.database = EveDatabase(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def claim(self, claim_id, *, value, slot="v2:user:self:drink", lifecycle="active",
              canonical=None, scope="user:self", subject="user:self", prop="drink"):
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES (?,'opaque_fact',?,?,?,?,?,?,'stable','2026-01-01','2026-01-01')""",
                (claim_id, scope, canonical or f"v2:{claim_id}", slot, f"{prop}: {value}",
                 json.dumps({"subject": subject, "property": prop, "value": value}), lifecycle),
            )

    def relation(self, relation_id, source, target, kind="supersedes"):
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_relations
                   (id,from_claim_id,to_claim_id,relation_type,created_at)
                   VALUES (?,?,?,?, '2026-01-01')""", (relation_id, source, target, kind),
            )

    def test_dry_run_detects_duplicate_without_product_mutation(self):
        self.claim("a", value="Tee", canonical="v2:drink:tea:a")
        self.claim("b", value="Tee", canonical="v2:drink:tea:b")
        maintenance = MemoryMaintenance(self.database)
        before = maintenance.product_digest()
        report = maintenance.start()
        self.assertEqual("completed", report["status"])
        self.assertEqual(before, maintenance.product_digest())
        duplicate = [item for item in report["findings"] if item["problem_class"] == "possible_duplicate"]
        self.assertEqual(1, len(duplicate))
        self.assertEqual("merge", duplicate[0]["proposed_action"])
        with self.database.connect() as connection:
            self.assertEqual(["active", "active"], [row[0] for row in connection.execute(
                "SELECT lifecycle FROM memory_claims ORDER BY id"
            )])

    def test_equal_provenance_labels_do_not_make_different_statements_duplicates(self):
        self.claim("a", value="Tee", slot=None)
        self.claim("b", value="Kaffee", slot=None)
        with self.database.connect() as connection:
            connection.execute("UPDATE memory_claims SET payload_json=?",
                               (json.dumps({"epistemic_kind": "user_instruction"}),))
        report = MemoryMaintenance(self.database).start()
        self.assertFalse(any(item["category"] == "same_structured_claim"
                             for item in report["findings"]))

    def test_active_conflict_but_correct_supersession_is_not_active_conflict(self):
        self.claim("a", value="Tee")
        self.claim("b", value="Kaffee", canonical="v2:drink:coffee")
        first = MemoryMaintenance(self.database).start()
        self.assertTrue(any(item["category"] == "active_slot_conflict" for item in first["findings"]))

        with self.database.connect() as connection:
            connection.execute("UPDATE memory_claims SET lifecycle='retired' WHERE id='a'")
        self.relation("r1", "b", "a")
        second = MemoryMaintenance(self.database).start()
        self.assertFalse(any(item["category"] == "active_slot_conflict" for item in second["findings"]))
        self.assertFalse(any(item["category"] == "inconsistent_supersession" for item in second["findings"]))

    def test_retired_intermediate_supersession_keeps_valid_history(self):
        self.claim("a", value="Tee", lifecycle="retired")
        self.claim("b", value="Kaffee", lifecycle="retired")
        self.claim("c", value="Wasser")
        self.relation("r1", "b", "a")
        self.relation("r2", "c", "b")
        report = MemoryMaintenance(self.database).start()
        self.assertFalse(any(item["category"] == "inconsistent_supersession"
                             for item in report["findings"]))
        # An inactive source without a current successor remains suspicious.
        with self.database.connect() as connection:
            connection.execute("UPDATE memory_claims SET lifecycle='retired' WHERE id='c'")
        report = MemoryMaintenance(self.database).start()
        self.assertTrue(any(item["category"] == "inconsistent_supersession"
                            for item in report["findings"]))

    def test_distinct_inventory_resources_with_equal_names_are_not_a_subject_cluster(self):
        for index in range(3):
            self.claim(str(index), value=str(index), slot='resource:' + str(index))
        with self.database.connect() as connection:
            for index in range(3):
                connection.execute("UPDATE memory_claims SET claim_kind='provider_binding',payload_json=? WHERE id=?",
                                   (json.dumps({'inventory_source': 'test', 'subject': 'Same name',
                                                'external_reference': 'light.' + str(index)}), str(index)))
        report = MemoryMaintenance(self.database).start()
        self.assertFalse(any(item['category'] == 'related_claim_cluster' for item in report['findings']))

    def test_orphan_relation_is_reported(self):
        self.claim("a", value="Tee")
        raw = sqlite3.connect(self.path)
        try:
            raw.execute("PRAGMA foreign_keys=OFF")
            raw.execute(
                """INSERT INTO memory_relations
                   (id,from_claim_id,to_claim_id,relation_type,created_at)
                   VALUES ('orphan','a','missing','contradicts','2026')"""
            )
            raw.commit()
        finally:
            raw.close()
        report = MemoryMaintenance(self.database).start()
        self.assertTrue(any(item["problem_class"] == "orphaned_data" for item in report["findings"]))
        self.assertEqual(1, len(report["warnings"]))

    def test_usage_is_evidence_only_and_never_a_delete_decision(self):
        self.claim("a", value="Tee", canonical="v2:drink:tea:a")
        self.claim("b", value="Tee", canonical="v2:drink:tea:b")
        conversations = ConversationStore(self.database)
        conversation_id = conversations.create("Usage")["id"]
        conversations.append_turn(conversation_id, "Frage", "Antwort", turn_id="turn-usage")
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_compiler_usage
                   (turn_id,consumer,claim_id,usage,created_at)
                   VALUES ('turn-usage','answer','a','used','2026')"""
            )
        report = MemoryMaintenance(self.database).start()
        duplicate = next(item for item in report["findings"] if item["category"] == "same_structured_claim")
        self.assertEqual(1, duplicate["evidence"]["usage"]["a"]["used"])
        self.assertEqual(0, duplicate["evidence"]["usage"]["b"]["used"])
        self.assertTrue(duplicate["evidence"]["usage_is_signal_only"])
        self.assertNotIn(duplicate["proposed_action"], {"archive", "delete_candidate"})

    def test_repeated_run_reuses_finding_identity(self):
        self.claim("a", value="Tee", canonical="v2:drink:tea:a")
        self.claim("b", value="Tee", canonical="v2:drink:tea:b")
        maintenance = MemoryMaintenance(self.database)
        first, second = maintenance.start(), maintenance.start()
        self.assertEqual(first["findings"][0]["id"], second["findings"][0]["id"])
        with self.database.connect() as connection:
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM memory_maintenance_findings"
            ).fetchone()[0])
            self.assertEqual(2, connection.execute(
                "SELECT count(*) FROM memory_maintenance_run_findings"
            ).fetchone()[0])

    def test_analysis_failure_cannot_change_product_memory(self):
        self.claim("a", value="Tee")
        maintenance = MemoryMaintenance(
            self.database, analysis_hook=lambda snapshot, findings: (_ for _ in ()).throw(ValueError("boom"))
        )
        before = maintenance.product_digest()
        report = maintenance.start()
        self.assertEqual("failed", report["status"])
        self.assertEqual("ValueError", report["error_class"])
        self.assertEqual(before, maintenance.product_digest())
        self.assertEqual([], report["findings"])

    def test_consolidation_preserves_information_as_review_only(self):
        for index, prop in enumerate(("drink", "food", "color")):
            self.claim(
                str(index), value=f"value-{index}", slot=f"v2:user:self:{prop}",
                prop=prop, canonical=f"v2:user:self:{prop}",
            )
        report = MemoryMaintenance(self.database).start()
        finding = next(item for item in report["findings"] if item["problem_class"] == "consolidation_candidate")
        self.assertEqual("review", finding["proposed_action"])
        self.assertTrue(finding["evidence"]["information_must_be_preserved"])


if __name__ == "__main__":
    unittest.main()
