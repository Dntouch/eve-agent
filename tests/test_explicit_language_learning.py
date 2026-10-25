import json
import tempfile
import unittest
from pathlib import Path
from eve_agent.semantic_inspector import SemanticInspector
from eve_agent.semantic_links import (
    LANGUAGE_RELATION_SCOPE, SIMILARITY_RELATION_SCOPE, SemanticLinks,
)
from eve_agent.storage import EveDatabase


class ExplicitLanguageRelationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "eve.db"
        self.db = EveDatabase(self.path)
        self.links = SemanticLinks(self.db, {}, {"mode": "active"})
        self.provider = {"provider": "fixture", "endpoint": "memory://provider"}
        self.context = {
            "conversation_id": "conversation-a", "history": [], "focus": [],
            "pending": None, "task_active": False,
        }
        self.turn = 0

    @staticmethod
    def plan(entity, service):
        return {
            "effect": "write",
            "actions": [{"type": "call_service", "entity_id": entity, "service": service}],
        }

    def confirmed_action(self, text, entity="light.flur", service="light.turn_off"):
        self.turn += 1
        plan = self.plan(entity, service)
        plan["semantic_learning"] = {
            "status": "resolved", "context_keys": [], "user_grounding": "explicit",
            "uncertainties": [], "utterance_quote": text, "basis": "Fixture evidence.",
            "action_link": {
                "kind": "new", "representation_id": "", "anchor_claim_id": "",
                "meaning": "Fixture action", "basis": "Fixture action relation.",
            },
        }
        claim_id = self.links.learn(
            text, self.context, self.provider, plan, {"status": "success"},
            source_ref=f"fixture:{self.turn}", provider_validated=True,
        )
        self.links.decide(claim_id, confirmed=True, source_ref=f"confirm:{self.turn}")
        return claim_id

    def relation(self, surfaces, *, context_keys=None, utterance=None):
        return self.links.record_language_relation(
            "surface_equivalence", surfaces=surfaces, polarity="positive",
            context=self.context, context_keys=context_keys or [], provider=self.provider,
            source_ref=f"language:{self.turn}:{len(surfaces)}", basis="Explicit fixture declaration.",
            user_utterance=utterance or " und ".join(surfaces),
        )

    def test_multiple_general_surfaces_persist_without_resource_binding(self):
        result = self.relation(
            ["Rolllade", "Rollo", "Rollläden"],
            utterance="Andere Wörter für Rolllade sind Rollo oder Rollläden.",
        )
        self.assertEqual("stored", result["status"])
        stored = self.links.language_relations(include_history=True)
        self.assertEqual(1, len(stored))
        self.assertEqual("surface_equivalence", stored[0]["relation_kind"])
        self.assertEqual(["Rolllade", "Rollo", "Rollläden"], stored[0]["surfaces"])
        self.assertIsNone(stored[0]["provider"])
        self.assertIsNone(stored[0]["resource_identity"])
        self.assertEqual("confirmed", stored[0]["confirmation"])
        restarted = SemanticLinks(EveDatabase(self.path))
        self.assertEqual(result["relation_id"], restarted.language_relations()[0]["id"])

    def test_resource_alias_resolves_only_confirmed_exact_source_evidence(self):
        source_claim = self.confirmed_action("Schalte das Licht im Flur aus.")
        result = self.links.record_language_relation(
            "resource_alias", source_surface="Licht im Flur", new_surface="Flurlicht",
            context=self.context, context_keys=[], provider=self.provider,
            source_ref="alias:one", basis="Explicit alias.", user_utterance=
            "Ein anderes Wort für Licht im Flur ist Flurlicht.",
        )
        self.assertEqual("stored", result["status"])
        self.assertEqual("light.flur", result["resource_identity"])
        self.assertIn(source_claim, result["source_claim_ids"])
        relation = self.links.language_relations()[0]
        self.assertEqual("resource_alias", relation["relation_kind"])
        self.assertEqual("light.flur", relation["resource_identity"])
        with self.db.connect() as db:
            dependency = db.execute("""SELECT 1 FROM memory_relations
                WHERE from_claim_id=? AND to_claim_id=? AND relation_type='refines'""",
                (result["relation_id"], source_claim)).fetchone()
        self.assertIsNotNone(dependency)

    def test_unknown_ambiguous_and_conflicting_aliases_fail_closed(self):
        unknown = self.links.record_language_relation(
            "resource_alias", source_surface="Unbekanntes Licht", new_surface="Alias",
            context=self.context, context_keys=[], provider=self.provider,
            source_ref="alias:unknown", basis="Explicit alias.",
            user_utterance="Unbekanntes Licht heißt Alias.",
        )
        self.assertEqual("unresolved", unknown["status"])
        self.confirmed_action("Nutze Quelle X.", "light.one")
        self.confirmed_action("Nutze Quelle X.", "light.two")
        ambiguous = self.links.record_language_relation(
            "resource_alias", source_surface="Quelle X", new_surface="Alias X",
            context=self.context, context_keys=[], provider=self.provider,
            source_ref="alias:ambiguous", basis="Explicit alias.",
            user_utterance="Quelle X heißt Alias X.",
        )
        self.assertEqual("ambiguous", ambiguous["status"])

        self.confirmed_action("Nutze Quelle A.", "light.one")
        first = self.links.record_language_relation(
            "resource_alias", source_surface="Quelle A", new_surface="Gemeinsamer Alias",
            context=self.context, context_keys=[], provider=self.provider,
            source_ref="alias:first", basis="Explicit alias.",
            user_utterance="Quelle A heißt Gemeinsamer Alias.",
        )
        self.confirmed_action("Nutze Quelle B.", "light.two")
        conflict = self.links.record_language_relation(
            "resource_alias", source_surface="Quelle B", new_surface="Gemeinsamer Alias",
            context=self.context, context_keys=[], provider=self.provider,
            source_ref="alias:conflict", basis="Explicit alias.",
            user_utterance="Quelle B heißt Gemeinsamer Alias.",
        )
        self.assertEqual("stored", first["status"])
        self.assertEqual("conflict", conflict["status"])
        self.assertEqual(first["relation_id"], conflict["conflicting_relation_id"])

    def test_correction_is_negative_version_and_undo_restores_only_predecessor(self):
        first = self.relation(["Rollo", "Rolllade"])
        correction = self.links.correct_language_relation(
            first["relation_id"], source_ref="correction:one", basis="User rejected it.")
        self.assertEqual("corrected", correction["status"])
        active = self.links.language_relations()
        self.assertEqual(1, len(active))
        self.assertEqual("negative", active[0]["polarity"])
        self.assertEqual(2, active[0]["version"])
        undone = self.links.correct_language_relation(
            correction["relation_id"], source_ref="undo:one", basis="User undid correction.", undo=True)
        self.assertEqual(first["relation_id"], undone["restored_relation_id"])
        active = self.links.language_relations()
        self.assertEqual(first["relation_id"], active[0]["id"])
        self.assertEqual("positive", active[0]["polarity"])

    def test_targeted_correction_preserves_unrelated_edge_and_undo_removes_only_block(self):
        first = self.relation(
            ["Rolllade", "Rollo", "Rollläden"],
            utterance="Rolllade Rollo Rollläden",
        )
        correction = self.links.correct_language_relation(
            first["relation_id"], source_ref="correction:targeted",
            basis="User rejected one pair.", edge_indexes=[0])
        self.assertTrue(correction["targeted"])
        active = self.links.language_relations()
        self.assertEqual({"positive", "negative"}, {item["polarity"] for item in active})
        negative = next(item for item in active if item["polarity"] == "negative")
        self.assertEqual(["Rolllade", "Rollo"], negative["surfaces"])
        self.links.correct_language_relation(
            negative["id"], source_ref="correction:targeted:undo",
            basis="Undo targeted correction.", undo=True)
        self.assertEqual([first["relation_id"]],
                         [item["id"] for item in self.links.language_relations()])

    def test_context_and_provider_boundaries_are_exact(self):
        scoped = self.relation(["alpha", "xa"], context_keys=["conversation_id"])
        other = dict(self.context, conversation_id="conversation-b")
        self.assertEqual([], self.links.language_relations(other, self.provider))
        self.assertEqual(scoped["relation_id"],
                         self.links.language_relations(self.context, self.provider)[0]["id"])

        self.confirmed_action("Quelle Lampe", "light.flur")
        alias = self.links.record_language_relation(
            "resource_alias", source_surface="Quelle Lampe", new_surface="Flur Alias",
            context=self.context, context_keys=[], provider=self.provider,
            source_ref="provider:alias", basis="Explicit alias.",
            user_utterance="Quelle Lampe heißt Flur Alias.",
        )
        self.assertEqual("stored", alias["status"])
        relations = self.links.language_relations(
            self.context, {"provider": "fixture", "endpoint": "memory://other"})
        self.assertNotIn(alias["relation_id"], {item["id"] for item in relations})

    def _confirm_grid(self, *, linked=False):
        rows = [
            ("do xa p", "A", "p"), ("do xa r", "A", "r"),
            ("do xb p", "B", "p"), ("do xb q", "B", "q"),
            ("do xb r", "B", "r"), ("do xc p", "C", "p"),
            ("do xc q", "C", "q"),
        ]
        for index, (text, entity, service) in enumerate(rows):
            plan = self.plan(entity, service)
            if linked:
                plan["semantic_learning"] = {
                    "status": "resolved", "context_keys": [], "user_grounding": "explicit",
                    "uncertainties": [], "utterance_quote": text, "basis": "Fixture evidence.",
                    "action_link": {
                        "kind": "new", "representation_id": "", "anchor_claim_id": "",
                        "meaning": f"Fixture action {index}", "basis": "Fixture action relation.",
                    },
                }
            claim = self.links.learn(
                text, {}, self.provider, plan, {"status": "success"},
                source_ref=f"grid:{index}", provider_validated=True,
            )
            self.links.decide(claim, confirmed=True, source_ref=f"grid-confirm:{index}")

    def test_direct_relation_augments_composition_without_touching_similarity(self):
        self._confirm_grid()
        before = self.links.similarity_settings()
        with self.db.connect() as db:
            similarity_count = db.execute(
                "SELECT COUNT(*) FROM memory_claims WHERE scope=?",
                (SIMILARITY_RELATION_SCOPE,)).fetchone()[0]
        relation = self.links.record_language_relation(
            "surface_equivalence", surfaces=["alpha", "xa"], polarity="positive",
            context={}, context_keys=[], provider=self.provider, source_ref="composition:relation",
            basis="Explicit fixture declaration.", user_utterance="alpha und xa sind gleich.",
        )
        result = self.links.composition_lookup("do alpha q", {}, self.provider)
        self.assertEqual("hit", result["status"])
        self.assertEqual("A", result["hit"]["plan"]["actions"][0]["entity_id"])
        self.assertIn(relation["relation_id"], result["hit"]["language_relation_ids"])
        self.assertEqual((0, 0, 0), (result["model_requests"], result["prompt_tokens"],
                                    result["completion_tokens"]))
        self.assertEqual(before, self.links.similarity_settings())
        with self.db.connect() as db:
            self.assertEqual(similarity_count, db.execute(
                "SELECT COUNT(*) FROM memory_claims WHERE scope=?",
                (SIMILARITY_RELATION_SCOPE,)).fetchone()[0])

    def test_resource_alias_can_supply_one_component_but_not_provider_or_action_authority(self):
        self._confirm_grid(linked=True)
        alias = self.links.record_language_relation(
            "resource_alias", source_surface="xa", new_surface="alpha",
            context={}, context_keys=[], provider=self.provider,
            source_ref="composition:alias", basis="Explicit fixture alias.",
            user_utterance="xa heißt alpha.",
        )
        self.assertEqual("stored", alias["status"])
        self.assertEqual("A", alias["resource_identity"])
        result = self.links.composition_lookup("do alpha q", {}, self.provider)
        self.assertEqual("hit", result["status"])
        self.assertEqual("A", result["hit"]["plan"]["actions"][0]["entity_id"])
        self.assertIn(alias["relation_id"], result["hit"]["language_relation_ids"])
        other_provider = {"provider": "fixture", "endpoint": "memory://other"}
        self.assertEqual(
            "fallback", self.links.composition_lookup("do alpha q", {}, other_provider)["status"])
        for index, claim_id in enumerate(alias["source_claim_ids"]):
            if self.links.experience(claim_id)["lifecycle"] == "active":
                self.links.decide(
                    claim_id, confirmed=False,
                    source_ref=f"composition:alias:invalidate:{index}")
        self.assertEqual(
            "fallback", self.links.composition_lookup("do alpha q", {}, self.provider)["status"])

    def test_relation_is_one_hop_and_correction_removes_dependent_lookup(self):
        self._confirm_grid()
        first = self.links.record_language_relation(
            "surface_equivalence", surfaces=["alpha", "xa"], polarity="positive",
            context={}, context_keys=[], provider=self.provider, source_ref="hop:first",
            basis="Explicit fixture declaration.", user_utterance="alpha und xa sind gleich.",
        )
        self.links.record_language_relation(
            "surface_equivalence", surfaces=["beta", "alpha"], polarity="positive",
            context={}, context_keys=[], provider=self.provider, source_ref="hop:second",
            basis="Explicit fixture declaration.", user_utterance="beta und alpha sind gleich.",
        )
        self.assertEqual("fallback", self.links.composition_lookup("do beta q", {}, self.provider)["status"])
        correction = self.links.correct_language_relation(
            first["relation_id"], source_ref="hop:correct", basis="Explicit correction.")
        self.assertEqual("fallback", self.links.composition_lookup("do alpha q", {}, self.provider)["status"])
        self.links.correct_language_relation(
            correction["relation_id"], source_ref="hop:undo", basis="Undo correction.", undo=True)
        self.assertEqual("hit", self.links.composition_lookup("do alpha q", {}, self.provider)["status"])

    def test_brainwatch_exposes_relations_evidence_versions_and_dependencies(self):
        self.confirmed_action("Licht im Flur ausschalten")
        self.links.record_language_relation(
            "resource_alias", source_surface="Licht im Flur", new_surface="Flurlicht",
            context=self.context, context_keys=[], provider=self.provider,
            source_ref="brainwatch:alias", basis="Explicit alias.",
            user_utterance="Licht im Flur heißt Flurlicht.",
        )
        inspector = SemanticInspector(self.path)
        data = inspector.composition(self.links.composition_settings())
        self.assertEqual(LANGUAGE_RELATION_SCOPE, data["language_relation_scope"])
        relation = data["language_relations"][0]
        self.assertEqual("resource_alias", relation["relation_kind"])
        self.assertTrue(relation["evidence"])
        self.assertTrue(relation["relations"])
        self.assertEqual(1, inspector.summary()["stock"]["language_relations_active"])


if __name__ == "__main__":
    unittest.main()
