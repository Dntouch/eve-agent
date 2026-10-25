import sqlite3
import tempfile
import unittest
from pathlib import Path

from eve_agent.memory_compiler import MemoryCompiler
from eve_agent.memory_v2 import MemoryV2Runtime
from eve_agent.agent import EveAgent
from eve_agent.dialog import Route
from eve_agent.search import LocalSearchCapability, PersistentSearch
from eve_agent.state import StateBus
from eve_agent.storage import ConversationStore, EveDatabase, SCHEMA_VERSION
from eve_agent.work_tasks import WorkTaskCapability, WorkTaskStore


def create_v1(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        EveDatabase._create_v1(connection)
        connection.execute("PRAGMA user_version = 1")
        connection.execute(
            "INSERT INTO conversations(id,title,created_at,updated_at) VALUES ('old','Alt','2026-01-01','2026-01-01')"
        )
        connection.execute(
            """INSERT INTO messages(id,conversation_id,role,content,ordinal,created_at)
               VALUES ('message-old','old','user','Über frühere Geräte','0','2026-01-01')"""
        )
        connection.commit()
    finally:
        connection.close()


def create_v2(path: Path) -> None:
    create_v1(path)
    connection = sqlite3.connect(path)
    try:
        EveDatabase._migrate_v1_to_v2(connection)
        connection.execute("PRAGMA user_version = 2")
        connection.execute(
            "INSERT INTO work_task_lists(id,name,created_at,updated_at) VALUES ('list','EVE','2026','2026')"
        )
        for identifier, title, status, updated_at in (
            ("older", "Älter", "open", "2026-01-01"),
            ("newer", "Neuer", "open", "2026-02-01"),
            ("done", "Erledigt", "completed", "2026-03-01"),
        ):
            connection.execute(
                """INSERT INTO work_items
                   (id,list_id,title,status,created_at,updated_at,metadata_json)
                   VALUES (?,?,?,?,?,?, '{}')""",
                (identifier, "list", title, status, updated_at, updated_at),
            )
        connection.commit()
    finally:
        connection.close()


class SchemaMigrationV2Test(unittest.TestCase):
    def test_new_database_is_created_directly_at_current_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = EveDatabase(Path(tmp) / "data" / "eve.db")
            with database.connect() as connection:
                self.assertEqual(SCHEMA_VERSION, connection.execute("PRAGMA user_version").fetchone()[0])
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
                work_columns = {row[1] for row in connection.execute("PRAGMA table_info(work_items)")}
            self.assertIn("work_items", tables)
            self.assertIn("position", work_columns)
            self.assertIn("conversation_messages_fts", tables)
            self.assertFalse((database.path.parent / "backups").exists())

    def test_v1_upgrade_preserves_data_builds_search_and_creates_backup_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "eve.db"
            create_v1(path)
            database = EveDatabase(path)
            backups = list((path.parent / "backups").glob("*.db"))
            self.assertEqual(1, len(backups))
            with database.connect() as connection:
                self.assertEqual(SCHEMA_VERSION, connection.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual("Alt", connection.execute("SELECT title FROM conversations WHERE id='old'").fetchone()[0])
                self.assertIsNone(connection.execute(
                    "SELECT turn_id FROM messages WHERE id='message-old'"
                ).fetchone()[0])
                self.assertEqual(0, connection.execute("SELECT count(*) FROM turns").fetchone()[0])
            self.assertEqual("Über frühere Geräte", PersistentSearch(database).conversations("Geräte")[0]["content"])
            EveDatabase(path)
            self.assertEqual(backups, list((path.parent / "backups").glob("*.db")))
            backup = sqlite3.connect(backups[0])
            try:
                self.assertEqual(1, backup.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(1, backup.execute("SELECT count(*) FROM messages").fetchone()[0])
            finally:
                backup.close()

    def test_v2_upgrade_preserves_previous_visible_order_and_backs_up_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "eve.db"
            create_v2(path)
            database = EveDatabase(path)
            backups = list((path.parent / "backups").glob("*.db"))
            self.assertEqual(1, len(backups))
            with database.connect() as connection:
                self.assertEqual(SCHEMA_VERSION, connection.execute("PRAGMA user_version").fetchone()[0])
                columns = {row[1] for row in connection.execute("PRAGMA table_info(work_items)")}
                ordered = connection.execute(
                    "SELECT id, position FROM work_items WHERE status='open' ORDER BY position"
                ).fetchall()
            self.assertIn("position", columns)
            self.assertEqual([("newer", 0), ("older", 1)], [(row[0], row[1]) for row in ordered])
            backup = sqlite3.connect(backups[0])
            try:
                self.assertEqual(2, backup.execute("PRAGMA user_version").fetchone()[0])
                self.assertNotIn("position", {row[1] for row in backup.execute("PRAGMA table_info(work_items)")})
            finally:
                backup.close()
            EveDatabase(path)
            self.assertEqual(backups, list((path.parent / "backups").glob("*.db")))

    def test_backup_includes_committed_wal_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "eve.db"
            create_v1(path)
            writer = sqlite3.connect(path)
            try:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("PRAGMA wal_autocheckpoint=0")
                writer.execute(
                    "INSERT INTO conversations(id,title,created_at,updated_at) VALUES ('wal','WAL','2026','2026')"
                )
                writer.commit()
                EveDatabase(path)
                backup_path = next((path.parent / "backups").glob("*.db"))
                backup = sqlite3.connect(backup_path)
                try:
                    self.assertEqual("WAL", backup.execute(
                        "SELECT title FROM conversations WHERE id='wal'"
                    ).fetchone()[0])
                finally:
                    backup.close()
            finally:
                writer.close()

    def test_failed_migration_rolls_back_schema_and_data(self):
        class BrokenDatabase(EveDatabase):
            @classmethod
            def _migrations(cls):
                def broken(connection):
                    connection.execute("CREATE TABLE must_rollback(value TEXT)")
                    raise RuntimeError("kaputt")
                return {1: broken}

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eve.db"
            create_v1(path)
            with self.assertRaisesRegex(RuntimeError, "kaputt"):
                BrokenDatabase(path)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(1, connection.execute("PRAGMA user_version").fetchone()[0])
                self.assertIsNone(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='must_rollback'"
                ).fetchone())
                self.assertEqual(1, connection.execute("SELECT count(*) FROM messages").fetchone()[0])
            finally:
                connection.close()

    def test_failed_v2_to_v3_migration_rolls_back_position_column(self):
        class BrokenV3Database(EveDatabase):
            @classmethod
            def _migrations(cls):
                def broken(connection):
                    connection.execute("ALTER TABLE work_items ADD COLUMN position INTEGER")
                    raise RuntimeError("v3 kaputt")
                return {1: cls._migrate_v1_to_v2, 2: broken}

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eve.db"
            create_v2(path)
            with self.assertRaisesRegex(RuntimeError, "v3 kaputt"):
                BrokenV3Database(path)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(2, connection.execute("PRAGMA user_version").fetchone()[0])
                self.assertNotIn("position", {row[1] for row in connection.execute("PRAGMA table_info(work_items)")})
                self.assertEqual(3, connection.execute("SELECT count(*) FROM work_items").fetchone()[0])
            finally:
                connection.close()


class WorkTasksV2Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = EveDatabase(Path(self.temp.name) / "eve.db")
        self.store = WorkTaskStore(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_history_reopen_update_and_list(self):
        task_list = self.store.create_list("EVE", "EVE-Entwicklung")
        item = self.store.create_item(task_list["id"], "Session-Lifecycle", "Timeout prüfen")
        self.assertEqual([item["id"]], [x["id"] for x in self.store.list_items(list_id=task_list["id"])])
        changed = self.store.update_item(item["id"], {"title": "Session-Lifecycle prüfen"})
        self.assertEqual("Session-Lifecycle prüfen", changed["title"])
        completed = self.store.complete_item(item["id"])
        self.assertEqual("completed", completed["status"])
        self.assertIsNotNone(completed["completed_at"])
        self.assertEqual(completed["id"], self.store.get_item(item["id"])["id"])
        reopened = self.store.reopen_item(item["id"])
        self.assertEqual("open", reopened["status"])
        self.assertIsNone(reopened["completed_at"])
        self.assertEqual(
            ["reopened", "completed", "updated", "created"],
            [event["event_type"] for event in self.store.events(item["id"])],
        )

    def test_search_is_immediate_and_handles_german_diacritics(self):
        task_list = self.store.create_list("Smart Home")
        item = self.store.create_item(task_list["id"], "Küchenlicht prüfen", "Geräte-Anbindung")
        self.assertEqual(item["id"], self.store.search_items("Küchenlicht")[0]["id"])
        self.store.update_item(item["id"], {"title": "Wohnzimmer prüfen"})
        self.assertEqual([], self.store.search_items("Küchenlicht"))
        self.assertEqual(item["id"], self.store.search_items("Wohnzimmer")[0]["id"])

    def test_move_reorders_atomically_across_lists_and_survives_reopen(self):
        first_list = self.store.create_list("A")
        second_list = self.store.create_list("B")
        first = self.store.create_item(first_list["id"], "Erste")
        second = self.store.create_item(first_list["id"], "Zweite")
        third = self.store.create_item(first_list["id"], "Dritte")
        destination = self.store.create_item(second_list["id"], "Ziel")

        self.store.move_item(third["id"], first_list["id"], 0)
        self.assertEqual(
            [third["id"], first["id"], second["id"]],
            [item["id"] for item in self.store.list_items(list_id=first_list["id"], status="open")],
        )
        moved = self.store.move_item(first["id"], second_list["id"], 0)
        self.assertEqual(second_list["id"], moved["list_id"])
        self.assertEqual(
            [first["id"], destination["id"]],
            [item["id"] for item in self.store.list_items(list_id=second_list["id"], status="open")],
        )

        restarted = WorkTaskStore(EveDatabase(self.database.path))
        self.assertEqual(
            [third["id"], second["id"]],
            [item["id"] for item in restarted.list_items(list_id=first_list["id"], status="open")],
        )
        restarted.complete_item(third["id"])
        reopened = restarted.reopen_item(third["id"])
        self.assertEqual(2, reopened["position"])
        self.assertEqual(
            [second["id"], third["id"]],
            [item["id"] for item in restarted.list_items(list_id=first_list["id"], status="open")],
        )

    def test_invalid_move_rolls_back_without_reordering(self):
        source = self.store.create_list("Quelle")
        target = self.store.create_list("Ziel")
        first = self.store.create_item(source["id"], "Eins")
        second = self.store.create_item(source["id"], "Zwei")
        before = [(item["id"], item["position"]) for item in self.store.list_items(list_id=source["id"])]
        with self.assertRaisesRegex(ValueError, "Zielposition"):
            self.store.move_item(first["id"], target["id"], 4)
        self.assertEqual(before, [(item["id"], item["position"]) for item in self.store.list_items(list_id=source["id"])])
        with self.assertRaises(KeyError):
            self.store.move_item(first["id"], "missing", 0)
        with self.assertRaises(KeyError):
            self.store.move_item("missing", target["id"], 0)
        self.assertEqual([first["id"], second["id"]], [item["id"] for item in self.store.list_items(list_id=source["id"])])

    def test_items_and_lists_are_soft_deleted_with_history(self):
        task_list = self.store.create_list("Löschtest")
        first = self.store.create_item(task_list["id"], "Einzeln löschen")
        second = self.store.create_item(task_list["id"], "Mit Liste löschen")

        deleted_item = self.store.delete_item(first["id"])
        self.assertEqual(first["id"], deleted_item["id"])
        with self.assertRaises(KeyError):
            self.store.get_item(first["id"])

        deleted_list = self.store.delete_list(task_list["id"])
        self.assertEqual(1, deleted_list["deleted_items"])
        with self.assertRaises(KeyError):
            self.store.get_list(task_list["id"])
        with self.assertRaises(KeyError):
            self.store.get_item(second["id"])

        with self.database.connect() as connection:
            item_events = connection.execute(
                "SELECT event_type FROM work_item_events WHERE work_item_id=? ORDER BY id", (first["id"],)
            ).fetchall()
            list_events = connection.execute(
                "SELECT event_type FROM work_item_events WHERE work_item_id=? ORDER BY id", (second["id"],)
            ).fetchall()
        self.assertEqual(["created", "deleted"], [row["event_type"] for row in item_events])
        self.assertEqual(["created", "deleted"], [row["event_type"] for row in list_events])

    def test_deleted_list_name_can_be_reused_without_restoring_deleted_items(self):
        original = self.store.create_list("Test", "Alte Beschreibung")
        old_item = self.store.create_item(original["id"], "Alte Aufgabe")
        self.store.delete_list(original["id"])

        recreated = self.store.create_list("test", "Neue Beschreibung")

        self.assertEqual(original["id"], recreated["id"])
        self.assertEqual("test", recreated["name"])
        self.assertEqual("Neue Beschreibung", recreated["description"])
        self.assertEqual("active", recreated["status"])
        self.assertEqual([], self.store.list_items(list_id=recreated["id"], status=None))
        with self.assertRaises(KeyError):
            self.store.get_item(old_item["id"])

    def test_active_list_name_still_cannot_be_reused_case_insensitively(self):
        self.store.create_list("Test")

        with self.assertRaisesRegex(ValueError, "existiert bereits"):
            self.store.create_list("test")



    def test_batch_creation_is_atomic_ordered_and_idempotent(self):
        task_list = self.store.create_list("EVE")
        first = self.store.create_items(task_list["id"], [
            {"title": "Erste Aufgabe", "description": "Erste Beschreibung"},
            {"title": "Zweite Aufgabe", "description": "Zweite Beschreibung"},
        ])
        repeated = self.store.create_items(task_list["id"], [
            {"title": "erste aufgabe", "description": "Wird nicht überschrieben"},
            {"title": "Dritte Aufgabe", "description": "Dritte Beschreibung"},
        ])

        self.assertEqual((2, 0), (first["created_count"], first["existing_count"]))
        self.assertEqual((1, 1), (repeated["created_count"], repeated["existing_count"]))
        items = self.store.list_items(list_id=task_list["id"])
        self.assertEqual(["Erste Aufgabe", "Zweite Aufgabe", "Dritte Aufgabe"], [item["title"] for item in items])
        self.assertEqual("Erste Beschreibung", items[0]["description"])

        with self.assertRaisesRegex(ValueError, "Aufgabentitel"):
            self.store.create_items(task_list["id"], [
                {"title": "Würde sonst angelegt"}, {"title": ""},
            ])
        self.assertEqual(3, len(self.store.list_items(list_id=task_list["id"])))

    def test_list_and_initial_items_are_created_atomically(self):
        result = self.store.create_list_with_items("Migration", [
            {"title": "Bestandsaufnahme", "description": "Systeme erfassen"},
            {"title": "Mailmigration", "description": "Dienste vorbereiten"},
        ], "Projektbeschreibung")

        task_list = self.store.get_list(result["list_id"])
        items = self.store.list_items(list_id=result["list_id"])
        self.assertEqual("Migration", task_list["name"])
        self.assertEqual(2, result["created_count"])
        self.assertEqual(["Bestandsaufnahme", "Mailmigration"], [item["title"] for item in items])

        with self.assertRaisesRegex(ValueError, "Aufgabentitel"):
            self.store.create_list_with_items("Defekt", [
                {"title": "Gültig"}, {"title": ""},
            ])
        self.assertNotIn("Defekt", [item["name"] for item in self.store.list_lists()])



class SearchV2Test(unittest.TestCase):

    def test_local_search_contract_distinguishes_memory_from_live_provider_state(self):
        operation = LocalSearchCapability.minimal_contract()["operations"]["search_knowledge"]
        self.assertEqual("read", operation["effect"])
        self.assertIn("Historisch gespeichertes Memory-Wissen", operation["purpose"])
        self.assertIn("keinen aktuellen Zustand", operation["purpose"])

    def test_all_domains_are_separate_and_soft_deleted_content_is_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = EveDatabase(root / "eve.db")
            conversations = ConversationStore(database)
            conversation = conversations.create("Lautsprecher")
            conversations.append_turn(conversation["id"], "WeSpeaker anbinden", "Das planen wir.")
            memory = MemoryV2Runtime(database, MemoryCompiler(database))
            search = PersistentSearch(database, memory_runtime=memory)
            self.assertEqual(conversation["id"], search.conversations("WeSpeaker")[0]["conversation_id"])
            conversations.delete(conversation["id"])
            self.assertEqual([], search.conversations("WeSpeaker"))

            with database.connect() as connection:
                connection.execute(
                    """INSERT INTO memory_claims
                       (id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,lifecycle,
                        verification_policy,created_at,updated_at)
                       VALUES ('heat','opaque_fact','household:default','v2:kitchen:heating',
                        'v2:kitchen:heating','Die Küche enthält eine Wärmepumpe',
                        '{"subject":"Küche","property":"Heizung","value":"Wärmepumpe"}',
                        'active','stable','2026','2026')"""
                )
            self.assertIn("Wärmepumpe", search.knowledge("Wärmepumpe")[0]["content"])
            memory.forget("Wärmepumpe")
            self.assertEqual([], search.knowledge("Wärmepumpe"))

if __name__ == "__main__":
    unittest.main()
