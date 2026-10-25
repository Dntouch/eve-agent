import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from eve_agent.storage import ConversationStore, EveDatabase, SCHEMA_VERSION
from eve_agent.search import PersistentSearch


class EveDatabaseTest(unittest.TestCase):
    def test_creates_versioned_private_database_with_foreign_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "eve.db"
            database = EveDatabase(path)

            self.assertEqual(0o600, os.stat(path).st_mode & 0o777)
            self.assertEqual(0o700, os.stat(path.parent).st_mode & 0o777)
            with database.connect() as connection:
                self.assertEqual(SCHEMA_VERSION, connection.execute("PRAGMA user_version").fetchone()[0])
                self.assertEqual(1, connection.execute("PRAGMA foreign_keys").fetchone()[0])
                tables = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            self.assertTrue({
                "conversations", "messages", "memory_items", "scheduled_tasks",
                "task_runs", "approvals", "audit_events",
                "conversation_assets", "conversation_tool_events",
                "visual_asset_index", "visual_asset_index_fts",
                "turns", "turn_memory_retrievals",
                "memory_claims", "memory_observations", "memory_evidence",
                "memory_relations", "memory_learning_decisions",
                "memory_learning_decision_claims", "memory_legacy_mappings",
                "memory_shadow_learning_decisions", "memory_shadow_decision_observations",
                "memory_runtime_traces", "memory_runtime_events",
                "memory_learning_jobs", "conversation_learning_runtime",
            }.issubset(tables))

    def test_rejects_database_from_newer_application_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eve.db"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
                connection.commit()
            with self.assertRaises(RuntimeError):
                EveDatabase(path)

    def test_v8_migration_removes_only_retired_markdown_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "eve.db"
            database = EveDatabase(path)
            with database.connect() as connection:
                for identifier, content, metadata in (
                    ("legacy-fact", "Alt", '{"legacy_source":"memory/facts.md"}'),
                    ("legacy-home", "Alt HA", '{"legacy_source":"memory/home-assistant.md"}'),
                    ("current-fact", "Neu gelernt", '{}'),
                    ("binding", "Aktuelle Zuordnung", '{"provider":"home_assistant"}'),
                ):
                    connection.execute(
                        """INSERT INTO memory_items
                           (id,content,category,status,confidence,created_at,updated_at,metadata_json)
                           VALUES (?,?,?,'active',1.0,'2026','2026',?)""",
                        (identifier, content, "provider_binding" if identifier == "binding" else "fact", metadata),
                    )
                connection.execute("PRAGMA user_version = 7")

            EveDatabase(path)
            with sqlite3.connect(path) as connection:
                remaining = {row[0] for row in connection.execute("SELECT id FROM memory_items")}
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(SCHEMA_VERSION, version)
            self.assertEqual({"current-fact", "binding"}, remaining)


