import tempfile
import unittest
from pathlib import Path

from eve_agent.storage import ConversationStore, EveDatabase
from eve_agent.work_tasks import WorkTaskCapability, WorkTaskStore


class TaskContextLinksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = EveDatabase(Path(self.temp.name) / "eve.db")
        self.conversations = ConversationStore(self.database)
        self.tasks = WorkTaskStore(self.database)
        self.conversation = self.conversations.create("Kontextchat")
        self.first = self.conversations.append_turn(
            self.conversation["id"], "Erste Frage", "Erste Antwort", turn_id="turn-1"
        )
        self.second = self.conversations.append_turn(
            self.conversation["id"], "Zweite Frage", "Zweite Antwort", turn_id="turn-2"
        )
        task_list = self.tasks.create_list("Projekt")
        self.item = self.tasks.create_item(task_list["id"], "Kontext umsetzen")

    def tearDown(self):
        self.temp.cleanup()

    def test_conversation_message_and_range_links_are_metadata_only_and_reverse_queryable(self):
        conversation_link = self.tasks.add_context_link(
            self.item["id"], self.conversation["id"], label="Gesamter Chat"
        )
        message_link = self.tasks.add_context_link(
            self.item["id"], self.conversation["id"],
            start_message_id=self.first[0]["id"], label="Ausgangspunkt",
        )
        range_link = self.tasks.add_context_link(
            self.item["id"], self.conversation["id"],
            start_message_id=self.first[1]["id"], end_message_id=self.second[0]["id"],
            source="assistant",
        )

        loaded = self.tasks.get_item(self.item["id"])
        self.assertEqual(3, len(loaded["context_links"]))
        self.assertEqual(self.conversation["id"], conversation_link["conversation_id"])
        self.assertEqual(self.first[0]["id"], message_link["start_message_id"])
        self.assertLessEqual(range_link["start_ordinal"], range_link["end_ordinal"])
        self.assertNotIn("content", repr(loaded["context_links"]).casefold())
        self.assertEqual(self.item["id"], self.tasks.items_for_conversation(self.conversation["id"])[0]["id"])

        duplicate = self.tasks.add_context_link(self.item["id"], self.conversation["id"])
        self.assertEqual(conversation_link["id"], duplicate["id"])
        self.tasks.remove_context_link(self.item["id"], message_link["id"])
        self.assertEqual(2, len(self.tasks.get_item(self.item["id"])["context_links"]))

    def test_rejects_wrong_conversation_missing_task_and_reversed_range(self):
        other = self.conversations.create("Anderer Chat")
        other_message = self.conversations.append_turn(other["id"], "A", "B")[0]
        with self.assertRaisesRegex(ValueError, "gehört nicht"):
            self.tasks.add_context_link(
                self.item["id"], self.conversation["id"],
                start_message_id=other_message["id"],
            )
        with self.assertRaisesRegex(ValueError, "vor seinem Anfang"):
            self.tasks.add_context_link(
                self.item["id"], self.conversation["id"],
                start_message_id=self.second[1]["id"], end_message_id=self.first[0]["id"],
            )
        with self.assertRaises(KeyError):
            self.tasks.add_context_link("missing", self.conversation["id"])

    def test_soft_deletions_remove_links_and_creation_can_link_atomically(self):
        linked = self.tasks.create_item(
            self.item["list_id"], "Direkt verknüpft",
            context_link={"conversation_id": self.conversation["id"], "source": "task_creation"},
        )
        self.assertEqual("task_creation", linked["context_links"][0]["source"])
        self.tasks.delete_item(linked["id"])
        with self.database.connect() as connection:
            self.assertEqual(0, connection.execute(
                "SELECT count(*) FROM work_item_context_links WHERE work_item_id=?", (linked["id"],)
            ).fetchone()[0])

        self.tasks.add_context_link(self.item["id"], self.conversation["id"])
        self.conversations.delete(self.conversation["id"])
        self.assertEqual([], self.tasks.get_item(self.item["id"])["context_links"])






    def test_existing_task_can_receive_additive_structural_context_without_creating_task(self):
        other = self.conversations.create("Zweiter Chat")
        other_turn = self.conversations.append_turn(
            other["id"], "Dritte Frage", "Dritte Antwort", turn_id="turn-other",
        )
        before_tasks = len(self.tasks.list_items(status=None))
        first_link = self.tasks.add_conversation_context(
            self.item["id"], self.conversation["id"], scope="current_turn",
        )
        second_link = self.tasks.add_conversation_context(
            self.item["id"], other["id"], scope="last_messages", count=2,
        )
        duplicate = self.tasks.add_conversation_context(
            self.item["id"], other["id"], scope="last_messages", count=2,
        )

        loaded = self.tasks.get_item(self.item["id"])
        self.assertEqual(before_tasks, len(self.tasks.list_items(status=None)))
        self.assertEqual(2, len(loaded["context_links"]))
        self.assertNotEqual(first_link["id"], second_link["id"])
        self.assertEqual(second_link["id"], duplicate["id"])
        self.assertEqual(other_turn[0]["id"], second_link["start_message_id"])
        self.assertEqual(other_turn[1]["id"], second_link["end_message_id"])
        self.assertEqual(self.item["id"], self.tasks.items_for_conversation(other["id"])[0]["id"])

    def test_same_conversation_accepts_distinct_ranges_and_conversation_only_link(self):
        whole = self.tasks.add_conversation_context(
            self.item["id"], self.conversation["id"], scope="conversation",
        )
        one_message = self.tasks.add_conversation_context(
            self.item["id"], self.conversation["id"], scope="last_messages", count=1,
        )
        two_turns = self.tasks.add_conversation_context(
            self.item["id"], self.conversation["id"], scope="last_turns", count=2,
        )
        self.assertEqual(3, len(self.tasks.get_item(self.item["id"])["context_links"]))
        self.assertIsNone(whole["start_message_id"])
        self.assertIsNone(one_message["end_message_id"])
        self.assertEqual(self.first[0]["id"], two_turns["start_message_id"])
        self.assertEqual(self.second[1]["id"], two_turns["end_message_id"])








if __name__ == "__main__":
    unittest.main()
