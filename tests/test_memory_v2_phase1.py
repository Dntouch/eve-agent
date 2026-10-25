import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from eve_agent.storage import EveDatabase, MemoryV2AuditStore, SCHEMA_VERSION


def create_v8(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        EveDatabase._create_v1(connection)
        EveDatabase._migrate_v1_to_v2(connection)
        EveDatabase._migrate_v2_to_v3(connection)
        EveDatabase._migrate_v3_to_v4(connection)
        EveDatabase._migrate_v4_to_v5(connection)
        EveDatabase._migrate_v5_to_v6(connection)
        EveDatabase._migrate_v6_to_v7(connection)
        EveDatabase._migrate_v7_to_v8(connection)
        connection.execute("PRAGMA user_version=8")
        connection.execute(
            "INSERT INTO conversations(id,title,created_at,updated_at) VALUES ('c','Alt','2026-01-01','2026-01-01')"
        )
        connection.execute(
            """INSERT INTO messages(id,conversation_id,role,content,ordinal,created_at)
               VALUES ('m-user','c','user','Historischer Kontext',0,'2026-01-01')"""
        )
        rows = (
            ("active", "Ein opaker Fakt mit Umlaut: Größe & Spaß", "fact", "active", .81,
             "m-user", "conversation:old", "2026-01-01", None, b"active-vector", '{"memory_key":"Test","nested":{"x":1}}'),
            ("candidate", "Noch unsicher", "fact", "candidate", .31,
             None, None, None, "2027-01-01", None, "{}"),
            ("superseded", "Historisch ersetzt", "fact", "superseded", .72,
             None, "old:ref", "2025-01-01", "2026-01-01", b"old", '{"note":"kept"}'),
            ("deleted", "Nicht mehr produktiv", "fact", "deleted", .44,
             None, None, None, None, None, "{}"),
            ("binding", "HA Bindung", "provider_binding", "active", .95,
             None, "provider:old", "2026-02-01", None, b"binding", json.dumps({
                 "provider": "home_assistant", "subject": "Wohnzimmerrollo",
                 "property": "Position", "entity_id": "cover.rollade_wohnzimmer",
                 "memory_key": "home_assistant:wohnzimmerrollo:position",
                 "evidence": "user_context_and_successful_provider_read",
             })),
        )
        for row in rows:
            connection.execute(
                """INSERT INTO memory_items
                   (id,content,category,status,confidence,source_message_id,source_ref,
                    valid_from,valid_until,embedding,created_at,updated_at,metadata_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?, ?,?)""",
                (*row[:10], "2026-03-01", "2026-03-02", row[10]),
            )
        connection.execute(
            """INSERT INTO turns(id,conversation_id,user_message_id,created_at,completed_at)
               VALUES ('t','c','m-user','2026-03-01','2026-03-01')"""
        )
        connection.execute(
            """INSERT INTO turn_memory_retrievals(turn_id,memory_id,position,method,score,retrieved_at)
               VALUES ('t','active',0,'hybrid',0.5,'2026-03-01')"""
        )
        connection.commit()
    finally:
        connection.close()


class MemoryV2Phase1MigrationTest(unittest.TestCase):
    def test_realistic_v8_migration_is_lossless_and_auditable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "eve.db"
            create_v8(path)
            before = path.stat().st_size
            database = EveDatabase(path)
            audit = MemoryV2AuditStore(database)
            summary = audit.migration_summary()

            self.assertEqual(23, SCHEMA_VERSION)
            self.assertEqual(5, summary["legacy_items"])
            self.assertEqual(5, summary["claims"])
            self.assertEqual(5, summary["observations"])
            self.assertEqual(5, summary["evidence"])
            self.assertEqual(5, summary["import_decisions"])
            self.assertEqual(0, summary["relations"])
            self.assertEqual({"active": 2, "candidate": 1, "retired": 2}, summary["claim_lifecycle"])
            self.assertEqual({"opaque_fact": 4, "provider_binding": 1}, summary["claim_kinds"])
            self.assertEqual("ok", summary["integrity"])
            self.assertEqual(0, summary["foreign_key_violations"])
            self.assertEqual([], audit.losslessness_issues())
            self.assertGreater(path.stat().st_size, before)

            mapping = audit.resolve_legacy_id("active")
            self.assertIsNotNone(mapping)
            detail = audit.claim(mapping["claim_id"])
            self.assertEqual("legacy_import", detail["evidence"][0]["evidence_type"])
            self.assertEqual("legacy", detail["observations"][0]["source_role"])
            self.assertEqual("historical_creation_context_only",
                             detail["observations"][0]["structured_value"]["source_message_semantics"])
            self.assertEqual("m-user", detail["observations"][0]["message_id"])
            self.assertEqual(len(b"active-vector"), detail["legacy_mapping"]["legacy_embedding_bytes"])

            with database.connect() as connection:
                self.assertEqual(SCHEMA_VERSION, connection.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(5, connection.execute("SELECT count(*) FROM memory_items").fetchone()[0])
                self.assertEqual("active", connection.execute(
                    "SELECT memory_id FROM turn_memory_retrievals WHERE turn_id='t'"
                ).fetchone()[0])
                self.assertEqual(mapping["claim_id"], connection.execute(
                    "SELECT claim_id FROM memory_legacy_mappings WHERE legacy_memory_id='active'"
                ).fetchone()[0])
            backups = list((path.parent / "backups").glob(f"eve-schema-v8-to-v{SCHEMA_VERSION}-*.db"))
            self.assertEqual(1, len(backups))
            with sqlite3.connect(backups[0]) as backup:
                self.assertEqual(8, backup.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(5, backup.execute("SELECT count(*) FROM memory_items").fetchone()[0])

    def test_provider_mapping_uses_only_existing_structured_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eve.db"
            create_v8(path)
            audit = MemoryV2AuditStore(EveDatabase(path))
            bindings = audit.provider_bindings()
            self.assertEqual(1, len(bindings))
            self.assertEqual("home_assistant", bindings[0]["payload"]["provider"])
            self.assertEqual("cover.rollade_wohnzimmer", bindings[0]["payload"]["external_reference"])
            self.assertIsNone(bindings[0]["payload"]["scope"])
            self.assertEqual("configuration", bindings[0]["verification_policy"])
            detail = audit.claim(bindings[0]["id"])
            self.assertTrue(detail["evidence"][0]["payload"]["not_verification"])

    def test_import_is_idempotent_and_reopen_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eve.db"
            create_v8(path)
            database = EveDatabase(path)
            first = MemoryV2AuditStore(database).migration_summary()
            with database.connect() as connection:
                EveDatabase._import_legacy_memory_v2(connection)
            second = MemoryV2AuditStore(EveDatabase(path)).migration_summary()
            for key in ("claims", "observations", "evidence", "import_decisions", "relations"):
                self.assertEqual(first[key], second[key])
            self.assertEqual([], MemoryV2AuditStore(database).losslessness_issues())

    def test_failed_v9_migration_rolls_back_everything(self):
        class BrokenV9Database(EveDatabase):
            @classmethod
            def _migrations(cls):
                migrations = dict(EveDatabase._migrations())
                def broken(connection):
                    EveDatabase._migrate_v8_to_v9(connection)
                    raise RuntimeError("v9 failure")
                migrations[8] = broken
                return migrations

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eve.db"
            create_v8(path)
            with self.assertRaisesRegex(RuntimeError, "v9 failure"):
                BrokenV9Database(path)
            with sqlite3.connect(path) as connection:
                self.assertEqual(8, connection.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(5, connection.execute("SELECT count(*) FROM memory_items").fetchone()[0])
                self.assertIsNone(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='memory_claims'"
                ).fetchone())
                self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
                self.assertEqual([], connection.execute("PRAGMA foreign_key_check").fetchall())


class MemoryV2Phase1ConstraintTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = EveDatabase(Path(self.temp.name) / "eve.db")

    def tearDown(self):
        self.temp.cleanup()

    def _claim(self, identifier: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,display_text,lifecycle,verification_policy,created_at,updated_at)
                   VALUES (?,'opaque_fact','test','key:'||?,'Text','active','unknown','2026','2026')""",
                (identifier, identifier),
            )

    def test_schema_constraints_and_relation_integrity(self):
        self._claim("a")
        self._claim("b")
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_relations(id,from_claim_id,to_claim_id,relation_type,created_at)
                   VALUES ('r','a','b','refines','2026')"""
            )
        with self.assertRaises(sqlite3.IntegrityError), self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_relations(id,from_claim_id,to_claim_id,relation_type,created_at)
                   VALUES ('self','a','a','refines','2026')"""
            )
        with self.assertRaises(sqlite3.IntegrityError), self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_relations(id,from_claim_id,to_claim_id,relation_type,created_at)
                   VALUES ('bad','a','missing','refines','2026')"""
            )
        with self.assertRaises(sqlite3.IntegrityError), self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_relations(id,from_claim_id,to_claim_id,relation_type,created_at)
                   VALUES ('type','a','b','similar','2026')"""
            )
        with self.assertRaises(sqlite3.IntegrityError), self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,display_text,lifecycle,verification_policy,created_at,updated_at)
                   VALUES ('invalid','opaque_fact','test','invalid','x','verified','unknown','2026','2026')"""
            )
        with self.assertRaises(sqlite3.IntegrityError), self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,display_text,lifecycle,verification_policy,created_at,updated_at)
                   VALUES ('duplicate','opaque_fact','test','key:a','x','active','unknown','2026','2026')"""
            )
        with self.assertRaises(sqlite3.IntegrityError), self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_evidence
                   (id,claim_id,stance,evidence_type,observed_at,created_at)
                   VALUES ('missing-claim','missing','supports','test','2026','2026')"""
            )
        with self.assertRaises(sqlite3.IntegrityError), self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_evidence
                   (id,claim_id,stance,evidence_type,observed_at,created_at)
                   VALUES ('bad-stance','a','neutral','test','2026','2026')"""
            )
        self.assertEqual(["refines"], [item["relation_type"] for item in MemoryV2AuditStore(self.database).relations()])

    def test_source_boundaries_are_structural(self):
        self._claim("claim")
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_observations
                   (id,source_role,source_type,observed_at,scope,created_at)
                   VALUES ('assistant','assistant','legacy_import','2026','test','2026')"""
            )
            self.assertEqual(0, connection.execute("SELECT count(*) FROM memory_evidence").fetchone()[0])
            connection.execute(
                """INSERT INTO memory_learning_decisions
                   (id,observation_id,decision_type,method,created_at)
                   VALUES ('decision','assistant','create_active','test','2026')"""
            )
            self.assertEqual(0, connection.execute("SELECT count(*) FROM memory_evidence").fetchone()[0])
            connection.execute(
                """INSERT INTO memory_evidence
                   (id,claim_id,observation_id,stance,evidence_type,observed_at,created_at)
                   VALUES ('evidence','claim','assistant','supports','legacy_import','2026','2026')"""
            )
            evidence = connection.execute("SELECT * FROM memory_evidence").fetchone()
            self.assertEqual("legacy_import", evidence["evidence_type"])
            self.assertIsNone(evidence["tool_event_id"])

    def test_productive_memory_has_no_legacy_file_or_table_write_path(self):
        root = Path(self.temp.name)
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES ('db-only','opaque_fact','user:self','db-only','Database only','{}',
                           'active','dynamic','2026','2026')"""
            )
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM memory_claims WHERE id='db-only'"
            ).fetchone()[0])
        self.assertFalse((root / "memory").exists())


if __name__ == "__main__":
    unittest.main()
