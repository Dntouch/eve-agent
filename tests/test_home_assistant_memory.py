import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eve_agent.home_assistant_inventory import HomeAssistantInventory
from eve_agent.memory_compiler import MemoryCompiler
from eve_agent.memory_v2 import MemoryV2Runtime
from eve_agent.semantic_links import SemanticLinks
from eve_agent.storage import EveDatabase
from eve_agent.training_packages import FORMAT, LANGUAGE_PACKAGE, HomeAssistantTrainingAdapter
from tests.test_home_assistant_inventory import FakeHomeAssistant


class HomeAssistantMemoryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = EveDatabase(Path(self.temporary.name) / "eve.db")
        self.home = FakeHomeAssistant()
        self.home.config = {"language": "de"}
        self.provider = self.home.semantic_provider_identity()
        self.memory = MemoryV2Runtime(self.database, MemoryCompiler(self.database))

    def scan(self):
        return HomeAssistantInventory(self.home, self.database).run()

    def import_profiles(self, *entries):
        return HomeAssistantTrainingAdapter(
            self.database, self.memory.home_assistant_memory, home_assistant=self.home,
        ).import_package({
            "format": FORMAT, "provider": "home_assistant", "kind": LANGUAGE_PACKAGE,
            "locale": "de",
            "metadata": {"name": "Testprofile", "version": "1", "publisher": "tests"},
            "entries": list(entries),
        })

    @staticmethod
    def profile(identifier, domain, surfaces, *, actions=None, properties=None, parameters=None):
        return {
            "id": identifier, "domain": domain, "surfaces": surfaces,
            "actions": actions or {}, "properties": properties or {},
            "parameters": parameters or {}, "source_version": "test-v1",
        }

    def test_inventory_activates_only_grounded_portable_language_profiles(self):
        baseline = self.scan()
        self.assertEqual(0, baseline["language_profiles"]["active"])
        self.import_profiles(
            self.profile(
                "sensor.de", "sensor", ["Sensor", "Stromverbrauch"],
                properties={"power": ["Wert", "Stromverbrauch"]},
            ),
            self.profile(
                "light.de", "light", ["Licht", "Lampe"],
                actions={"light.turn_on": {"surfaces": ["einschalten"]}},
            ),
        )
        result = self.scan()

        self.assertEqual(2, result["language_profiles"]["active"])
        self.assertEqual(2, result["language_profiles"]["relations"]["active"])
        hints = self.memory.home_assistant_language_hints(
            "Wie viel Stromverbrauch hat das Büro?", self.provider,
        )
        self.assertIn("sensor", {item["domain"] for item in hints})
        sensor = next(item for item in hints if item["domain"] == "sensor")
        self.assertEqual(1, sensor["grounded_entity_count"])
        self.assertEqual(1, len(sensor["grounding_relation_ids"]))
        with self.database.connect() as connection:
            profiles = connection.execute(
                """SELECT payload_json FROM memory_claims WHERE lifecycle='active'
                   AND json_extract(payload_json,'$.kind')='home_assistant_language_profile'"""
            ).fetchall()
        self.assertEqual(2, len(profiles))

    def test_language_profile_is_not_retrievable_without_its_inventory_relation(self):
        self.import_profiles(self.profile(
            "sensor.de", "sensor", ["Sensor", "Stromverbrauch"],
            properties={"power": ["Wert", "Stromverbrauch"]},
        ))
        self.scan()
        with self.database.connect() as connection:
            profile = connection.execute(
                """SELECT id FROM memory_claims WHERE lifecycle='active'
                   AND json_extract(payload_json,'$.kind')='home_assistant_language_profile'
                   AND json_extract(payload_json,'$.domain')='sensor'"""
            ).fetchone()
            connection.execute(
                "DELETE FROM memory_relations WHERE to_claim_id=? AND relation_type='refines'",
                (profile["id"],),
            )

        hints = self.memory.home_assistant_language_hints(
            "Wie viel Stromverbrauch hat das Büro?", self.provider,
        )

        self.assertNotIn("sensor", {item["domain"] for item in hints})

    def test_learned_action_targets_real_inventory_claim_and_requires_the_edge(self):
        self.scan()
        links = SemanticLinks(self.database)
        context = {
            "conversation_id": "c", "history": [], "focus": [],
            "pending": None, "task_active": False,
        }
        text = "Schalte das Bürolicht aus"
        plan = {
            "effect": "write",
            "actions": [{
                "type": "call_service", "entity_id": "light.office",
                "service": "light.turn_off", "data": {},
            }],
            "semantic_learning": {
                "status": "resolved", "context_keys": [], "user_grounding": "explicit",
                "uncertainties": [], "utterance_quote": text,
                "basis": "Explizite, provider-validierte Ausführung.",
                "action_link": {
                    "kind": "new", "representation_id": "", "anchor_claim_id": "",
                    "meaning": "Bürolicht ausschalten",
                    "basis": "Explizite, provider-validierte Ausführung.",
                },
            },
        }
        claim_id = links.learn(
            text, context, self.provider, plan, {"status": "success"},
            source_ref="test:ha-action", provider_validated=True,
            exact_replay_authorized=True,
        )
        experience = links.experience(claim_id)
        group_id = experience["action_representation_id"]
        candidates = links.action_candidates(
            self.provider, context=context, effect="write", resources=["light.office"],
        )
        self.assertEqual(1, len(candidates))
        self.assertEqual("light.office", candidates[0]["target_relations"][0]["entity_id"])
        self.assertIsNotNone(links.lookup(text, context, self.provider))

        with self.database.connect() as connection:
            target = connection.execute(
                """SELECT r.id FROM memory_relations r
                   JOIN memory_claims c ON c.id=r.to_claim_id
                   WHERE r.from_claim_id=? AND c.claim_kind='provider_binding'""",
                (group_id,),
            ).fetchone()
            self.assertIsNotNone(target)
            connection.execute("DELETE FROM memory_relations WHERE id=?", (target["id"],))

        with patch.object(links, "sync_action_relations", return_value={}):
            self.assertEqual([], links.action_candidates(
                self.provider, context=context, effect="write", resources=["light.office"],
            ))
            self.assertIsNone(links.lookup(text, context, self.provider))

    def test_scene_relation_reuses_real_binding_for_a_proven_equivalent_action(self):
        members = ["cover.office_left", "cover.office_right"]
        for entity_id in members:
            self.home.entities.append({
                "entity_id": entity_id, "name": entity_id, "area": "Office",
                "device_class": "shutter", "unit": None, "state_class": None,
                "supported_features": 3,
                "services": ["cover.open_cover", "cover.close_cover"],
                "service_fields": {"cover.open_cover": [], "cover.close_cover": []},
                "members": [], "state": "open",
            })
        self.home.entities.append({
            "entity_id": "scene.office_covers_down", "name": "Office covers down",
            "area": "Office", "device_class": None, "unit": None,
            "state_class": None, "supported_features": 0,
            "services": ["scene.turn_on"],
            "service_fields": {"scene.turn_on": ["transition"]},
            "members": members, "state": "scening",
        })
        self.scan()
        links = SemanticLinks(self.database)
        context = {"conversation_id": "c", "history": [], "focus": [],
                   "pending": None, "task_active": False}
        text = "Fahre alle Büro-Rollos runter"
        plan = {
            "effect": "write",
            "actions": [{"type": "call_service", "entity_id": entity_id,
                         "service": "cover.close_cover", "data": {}}
                        for entity_id in members],
            "semantic_learning": {
                "status": "resolved", "context_keys": [], "user_grounding": "explicit",
                "uncertainties": [], "utterance_quote": text,
                "basis": "Explizite, provider-validierte Ausführung.",
                "action_link": {"kind": "new", "representation_id": "",
                                "anchor_claim_id": "", "meaning": "Alle Büro-Rollos schließen",
                                "basis": "Explizite, provider-validierte Ausführung."},
            },
        }
        claim_id = links.learn(
            text, context, self.provider, plan, {"status": "success"},
            source_ref="test:cover-action", provider_validated=True,
            exact_replay_authorized=True,
        )
        reference = links.action_candidates(self.provider, context=context)[0]

        learned = links.record_action_resource_relation(
            "scene.office_covers_down", reference, provider=self.provider,
            source_ref="test:scene-learning", basis="Explicit scene explanation.",
            user_utterance="Dafür gibt es scene.office_covers_down.",
        )

        self.assertEqual("stored", learned["status"])
        hit = links.lookup(text, context, self.provider)
        hit = links.apply_action_resource_executor(hit, self.provider)
        self.assertEqual([{
            "type": "call_service", "entity_id": "scene.office_covers_down",
            "service": "scene.turn_on", "data": {},
        }], hit["plan"]["actions"])
        with self.database.connect() as connection:
            targets = connection.execute(
                "SELECT count(*) FROM memory_relations WHERE from_claim_id=? AND relation_type='refines'",
                (learned["relation_id"],),
            ).fetchone()[0]
        self.assertEqual(2, targets)

    def test_rollo_and_jalousie_resolve_to_memory_profile_without_python_mapping(self):
        self.home.entities.append({
            "entity_id": "cover.office", "name": "Office blind", "area": "Office",
            "device_class": "shutter", "unit": None, "state_class": None,
            "supported_features": 15,
            "services": ["cover.open_cover", "cover.close_cover", "cover.set_cover_position"],
            "service_fields": {
                "cover.open_cover": [], "cover.close_cover": [],
                "cover.set_cover_position": ["position"],
            },
            "members": [], "state": "open",
        })
        self.scan()
        self.import_profiles(self.profile(
            "cover.de", "cover", ["Rollo", "Jalousie"],
            actions={
                "cover.open_cover": {"surfaces": ["öffnen"]},
                "cover.close_cover": {"surfaces": ["schließen"]},
                "cover.set_cover_position": {"surfaces": ["stellen"]},
            },
            parameters={"position": ["Position", "Prozent", "%"]},
        ))

        hints = self.memory.home_assistant_language_hints(
            "Stelle die Jalousie auf 50 Prozent", self.provider,
        )

        cover = next(item for item in hints if item["domain"] == "cover")
        self.assertIn("Jalousie", cover["surfaces"])
        self.assertNotIn("actions", cover)
        self.assertEqual([], cover["property_names"])
        selected = self.memory.home_assistant_language_profile("cover", self.provider)
        self.assertIn("cover.set_cover_position", selected["actions"])
        self.assertEqual(["Position", "Prozent", "%"], selected["parameters"]["position"])

    def test_direct_camera_operation_is_grounded_by_camera_inventory(self):
        self.home.entities.append({
            "entity_id": "camera.front_door", "name": "Front door camera", "area": "Hall",
            "device_class": None, "unit": None, "state_class": None,
            "supported_features": 0, "services": [], "service_fields": {},
            "members": [], "state": "idle",
        })
        self.scan()
        self.import_profiles(self.profile(
            "camera.de", "camera", ["Kamera", "Kamerabild"],
            actions={"get_camera_snapshot": {"surfaces": ["Bild zeigen"]}},
        ))

        hints = self.memory.home_assistant_language_hints(
            "Zeige mir ein Kamerabild der Haustür", self.provider,
        )

        camera = next(item for item in hints if item["domain"] == "camera")
        self.assertNotIn("actions", camera)
        selected = self.memory.home_assistant_language_profile("camera", self.provider)
        self.assertIn("get_camera_snapshot", selected["actions"])

    def test_language_catalog_does_not_decide_semantic_relevance_in_python(self):
        self.scan()
        self.import_profiles(
            self.profile(
                "sensor.de", "sensor", ["Messfühler"],
                actions={"get_state": {"surfaces": ["aktuellen Wert anzeigen"]}},
            ),
            self.profile(
                "light.de", "light", ["Leuchte"],
                actions={"get_state": {"surfaces": ["aktuellen Zustand anzeigen"]}},
            ),
        )

        catalog = self.memory.home_assistant_language_hints(
            "Wie lautet der Messfühlerwert?", self.provider,
        )
        self.assertEqual({"light", "sensor"}, {item["domain"] for item in catalog})
        self.assertTrue(all("actions" not in item for item in catalog))
        sensor = self.memory.home_assistant_language_profile("sensor", self.provider)
        self.assertIn("get_state", sensor["actions"])

    def test_area_policy_is_visible_versioned_editable_and_applied_only_to_aggregate(self):
        self.home.entities.append({
            "entity_id": "light.carport", "name": "Carport Light", "area": "Carport",
            "device_class": None, "unit": None, "state_class": None,
            "supported_features": 1, "services": ["light.turn_on", "light.turn_off"],
            "service_fields": {"light.turn_on": [], "light.turn_off": []},
            "members": [], "state": "on",
        })
        self.scan()

        stored = self.memory.set_home_assistant_aggregate_policy(
            self.provider, ["Carport"], source_ref="test:user-policy",
        )

        self.assertEqual("stored", stored["status"])
        self.assertEqual(["Carport"], stored["policy"]["excluded_areas"])
        self.assertTrue(next(item for item in stored["areas"] if item["area"] == "Carport")["excluded"])
        bindings = self.memory.inventory_bindings(namespace="light", limit=64)["bindings"]
        aggregate = self.memory.apply_home_assistant_aggregate_policy(
            self.provider, bindings, effect="write", explicit_target=False,
        )
        explicit = self.memory.apply_home_assistant_aggregate_policy(
            self.provider, bindings, effect="write", explicit_target=True,
        )
        read = self.memory.apply_home_assistant_aggregate_policy(
            self.provider, bindings, effect="read", explicit_target=False,
        )
        self.assertNotIn("light.carport", {item["entity_id"] for item in aggregate["bindings"]})
        self.assertIn("light.carport", {item["entity_id"] for item in explicit["bindings"]})
        self.assertIn("light.carport", {item["entity_id"] for item in read["bindings"]})

        replaced = self.memory.set_home_assistant_aggregate_policy(
            self.provider, [], source_ref="test:user-policy-edit",
        )
        self.assertEqual(2, replaced["policy"]["version"])
        self.assertEqual([], replaced["policy"]["excluded_areas"])
        with self.database.connect() as connection:
            self.assertEqual(1, connection.execute(
                """SELECT count(*) FROM memory_relations
                   WHERE relation_type='supersedes'"""
            ).fetchone()[0])

    def test_policy_rejects_unknown_area_instead_of_inventing_it(self):
        self.scan()
        with self.assertRaisesRegex(ValueError, "Unbekannte Home-Assistant-Area"):
            self.memory.set_home_assistant_aggregate_policy(
                self.provider, ["Imaginary Garage"], source_ref="test:invalid",
            )


if __name__ == "__main__":
    unittest.main()
