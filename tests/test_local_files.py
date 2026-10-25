import json
import tempfile
import unittest
from pathlib import Path

from eve_agent.local_files import LocalFileAccessError, LocalFileCapability, LocalFileReader
from eve_agent.search import PersistentSearch
from eve_agent.storage import ConversationStore, EveDatabase


class LocalFileReaderTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.first = self.base / "first"; self.second = self.base / "second"
        self.first.mkdir(); self.second.mkdir()
        (self.first / "Anleitung Drucker.md").write_text("Kalibrierung\nplan_turn steht hier\n", encoding="utf-8")
        (self.second / "PERFORMANCE-P7.md").write_text("P7 Ergebnis", encoding="utf-8")
        self.roots = [str(self.first), str(self.second)]
        self.reader = LocalFileReader(lambda: self.roots, max_text_bytes=200)

    def tearDown(self): self.temporary.cleanup()

    def test_multiple_roots_listing_filename_and_content_search(self):
        listing = self.reader.list_directory("root:0/")
        self.assertIn("Anleitung Drucker.md", [item["name"] for item in listing["entries"]])
        self.assertEqual("PERFORMANCE-P7.md", self.reader.search_files("PERFORMANCE-P7")[0]["name"])
        self.assertIn("Anleitung", self.reader.search_files("plan_turn")[0]["name"])

    def test_read_search_and_large_text_are_bounded(self):
        result = self.reader.read_text("Anleitung Drucker.md", max_chars=200)
        self.assertIn("Kalibrierung", result["content"])
        self.assertEqual(2, self.reader.search_text("Anleitung Drucker.md", "plan_turn")["matches"][0]["line"])
        (self.first / "large.log").write_text("x" * 201, encoding="utf-8")
        with self.assertRaisesRegex(LocalFileAccessError, "zu groß"):
            self.reader.read_text("large.log")

    def test_root_removal_traversal_outside_and_symlink_escape_are_blocked(self):
        outside = self.base / "outside.txt"; outside.write_text("secret", encoding="utf-8")
        (self.first / "escape").symlink_to(outside)
        for target in ("../outside.txt", str(outside), "escape"):
            with self.assertRaises(LocalFileAccessError): self.reader.read_text(target)
        self.roots.clear()
        with self.assertRaisesRegex(LocalFileAccessError, "kein lesbarer"):
            self.reader.list_directory(".")

    def test_open_image_is_read_only_and_source_stays_unchanged(self):
        path = self.first / "rack.png"; original = b"\x89PNG\r\n\x1a\ncontent"; path.write_bytes(original)
        resource = self.reader.open_resource("rack.png")
        self.assertEqual("image", resource["type"])
        self.assertTrue(resource["content"].startswith("data:image/png;base64,"))
        self.assertEqual(original, path.read_bytes())

    def test_unique_bare_filename_resolves_in_nested_directory(self):
        nested = self.first / "EVE-Glubsch"; nested.mkdir()
        image = nested / "EVE-Glubsch Odysee.png"; image.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.assertEqual(image.resolve(), self.reader.resolve("EVE-Glubsch Odysee.png", directory=False))

    def test_unique_filename_recovers_from_incorrect_model_directory(self):
        nested = self.first / "EVE-Glubsch"; nested.mkdir()
        image = nested / "EVE-Glubsch Odysee.png"; image.write_bytes(b"\x89PNG\r\n\x1a\n")
        resolved = self.reader.resolve("root:0/EVE Unterlagen/EVE-Glubsch Odysee.png", directory=False)
        self.assertEqual(image.resolve(), resolved)

    def test_duplicate_bare_filename_is_not_guessed(self):
        (self.first / "duplicate.txt").write_text("first", encoding="utf-8")
        (self.second / "duplicate.txt").write_text("second", encoding="utf-8")
        with self.assertRaisesRegex(LocalFileAccessError, "nicht eindeutig"):
            self.reader.resolve("duplicate.txt", directory=False)

    def test_default_listing_and_search_do_not_hide_late_entries(self):
        for index in range(520):
            (self.first / f"entry-{index:03d}.txt").write_text(
                f"needle {index}", encoding="utf-8",
            )

        listing = self.reader.list_directory("root:0/")
        matches = self.reader.search_files("needle", include_content=True)

        self.assertEqual(521, len(listing["entries"]))
        self.assertFalse(listing["truncated"])
        self.assertEqual(520, len(matches))


class LocalFileCapabilityTest(unittest.TestCase):
    def test_self_description_exposes_complete_read_only_boundary(self):
        capability = LocalFileCapability(LocalFileReader(lambda: []), object())

        description = capability.self_descriptions()[0]

        self.assertIn("strikt read-only", description.statement)
        self.assertIn("weder verändern noch löschen", description.statement)
        self.assertEqual(
            "list_directory,search_files,read_text,search_text,open_resource",
            description.operation,
        )

    def test_structured_search_and_open_use_published_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "rack.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            capability = LocalFileCapability(LocalFileReader(lambda: [str(root)]), object())
            found = capability.execute_operation("search_files", {"query": "rack", "limit": 5})
            self.assertEqual("rack.png", found["result"][0]["name"])
            opened = capability.execute_operation("open_resource", {"path": found["result"][0]["path"]})
            self.assertEqual("local_file", opened["resources"][0]["source"])

    def test_unpublished_structured_operation_is_rejected(self):
        capability = LocalFileCapability(LocalFileReader(lambda: []), object())
        with self.assertRaises(ValueError):
            capability.execute_operation("delete", {"path": "anything"})


    def test_persisted_local_image_survives_root_removal_and_enters_visual_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); shared = base / "shared"; shared.mkdir()
            image = shared / "Glubsch-Rack.png"; image.write_bytes(b"\x89PNG\r\n\x1a\n")
            roots = [str(shared)]
            resource = LocalFileReader(lambda: roots).open_resource(str(image))
            store = ConversationStore(EveDatabase(base / "eve.db"))
            conversation = store.create("Lokales Glubsch-Bild")["id"]
            store.append_turn(
                conversation, "Zeig das Glubsch-Bild", "Hier ist das Rack-Bild.",
                assistant_attachments=[resource],
            )
            asset = store.messages(conversation)["messages"][1]["attachments"][0]
            roots.clear(); image.unlink()
            restarted = ConversationStore(EveDatabase(base / "eve.db"))
            self.assertTrue(restarted.read_asset(asset["id"])[1])
            hits = PersistentSearch(restarted.database).visual_assets("Glubsch Rack")
            self.assertEqual(asset["id"], hits[0]["asset_id"])
            self.assertNotIn("base64", json.dumps(hits))


if __name__ == "__main__": unittest.main()
