import tempfile
from pathlib import Path
import unittest

from eve_agent.storage import EveDatabase
from eve_agent.work_tasks import WorkTaskStore


class WorkTaskFormattingTest(unittest.TestCase):
    def test_markdown_newlines_and_code_indentation_survive_every_description_write_path(self):
        markdown = "## Ziel\n\n**Fett** und *kursiv*\n\n- Eins\n- Zwei\n\n```python\nif True:\n    print('Hallo')\n```"
        with tempfile.TemporaryDirectory() as directory:
            store = WorkTaskStore(EveDatabase(Path(directory) / "eve.db"))
            task_list = store.create_list("  Test   Liste  ", markdown)
            self.assertEqual("Test Liste", task_list["name"])
            self.assertEqual(markdown, task_list["description"])
            item = store.create_item(task_list["id"], "  Titel   bleibt kompakt  ", markdown)
            self.assertEqual("Titel bleibt kompakt", item["title"])
            self.assertEqual(markdown, store.get_item(item["id"])["description"])
            updated = markdown + "\n\n> Neuer Hinweis"
            store.update_item(item["id"], {"description": updated})
            self.assertEqual(updated, store.get_item(item["id"])["description"])
            result = store.create_items(task_list["id"], [{"title": "Batch", "description": markdown}])
            self.assertEqual(markdown, store.get_item(result["items"][0]["id"])["description"])
            nested = store.create_list_with_items("Neue Liste", [{"title": "Atomar", "description": markdown}], markdown)
            self.assertEqual(markdown, store.get_item(nested["items"][0]["id"])["description"])