class ConversationStoreTest(unittest.TestCase):
    def make_store(self, root: Path) -> ConversationStore:
        return ConversationStore(EveDatabase(root / "data" / "eve.db"))

    def test_conversation_crud_and_turn_persist_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make_store(root)
            conversation = store.create()
            store.append_turn(conversation["id"], "Plane meinen Urlaub", "Gerne.")

            restarted = self.make_store(root)
            loaded = restarted.get(conversation["id"])
            page = restarted.messages(conversation["id"])
            self.assertEqual("Plane meinen Urlaub", loaded["title"])
            self.assertEqual(["user", "assistant"], [item["role"] for item in page["messages"]])
            self.assertEqual("Gerne.", page["messages"][1]["content"])

            renamed = restarted.rename(conversation["id"], "Sommerurlaub")
            self.assertEqual("Sommerurlaub", renamed["title"])
            restarted.delete(conversation["id"])
            with self.assertRaises(KeyError):
                restarted.get(conversation["id"])

    def test_recent_history_returns_complete_conversation_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            conversation_id = store.create("Lang")['id']
            for index in range(40):
                store.append_turn(conversation_id, f"Frage {index}", f"Antwort {index}")

            history = store.recent_history(conversation_id)

            self.assertEqual(80, len(history))
            self.assertEqual("Frage 0", history[0]["content"])
            self.assertEqual("Antwort 39", history[-1]["content"])

    def test_operational_conversation_state_survives_restart_without_becoming_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); store = self.make_store(root)
            conversation_id = store.create("Pending")['id']
            state = {
                "dialog_focus": [{
                    "entity_id": "sensor.target", "source": "provider_execution",
                    "live_verified": True, "live_verified_at": "2026-10-08T12:00:00+02:00",
                }],
                "pending_resolution": {
                    "status": "open", "provider": "home_assistant",
                    "operation_types": ["get_state"], "unresolved": ["target_confirmation"],
                },
            }
            store.set_conversation_state(conversation_id, state)

            restarted = self.make_store(root)
            self.assertEqual(state, restarted.conversation_state(conversation_id))
            with restarted.database.connect() as connection:
                self.assertEqual(0, connection.execute("SELECT count(*) FROM memory_items").fetchone()[0])

    def test_turn_messages_retrievals_and_knowledge_flow_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make_store(root)
            conversation_id = store.create("Lineage")["id"]
            with store.database.connect() as connection:
                connection.execute(
                    """INSERT INTO memory_items
                       (id,content,category,status,confidence,created_at,updated_at)
                       VALUES ('memory-1','Testwissen','fact','active',1.0,'2026','2026')"""
                )
            flow = {
                "version": 1,
                "stages": [{"kind": "user", "summary": "Eingabe", "details": {"token": "secret"}}],
            }
            user, assistant = store.append_turn(
                conversation_id, "Frage", "Antwort", turn_id="turn-1", knowledge_flow=flow,
                memory_retrievals=[{"memory_id": "memory-1", "method": "hybrid", "score": .42}],
            )

            restarted = self.make_store(root)
            lineage = restarted.turn_lineage("turn-1")
            messages = restarted.messages(conversation_id)["messages"]
            self.assertEqual("turn-1", user["turn_id"])
            self.assertEqual("turn-1", assistant["turn_id"])
            self.assertEqual(["turn-1", "turn-1"], [item["turn_id"] for item in messages])
            self.assertEqual(user["id"], lineage["user_message_id"])
            self.assertEqual(assistant["id"], lineage["assistant_message_id"])
            self.assertEqual("[REDACTED]", lineage["knowledge_flow"]["stages"][0]["details"]["token"])
            self.assertEqual("memory-1", lineage["memory_retrievals"][0]["memory_id"])
            self.assertEqual("hybrid", lineage["memory_retrievals"][0]["method"])
            self.assertEqual(.42, lineage["memory_retrievals"][0]["score"])

    def test_legacy_messages_receive_no_invented_turn_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            conversation_id = store.create("Historisch")["id"]
            store.append_turn(conversation_id, "Alt", "Altantwort")

            messages = store.messages(conversation_id)["messages"]
            self.assertEqual([None, None], [item["turn_id"] for item in messages])
            with store.database.connect() as connection:
                self.assertEqual(0, connection.execute("SELECT count(*) FROM turns").fetchone()[0])

    def test_messages_are_paginated_without_splitting_storage_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            conversation_id = store.create("Test")["id"]
            for index in range(3):
                store.append_turn(conversation_id, f"Frage {index}", f"Antwort {index}")

            newest = store.messages(conversation_id, limit=2)
            self.assertTrue(newest["has_more"])
            self.assertEqual(["Frage 2", "Antwort 2"], [item["content"] for item in newest["messages"]])
            older = store.messages(conversation_id, limit=4, before=newest["messages"][0]["ordinal"])
            self.assertEqual(["Frage 0", "Antwort 0", "Frage 1", "Antwort 1"], [item["content"] for item in older["messages"]])

    def test_reasoning_is_redacted_persisted_metadata_and_not_conversation_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            conversation_id = store.create("Thinking")["id"]
            _user, assistant = store.append_turn(conversation_id, "Frage", "Antwort")

            stored = store.store_message_reasoning(
                conversation_id, assistant["id"],
                "Prüfe Provider mit Authorization: Bearer super-secret-token",
            )

            message = store.messages(conversation_id)["messages"][1]
            self.assertEqual(stored["reasoning"], message["metadata"]["reasoning"])
            self.assertNotIn("super-secret-token", message["metadata"]["reasoning"])
            history = store.recent_history(conversation_id)
            self.assertEqual("Antwort", history[1]["content"])

    def test_unknown_conversation_and_invalid_title_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            with self.assertRaises(KeyError):
                store.messages("missing")
            with self.assertRaises(ValueError):
                store.create("   ")

    def test_turn_assets_and_tool_events_survive_restart_without_inline_base64(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); store = self.make_store(root)
            conversation_id = store.create("Medien")['id']
            image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
            store.append_turn(
                conversation_id, "Was ist darauf?", "Ein Testbild.",
                user_attachments=[{"type": "image", "content": image}],
                assistant_attachments=[{"type": "image", "content": image}],
                tool_events=[{
                    "tool": "home_assistant", "status": "completed", "summary": "Kamerabild abgerufen",
                    "input": {"operation": "get_camera_snapshot"},
                    "result": {"resource_count": 1},
                }],
            )

            restarted = self.make_store(root)
            messages = restarted.messages(conversation_id)["messages"]
            self.assertEqual(1, len(messages[0]["attachments"]))
            self.assertEqual(1, len(messages[1]["attachments"]))
            self.assertNotIn("base64", json.dumps(messages))
            self.assertEqual("home_assistant", messages[1]["tool_events"][0]["tool"])
            self.assertTrue(messages[1]["tool_events"][0]["historical"])
            history = restarted.recent_history(conversation_id)
            self.assertIn("Historische Conversation-Anhänge", history[0]["content"])
            self.assertIn("kein aktueller Providerzustand", history[1]["content"])
            self.assertNotIn("base64", json.dumps(history))
            mime, body = restarted.read_asset(messages[0]["attachments"][0]["id"])
            self.assertEqual("image/png", mime)
            self.assertTrue(body)

    def test_home_assistant_asset_action_provenance_survives_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); store = self.make_store(root)
            conversation_id = store.create("Zwei Kameras")["id"]
            image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
            attachments = [
                {
                    "type": "image", "content": image,
                    "action_index": index, "operation": "get_camera_snapshot",
                    "entity_id": entity_id, "result_status": "success",
                    "result_reference": f"action_result:{index}",
                }
                for index, entity_id in enumerate(("camera.front", "camera.garage"))
            ]
            store.append_turn(
                conversation_id, "Zeige beide Kameras", "Hier sind beide Bilder.",
                assistant_attachments=attachments,
            )

            assistant = store.messages(conversation_id)["messages"][1]
            self.assertEqual(2, len(assistant["attachments"]))
            self.assertEqual([0, 1], [
                item["metadata"]["action_index"] for item in assistant["attachments"]
            ])
            self.assertEqual(["camera.front", "camera.garage"], [
                item["metadata"]["entity_id"] for item in assistant["attachments"]
            ])
            self.assertTrue(all(
                item["metadata"]["operation"] == "get_camera_snapshot"
                for item in assistant["attachments"]
            ))

    def test_delete_conversation_removes_owned_asset_but_not_other_conversation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); store = self.make_store(root)
            image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
            ids = [store.create(f"Medien {index}")["id"] for index in range(2)]
            for conversation_id in ids:
                store.append_turn(
                    conversation_id, "Bild", "Okay",
                    user_attachments=[{"type": "image", "content": image}],
                )
            assets = [store.messages(item)["messages"][0]["attachments"][0] for item in ids]

            store.delete(ids[0])

            with self.assertRaises(KeyError):
                store.read_asset(assets[0]["id"])
            self.assertFalse((store.asset_root / (assets[0]["id"] + ".png")).exists())
            self.assertTrue(store.read_asset(assets[1]["id"])[1])

    def test_image_index_reuses_asset_and_is_removed_with_conversation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            conversation_id = store.create("Milo im Garten")["id"]
            image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
            store.append_turn(
                conversation_id, "Das ist Milo im Garten", "Ich sehe Milo neben dem Apfelbaum.",
                user_attachments=[{"type": "image", "content": image}],
            )
            asset = store.messages(conversation_id)["messages"][0]["attachments"][0]
            details = store.asset_details(asset["id"])
            self.assertIn("Milo", details["description"])
            self.assertEqual(conversation_id, details["conversation_id"])
            self.assertEqual(1, len(list(store.asset_root.iterdir())))

            store.delete(conversation_id)
            with store.database.connect() as connection:
                self.assertEqual(
                    0, connection.execute("SELECT count(*) FROM visual_asset_index").fetchone()[0]
                )

    def test_visual_search_crosses_conversations_and_returns_original_asset_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            source = store.create("Werkstatt")["id"]
            store.append_turn(
                source, "Foto vom ESP32 Gehäuse am 3D-Drucker", "Daneben liegt ein Messschieber.",
                user_attachments=[{
                    "type": "image", "content": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB",
                }],
            )
            target = store.create("Neue Unterhaltung")["id"]
            result = PersistentSearch(store.database).visual_assets("ESP32 Gehäuse Drucker")
            self.assertEqual(1, len(result))
            self.assertEqual(source, result[0]["conversation_id"])
            self.assertNotEqual(target, result[0]["conversation_id"])
            self.assertEqual(
                store.messages(source)["messages"][0]["attachments"][0]["id"],
                result[0]["asset_id"],
            )
            self.assertNotIn("base64", json.dumps(result))

    def test_generated_attachment_is_bound_to_assistant_message_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); store = self.make_store(root)
            conversation_id = store.create("Datei")["id"]
            _user, assistant = store.append_turn(conversation_id, "Erstelle Datei", "Hier ist sie.")
            store.store_artifacts(conversation_id, assistant["id"], [{
                "filename": "bericht.txt", "mime": "text/plain", "base64": "SGFsbG8=",
            }])

            message = self.make_store(root).messages(conversation_id)["messages"][1]
            self.assertEqual("bericht.txt", message["attachments"][0]["filename"])
            self.assertEqual("text/plain", message["attachments"][0]["media_type"])
            self.assertEqual(b"Hallo", store.read_asset(message["attachments"][0]["id"])[1])

    def test_download_export_reuses_tool_image_attachment_and_visual_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            cid = store.create("Bild")["id"]
            encoded = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
            _, assistant = store.append_turn(cid, "Erzeuge ein Bild", "Hier ist es.",
                assistant_attachments=[{"type": "file", "filename": "bild.png", "content": "data:image/png;base64," + encoded}])
            original = store.messages(cid)["messages"][1]["attachments"][0]
            artifact = {"filename": "bild.png", "mime": "image/png", "base64": encoded}
            for _ in range(2):
                self.assertEqual(original["id"], store.store_artifacts(cid, assistant["id"], [artifact])[0]["id"])
            with store.database.connect() as connection:
                self.assertEqual(1, connection.execute("SELECT count(*) FROM conversation_assets").fetchone()[0])
                self.assertEqual(1, connection.execute("SELECT count(*) FROM visual_asset_index").fetchone()[0])
            self.assertEqual(1, len(list(store.asset_root.iterdir())))
            # A deliberately different download name remains a separate file.
            store.store_artifacts(cid, assistant["id"], [{**artifact, "filename": "kopie.png"}])
            self.assertEqual(2, len(store.messages(cid)["messages"][1]["attachments"]))

    def test_historical_duplicate_assistant_assets_are_displayed_once_without_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            cid = store.create("Bild")["id"]
            _, assistant = store.append_turn(cid, "Bild", "Fertig", assistant_attachments=[{
                "type": "file", "filename": "bild.png",
                "content": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"}])
            with store.database.connect() as connection:
                connection.execute("""INSERT INTO conversation_assets
                    (id,conversation_id,message_id,media_type,filename,byte_size,sha256,ordinal,created_at,metadata_json)
                    SELECT 'historical-duplicate',conversation_id,message_id,media_type,filename,byte_size,sha256,
                           ordinal+1,created_at,metadata_json FROM conversation_assets WHERE message_id=?""", (assistant["id"],))
            self.assertEqual(1, len(store.messages(cid)["messages"][1]["attachments"]))
            with store.database.connect() as connection:
                self.assertEqual(2, connection.execute("SELECT count(*) FROM conversation_assets").fetchone()[0])
