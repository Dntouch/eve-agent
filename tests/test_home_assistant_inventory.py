import json
import tempfile
import unittest
from pathlib import Path

from eve_agent.home_assistant_inventory import HomeAssistantInventory
from eve_agent.memory_compiler import MemoryCompiler
from eve_agent.memory_v2 import MemoryV2Runtime
from eve_agent.storage import EveDatabase


class FakeHomeAssistant:
    configured = True

    def __init__(self):
        self.entities = [
            {
                "entity_id": "sensor.office_power",
                "name": "Office Power",
                "area": "Office",
                "device_class": "power",
                "unit": "W",
                "state_class": "measurement",
                "supported_features": 0,
                "services": [],
                "members": [],
                "state": "12",
            },
            {
                "entity_id": "light.office",
                "name": "Office Light",
                "area": "Office",
                "device_class": None,
                "unit": None,
                "state_class": None,
                "supported_features": 1,
                "services": ["light.turn_on", "light.turn_off"],
                "service_fields": {"light.turn_on": ["brightness_pct"], "light.turn_off": []},
                "members": ["light.office_left", "light.office_right"],
                "state": "unavailable",
            },
        ]
        self.calls = 0

    def semantic_provider_identity(self):
        return {"provider": "home_assistant", "endpoint": "http://ha.local"}

    def inventory_catalog(self):
        self.calls += 1
        return {"entities": list(self.entities)}


class HomeAssistantInventoryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = EveDatabase(Path(self.temporary.name) / "eve.db")
        self.home = FakeHomeAssistant()
        self.inventory = HomeAssistantInventory(self.home, self.database)

    def claims(self):
        with self.database.connect() as connection:
            return [dict(row) for row in connection.execute(
                """SELECT * FROM memory_claims
                   WHERE json_extract(payload_json,'$.inventory_source')='home_assistant'
                   ORDER BY canonical_key"""
            ).fetchall()]

    def test_scan_stores_provider_facts_in_memory_without_language_inference(self):
        result = self.inventory.run()
        self.assertEqual("read", result["effect"])
        self.assertEqual(2, result["counts"]["created"])
        self.assertEqual(1, result["counts"]["unavailable"])
        self.assertEqual(1, self.home.calls)
        claims = self.claims()
        self.assertEqual(2, len(claims))
        self.assertTrue(all(item["claim_kind"] == "provider_binding" for item in claims))
        self.assertTrue(all(item["lifecycle"] == "active" for item in claims))
        payloads = [json.loads(item["payload_json"]) for item in claims]
        self.assertEqual(
            {"light.office", "sensor.office_power"},
            {item["external_reference"] for item in payloads},
        )
        self.assertNotIn("Lampe", json.dumps(payloads, ensure_ascii=False))
        light = next(item for item in payloads if item["external_reference"] == "light.office")
        self.assertEqual(
            ["light.office_left", "light.office_right"],
            light["provider_metadata"]["members"],
        )
        self.assertEqual(
            {"light.turn_off": [], "light.turn_on": ["brightness_pct"]},
            light["provider_metadata"]["service_fields"],
        )

    def test_equal_names_keep_distinct_resource_slots_and_repair_old_slot(self):
        self.home.entities[1]["name"] = self.home.entities[0]["name"]
        self.inventory.run()
        claims = self.claims()
        self.assertEqual(2, len({c["slot_key"] for c in claims}))
        with self.database.connect() as connection:
            connection.execute("UPDATE memory_claims SET slot_key='old-shared-slot'")
        result = self.inventory.run()
        self.assertEqual(2, result["counts"]["updated"])
        self.assertEqual(2, len({c["slot_key"] for c in self.claims()}))

    def test_runtime_self_description_publishes_read_only_inventory_capability(self):
        description = self.inventory.self_descriptions()[0]
        self.assertEqual("home_assistant.inventory", description.capability_id)
        self.assertEqual("scan", description.operation)
        self.assertIn("rein lesend", description.statement)

    def test_rescan_is_idempotent_and_records_fresh_provider_evidence(self):
        first = self.inventory.run()
        second = self.inventory.run()
        self.assertEqual(0, second["counts"]["created"])
        self.assertEqual(2, second["counts"]["unchanged"])
        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
        with self.database.connect() as connection:
            self.assertEqual(4, connection.execute(
                "SELECT count(*) FROM memory_evidence WHERE evidence_type='provider_inventory'"
            ).fetchone()[0])

    def test_duplicate_provider_rows_are_bounded_to_one_claim(self):
        self.home.entities.append(dict(self.home.entities[0]))

        result = self.inventory.run()

        self.assertEqual(2, result["counts"]["total"])
        self.assertEqual(1, result["counts"]["skipped"])
        self.assertEqual(2, len(self.claims()))

    def test_long_provider_entity_id_is_preserved_as_identity(self):
        long_id = (
            "sensor.energy_battery_senec_battery_charge_power_"
            "senec_battery_discharge_power_net_power"
        )
        self.home.entities = [{
            "entity_id": long_id, "name": "SENEC Net Power", "area": None,
            "device_class": "power", "unit": "W", "state_class": "measurement",
            "supported_features": 0, "services": [], "members": [], "state": "1",
        }]

        result = self.inventory.run()

        self.assertEqual(1, result["counts"]["created"])
        payload = json.loads(self.claims()[0]["payload_json"])
        self.assertEqual(long_id, payload["external_reference"])
        self.assertNotIn("[REDACTED]", payload["external_reference"])

    def test_changed_removed_and_returned_entities_follow_memory_lifecycle(self):
        self.inventory.run()
        self.home.entities[0] = {**self.home.entities[0], "area": "Studio"}
        self.home.entities.pop()
        changed = self.inventory.run()
        self.assertEqual(1, changed["counts"]["updated"])
        self.assertEqual(1, changed["counts"]["retired"])
        self.home.entities.append({
            "entity_id": "light.office", "name": "Office Light", "area": "Office",
            "device_class": None, "unit": None, "state_class": None,
            "supported_features": 1, "services": ["light.turn_on"], "state": "on",
        })
        returned = self.inventory.run()
        self.assertEqual(1, returned["counts"]["restored"])
        self.assertTrue(all(item["lifecycle"] == "active" for item in self.claims()))

    def test_inventory_claim_is_available_to_memory_provider_binding_retrieval(self):
        self.inventory.run()
        runtime = MemoryV2Runtime(self.database, MemoryCompiler(self.database))
        bindings = runtime.provider_bindings("Office Power")
        self.assertIn("sensor.office_power", {
            item["entity_id"] for item in bindings
        })

    def test_exact_namespace_inventory_lookup_is_bounded_and_provider_free(self):
        self.inventory.run()
        runtime = MemoryV2Runtime(self.database, MemoryCompiler(self.database))
        calls = self.home.calls

        result = runtime.inventory_bindings(namespace="light", cursor=0, limit=1)

        self.assertEqual(1, result["total"])
        self.assertEqual("light.office", result["bindings"][0]["entity_id"])
        self.assertEqual(["brightness_pct"], result["bindings"][0]["service_fields"]["light.turn_on"])
        self.assertEqual(calls, self.home.calls)

    def test_inventory_lookup_preserves_short_exact_provider_identity_tokens(self):
        self.home.entities = [
            {
                "entity_id": "sensor.smartplug_tv_energy_power",
                "name": "SmartPlug_TV ENERGY Power", "area": None,
                "device_class": "power", "unit": "W", "state_class": "measurement",
                "supported_features": None, "services": [], "members": [], "state": "0",
            },
            {
                "entity_id": "sensor.solar_power", "name": "Solar Power", "area": None,
                "device_class": "power", "unit": "W", "state_class": "measurement",
                "supported_features": None, "services": [], "members": [], "state": "100",
            },
        ]
        self.inventory.run()
        runtime = MemoryV2Runtime(self.database, MemoryCompiler(self.database))

        result = runtime.inventory_bindings("Leistung der TV-Bank")

        self.assertEqual(
            "sensor.smartplug_tv_energy_power", result["bindings"][0]["entity_id"],
        )
        self.assertNotIn(
            "sensor.solar_power", {item["entity_id"] for item in result["bindings"]},
        )

    def test_inventory_lookup_applies_model_selected_namespace_hint_when_available(self):
        self.home.entities = [
            {
                "entity_id": "light.tv", "name": "TV Light", "area": None,
                "device_class": None, "unit": None, "state_class": None,
                "supported_features": None, "services": [], "members": [], "state": "off",
            },
            {
                "entity_id": "sensor.tv_power", "name": "TV Power", "area": None,
                "device_class": "power", "unit": "W", "state_class": "measurement",
                "supported_features": None, "services": [], "members": [], "state": "0",
            },
        ]
        self.inventory.run()
        runtime = MemoryV2Runtime(self.database, MemoryCompiler(self.database))

        result = runtime.inventory_bindings("TV Power", namespace_hint="sensor")

        self.assertEqual(["sensor.tv_power"], [
            item["entity_id"] for item in result["bindings"]
        ])

    def test_namespace_hint_does_not_hide_an_exact_identity_in_another_domain(self):
        self.home.entities = [
            {
                "entity_id": "climate.bathroom", "name": "Thermostat Badezimmer",
                "area": "Badezimmer", "device_class": None, "unit": None,
                "state_class": None, "supported_features": None,
                "services": [], "members": [], "state": "heat",
            },
            {
                "entity_id": "sensor.guest_temperature",
                "name": "Thermostat Gästetoilette Temperatur", "area": "Flur",
                "device_class": "temperature", "unit": "°C",
                "state_class": "measurement", "supported_features": None,
                "services": [], "members": [], "state": "20",
            },
        ]
        self.inventory.run()
        runtime = MemoryV2Runtime(self.database, MemoryCompiler(self.database))

        result = runtime.inventory_bindings(
            "Badezimmer Temperatur", namespace_hint="sensor",
        )

        self.assertEqual("climate.bathroom", result["bindings"][0]["entity_id"])

    def test_inventory_lookup_matches_one_edit_provider_spelling_without_semantic_substitution(self):
        self.home.entities = [
            {
                "entity_id": "sensor.smartplug_spuelmaschine_energy_power",
                "name": "SmartPlug_Spuelmaschine ENERGY Power", "area": None,
                "device_class": "power", "unit": "W", "state_class": "measurement",
                "supported_features": None, "services": [], "members": [], "state": "0",
            },
            {
                "entity_id": "sensor.smartplug_waschmaschine_energy_power",
                "name": "SmartPlug_Waschmaschine ENERGY Power", "area": None,
                "device_class": "power", "unit": "W", "state_class": "measurement",
                "supported_features": None, "services": [], "members": [], "state": "0",
            },
        ]
        self.inventory.run()
        runtime = MemoryV2Runtime(self.database, MemoryCompiler(self.database))

        result = runtime.inventory_bindings("Spülmaschine", namespace_hint="sensor")

        self.assertIn("sensor.smartplug_spuelmaschine_energy_power", {
            item["entity_id"] for item in result["bindings"]
        })
        self.assertNotIn("sensor.smartplug_waschmaschine_energy_power", {
            item["entity_id"] for item in result["bindings"]
        })

    def test_inventory_lookup_matches_a_query_word_inside_a_longer_identity_word(self):
        self.home.entities = [{
            "entity_id": "sensor.house_power", "name": "Aktueller Hausverbrauch",
            "area": None, "device_class": "power", "unit": "W",
            "state_class": "measurement", "supported_features": None,
            "services": [], "members": [], "state": "100",
        }]
        self.inventory.run()
        runtime = MemoryV2Runtime(self.database, MemoryCompiler(self.database))

        result = runtime.inventory_bindings("Stromverbrauch Haus", namespace_hint="sensor")

        self.assertEqual(["sensor.house_power"], [
            item["entity_id"] for item in result["bindings"]
        ])

    def test_switching_provider_endpoint_retires_only_old_inventory_claims(self):
        self.inventory.run()
        self.home.semantic_provider_identity = lambda: {
            "provider": "home_assistant", "endpoint": "http://replacement-ha.local",
        }

        result = self.inventory.run()

        self.assertEqual(2, result["counts"]["created"])
        self.assertEqual(2, result["counts"]["retired"])
        claims = self.claims()
        self.assertEqual(2, sum(item["lifecycle"] == "active" for item in claims))
        self.assertEqual(2, sum(item["lifecycle"] == "retired" for item in claims))

    def test_secret_like_provider_text_is_redacted(self):
        self.home.entities = [{
            "entity_id": "sensor.secret", "name": "token=very-secret-value",
            "area": None, "device_class": None, "unit": None, "state_class": None,
            "supported_features": None, "services": [], "members": [], "state": "on",
        }]
        self.inventory.run()
        encoded = json.dumps(self.claims(), ensure_ascii=False)
        self.assertNotIn("very-secret-value", encoded)
        self.assertIn("[REDACTED]", encoded)


if __name__ == "__main__":
    unittest.main()
