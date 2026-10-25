import copy
import json
import tempfile
import unittest
from pathlib import Path

from eve_agent.home_assistant_inventory import HomeAssistantInventory
from eve_agent.home_assistant_memory import HomeAssistantMemory
from eve_agent.storage import EveDatabase
from eve_agent.training_packages import (
    FORMAT,
    HomeAssistantTrainingAdapter,
    TrainingPackageManager,
)
from tests.test_home_assistant_inventory import FakeHomeAssistant


class TrainingPackagesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = EveDatabase(Path(self.temporary.name) / "eve.db")
        self.home = FakeHomeAssistant()
        self.memory = HomeAssistantMemory(self.database)
        self.inventory = HomeAssistantInventory(self.home, self.database)
        self.adapter = HomeAssistantTrainingAdapter(
            self.database, self.memory,
            home_assistant=self.home, inventory=self.inventory,
        )
        self.manager = TrainingPackageManager([self.adapter])

    def package(self):
        return {
            "format": FORMAT,
            "provider": "home_assistant",
            "kind": "language",
            "locale": "de",
            "entries": [{
                "id": "profile.light",
                "domain": "light",
                "surfaces": ["Leuchtkörper"],
                "actions": {
                    "light.turn_on": {"surfaces": ["aktivieren"]},
                    "light.turn_off": {"surfaces": ["deaktivieren"]},
                },
                "properties": {"power": ["Betriebszustand"]},
                "parameters": {},
                "source_version": "test-v1",
            }],
            "metadata": {
            "name": "Gemeinschaft Licht",
            "version": "1.0.0",
            "publisher": "eve-community",
            "license": "CC0-1.0",
            "description": "Generische Lichtbegriffe.",
            },
        }

    def import_fixture_profiles(self, *, ambiguous=False):
        package = self.package()
        if ambiguous:
            package["entries"].append({
                "id": "profile.sensor",
                "domain": "sensor",
                "surfaces": ["Leuchtkörper"],
                "actions": {"get_state": {"surfaces": ["auslesen"]}},
                "properties": {"power": ["Betriebszustand"]},
                "parameters": {},
                "source_version": "test-v1",
            })
        self.adapter.import_package(package)

    def test_manager_is_provider_independent_and_reports_installed_adapters(self):
        overview = self.manager.overview(locale="de")

        self.assertEqual(FORMAT, overview["format"])
        self.assertEqual(["home_assistant"], [item["provider"] for item in overview["providers"]])
        with self.assertRaisesRegex(ValueError, "kein Trainingsadapter"):
            self.manager.export("unknown_provider", "language")

    def test_language_export_contains_no_local_inventory_or_provider_access_data(self):
        self.inventory.run()
        self.import_fixture_profiles()

        package = self.adapter.export("language", locale="de")
        encoded = json.dumps(package, ensure_ascii=False)

        self.assertEqual(FORMAT, package["format"])
        self.assertEqual("home_assistant", package["provider"])
        self.assertEqual("language", package["kind"])
        self.assertNotIn("light.office", encoded)
        self.assertNotIn("Office", encoded)
        self.assertNotIn("ha.local", encoded)
        self.assertNotIn("entity_id", encoded)
        self.assertEqual(package, self.adapter.validate(package))
        overview = self.adapter.overview(locale="de")
        self.assertIn("profile.light", {
            item["id"] for item in overview["export_entries"] if item["kind"] == "language"
        })

    def test_preview_and_import_are_idempotent_and_do_not_call_provider(self):
        package = self.package()
        calls = self.home.calls

        preview = self.manager.preview(package)
        first = self.manager.import_package(package)
        second = self.manager.import_package(package)

        self.assertEqual(1, preview["changes"]["new"])
        self.assertFalse(preview["requires_provider_action"])
        self.assertEqual("imported", first["status"])
        self.assertEqual(1, second["changes"]["unchanged"])
        self.assertEqual(calls, self.home.calls)
        with self.database.connect() as connection:
            claims = connection.execute(
                """SELECT count(*) FROM memory_claims
                   WHERE json_extract(payload_json,'$.kind')='portable_training_language_profile'"""
            ).fetchone()[0]
            evidence = connection.execute(
                "SELECT count(*) FROM memory_evidence WHERE evidence_type='training_package_import'"
            ).fetchone()[0]
        self.assertEqual(1, claims)
        self.assertEqual(1, evidence)

    def test_imported_profile_is_grounded_only_against_local_inventory(self):
        self.inventory.run()
        package = self.package()
        package["entries"][0]["surfaces"].append("Leuchtkörper")

        result = self.manager.import_package(package)
        hints = self.memory.language_hints(
            "Leuchtkörper im Büro", self.home.semantic_provider_identity(), locale="de",
        )

        self.assertGreaterEqual(result["grounding"]["relations"]["active"], 1)
        light = next(item for item in hints if item["domain"] == "light")
        self.assertEqual(1, light["grounded_entity_count"])
        self.assertIn("Leuchtkörper", light["surfaces"])

    def test_modified_integrity_and_private_fields_are_rejected(self):
        self.import_fixture_profiles()
        package = self.adapter.export("language", locale="de", entry_ids=["profile.light"])
        tampered = copy.deepcopy(package)
        tampered["entries"][0]["surfaces"].append("Manipuliert")
        with self.assertRaisesRegex(ValueError, "Prüfsumme"):
            self.manager.preview(tampered)

        private = self.package()
        private["entries"][0]["entity_id"] = "light.private"
        with self.assertRaisesRegex(ValueError, "nicht veröffentlichte Felder"):
            self.manager.preview(private)

    def test_training_is_read_only_and_generates_shareable_ambiguities(self):
        self.inventory.run()
        self.import_fixture_profiles(ambiguous=True)
        calls = self.home.calls

        result = self.manager.train("home_assistant", refresh_inventory=False, locale="de")
        package = self.manager.export("home_assistant", "ambiguities", locale="de")

        self.assertEqual("read", result["effect"])
        self.assertEqual(0, result["llm_requests"])
        self.assertEqual(calls, self.home.calls)
        self.assertGreater(len(package["entries"]), 0)
        self.assertEqual(package, self.adapter.validate(package))
        self.assertNotIn("light.office", json.dumps(package, ensure_ascii=False))

    def test_unsigned_and_present_signature_are_explicit_in_preview(self):
        package = self.package()
        self.assertEqual("unsigned", self.manager.preview(package)["signature"])
        package["signature"] = {
            "algorithm": "future-test", "key_id": "community-key", "value": "abc",
        }
        self.assertEqual("present_unverified", self.manager.preview(package)["signature"])


if __name__ == "__main__":
    unittest.main()
