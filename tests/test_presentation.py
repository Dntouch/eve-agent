import tempfile
import unittest
from pathlib import Path

from eve_agent.presentation import PresentationStore, validate_presentation


class PresentationStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PresentationStore(Path(self.temp.name))
        self.document = {
            "title": "Übersicht",
            "layout": "grid",
            "components": [
                {"type": "metric", "label": "Temperatur", "value": "21,4 °C"},
                {"type": "progress", "label": "Fortschritt", "value": 73},
                {"type": "image", "content": "/runtime/resource/123"},
            ],
        }

    def test_create_assigns_id_and_activates_presentation(self):
        created = self.store.create(self.document)
        self.assertTrue(created["active"])
        self.assertRegex(created["id"], r"^[0-9a-f]{32}$")
        self.assertEqual(created["presentation"], self.document)

    def test_execute_if_revision_rejects_obsolete_command(self):
        created = self.store.create(self.document)
        with self.assertRaises(RuntimeError):
            self.store.execute_if_revision(
                {"action": "close", "id": created["id"]},
                expected_revision=created["revision"] - 1,
            )
        self.assertTrue(self.store.read()["active"])
        self.assertEqual(self.store.read(), created)

    def test_update_keeps_id_and_replaces_document(self):
        created = self.store.create(self.document)
        changed = {"title": "Neu", "layout": "vertical", "components": [{"type": "text", "content": "Aktuell"}]}
        updated = self.store.update(created["id"], changed)
        self.assertEqual(updated["id"], created["id"])
        self.assertGreater(updated["revision"], created["revision"])
        self.assertEqual(updated["presentation"], changed)

    def test_close_returns_to_inactive_state(self):
        created = self.store.create(self.document)
        closed = self.store.close(created["id"])
        self.assertFalse(closed["active"])
        self.assertNotIn("presentation", closed)

    def test_unknown_and_invalid_components_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unbekannter Komponententyp"):
            validate_presentation({"components": [{"type": "weather"}]})
        with self.assertRaisesRegex(ValueError, "zwischen 0 und 100"):
            validate_presentation({"components": [{"type": "progress", "value": 120}]})
        with self.assertRaisesRegex(ValueError, "nur für container"):
            validate_presentation({"components": [{"type": "text", "components": []}]})

    def test_list_accepts_strings(self):
        document = validate_presentation({"components": [{"type": "list", "items": ["Eins", "Zwei"]}]})
        self.assertEqual(document["components"][0]["items"], ["Eins", "Zwei"])

    def test_list_accepts_numbers(self):
        document = validate_presentation({"components": [{"type": "list", "items": [1, 2.5, -3]}]})
        self.assertEqual(document["components"][0]["items"], [1, 2.5, -3])

    def test_list_accepts_label_value_objects(self):
        items = [
            {"label": "Öffnungskontakt", "value": "Geschlossen"},
            {"label": "Schlossstatus", "value": "Abgeschlossen"},
        ]
        document = validate_presentation({"components": [{"type": "list", "items": items}]})
        self.assertEqual(document["components"][0]["items"], items)

    def test_list_rejects_mixed_unsupported_structures(self):
        invalid_items = [
            ["lesbar", {"label": "Status", "value": {"nested": True}}],
            [1, {"label": "Status"}],
            ["lesbar", {"label": "Status", "value": "OK", "detail": "extra"}],
            ["lesbar", ["verschachtelt"]],
        ]
        for items in invalid_items:
            with self.subTest(items=items), self.assertRaisesRegex(ValueError, r"list\.items\[1\]"):
                validate_presentation({"components": [{"type": "list", "items": items}]})

    def test_existing_presentation_components_are_unchanged(self):
        self.assertEqual(validate_presentation(self.document), self.document)

    def test_schema_has_no_data_source_vocabulary(self):
        source = Path(__file__).resolve().parents[1] / "src" / "eve_agent" / "presentation.py"
        implementation = source.read_text(encoding="utf-8").casefold()
        for forbidden in ("home_assistant", "camera", "weather", "printer", "tesla"):
            self.assertNotIn(forbidden, implementation)

    def test_media_resource_address_can_contain_large_inline_payload(self):
        payload = "data:image/png;base64," + ("A" * 200_000)
        created = self.store.create({"components": [{"type": "image", "content": payload}]})
        public = self.store.client_state()
        resource = public["presentation"]["components"][0]["content"]
        self.assertEqual(resource, f"/api/presentation/resource/{created['revision']}/0")
        mime, content = self.store.read_resource(created["revision"], "0")
        self.assertEqual(mime, "image/png")
        self.assertEqual(content, b"\x00" * 150_000)
