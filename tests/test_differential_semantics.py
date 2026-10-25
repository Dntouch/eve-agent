import inspect
import json
import tempfile
import unittest
from pathlib import Path
from eve_agent.differential_semantics import DifferentialSemantics, flatten_plan
from eve_agent.semantic_links import SemanticLinks
from eve_agent.storage import EveDatabase, SCHEMA_VERSION


class DifferentialSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "eve.db"
        self.db = EveDatabase(self.path)
        self.provider = {"provider": "synthetic", "endpoint": "memory://provider"}
        self.links = SemanticLinks(self.db, {}, {"enabled": True, "mode": "active"})

    @staticmethod
    def plan(entity, service, parameters=None):
        return {"effect": "write", "context_required": False, "clarification": None,
                "actions": [{"type": "call_service", "entity_id": entity,
                             "service": service, "parameters": parameters or {}}]}

    def confirm(self, utterance, entity, service, root, *, context=None, provider=None,
                validated=True, result="success"):
        claim = self.links.learn(
            utterance, context or {}, provider or self.provider, self.plan(entity, service),
            {"status": result}, source_ref=root, provider_validated=validated,
        )
        self.assertIsNotNone(claim)
        self.links.decide(claim, confirmed=True, source_ref="confirm:" + root)
        return claim

    def train_grid(self):
        # xa/q is intentionally absent.  Every released variable has two
        # independent supports, a one-field contrast and nuisance variation.
        rows = [
            ("do xa p", "A", "p"), ("do xa r", "A", "r"),
            ("do xb p", "B", "p"), ("do xb q", "B", "q"),
            ("do xb r", "B", "r"), ("do xc p", "C", "p"),
            ("do xc q", "C", "q"),
        ]
        return [self.confirm(text, entity, service, f"root:{index}")
                for index, (text, entity, service) in enumerate(rows)]

    def test_active_unknown_combination_is_unique_valid_json_and_model_free(self):
        self.train_grid()
        result = self.links.composition_lookup("do xa q", {}, self.provider)
        self.assertEqual("hit", result["status"])
        self.assertEqual(self.plan("A", "q")["actions"], result["hit"]["plan"]["actions"])
        self.assertEqual((0, 0, 0), (result["model_requests"], result["prompt_tokens"],
                                    result["completion_tokens"]))
        json.loads(json.dumps(result, ensure_ascii=False))
        self.assertTrue(result["execution_authorized"])
        self.assertFalse(result["truncated"])

    def test_shadow_returns_diagnostics_without_authorizing_execution(self):
        self.train_grid(); self.links.configure_composition({"mode": "shadow"})
        result = self.links.composition_lookup("do xa q", {}, self.provider)
        self.assertEqual("shadow_hit", result["status"])
        self.assertIsNone(result["hit"])
        self.assertIsNotNone(result["shadow_candidate"])
        self.assertFalse(result["execution_authorized"])

    def test_unconfirmed_failed_and_unvalidated_experiences_do_not_release(self):
        claim = self.links.learn("do xa p", {}, self.provider, self.plan("A", "p"),
                                 {"status": "success"}, source_ref="root:one",
                                 provider_validated=True)
        self.assertIsNotNone(claim)
        self.confirm("do xa r", "A", "r", "root:two", validated=False)
        self.confirm("do xb p", "B", "p", "root:three", result="outcome_uncertain")
        result = self.links.composition_lookup("do xa q", {}, self.provider)
        self.assertEqual("fallback", result["status"])
        with self.db.connect() as db:
            states = dict(db.execute("SELECT reason,COUNT(*) FROM semantic_differential_experiences GROUP BY reason"))
        self.assertGreaterEqual(states.get("semantic_experience_unconfirmed", 0), 1)
        self.assertGreaterEqual(states.get("technical_result_not_confirmed", 0), 2)

    def test_repeated_and_unknown_roots_never_count_as_independent_support(self):
        self.confirm("do xa p", "A", "p", "same-root")
        second = self.confirm("do xa r", "A", "r", "same-root")
        self.confirm("do xb p", "B", "p", "root:b1")
        self.confirm("do xb r", "B", "r", "root:b2")
        with self.db.connect() as db:
            row = db.execute("SELECT payload_json FROM memory_claims WHERE id=?", (second,)).fetchone()
            payload = json.loads(row[0]); payload.pop("differential_provenance_root")
            db.execute("UPDATE memory_claims SET payload_json=? WHERE id=?",
                       (json.dumps(payload, ensure_ascii=False), second))
        self.links.differential.refresh_claim(second)
        result = self.links.composition_lookup("do xa q", {}, self.provider)
        self.assertEqual("fallback", result["status"])
        with self.db.connect() as db:
            maximum = db.execute("""SELECT MAX(support_roots) FROM semantic_differential_hypotheses
                WHERE feature='tok:xa' AND value_json='\"A\"'""").fetchone()[0]
        self.assertIn(maximum, (None, 1))

    def test_context_provider_service_entity_and_parameter_identity_are_structural(self):
        left, left_shape = flatten_plan(self.plan("A", "p", {"level": 1}))
        service, _ = flatten_plan(self.plan("A", "q", {"level": 1}))
        entity, _ = flatten_plan(self.plan("B", "p", {"level": 1}))
        parameter, parameter_shape = flatten_plan(self.plan("A", "p", {"level": 2}))
        self.assertEqual(left_shape, parameter_shape)
        self.assertNotEqual(left["/actions/0/service"], service["/actions/0/service"])
        self.assertNotEqual(left["/actions/0/entity_id"], entity["/actions/0/entity_id"])
        self.assertNotEqual(left["/actions/0/parameters/level"], parameter["/actions/0/parameters/level"])
        self.train_grid()
        self.assertEqual("fallback", self.links.composition_lookup(
            "do xa q", {"scope": "different"}, {**self.provider, "endpoint": "memory://other"})["status"])

    def test_unknown_surface_and_incomplete_coverage_fall_back(self):
        self.train_grid()
        for text in ("do xa q extra", "unknown xa q", "do xa"):
            result = self.links.composition_lookup(text, {}, self.provider)
            self.assertEqual("fallback", result["status"])
            self.assertTrue(result["missing_evidence"] or result["reason"])

    def test_word_order_and_formal_symbols_are_not_interpreted(self):
        self.train_grid()
        # Order changes are accepted only because each observed unit remains
        # formally covered; no grammar or German-specific role is consulted.
        reordered = self.links.composition_lookup("q do xa", {}, self.provider)
        self.assertEqual("hit", reordered["status"])
        symbols = SemanticLinks(EveDatabase(Path(self.tmp.name) / "symbols.db"), {}, {"mode": "active"})
        old = self.links; self.links = symbols
        try:
            rows = [("◇ α !", "A", "p"), ("◇ α ?", "A", "r"),
                    ("◇ β !", "B", "p"), ("◇ β +", "B", "q"),
                    ("◇ β ?", "B", "r"), ("◇ γ !", "C", "p"), ("◇ γ +", "C", "q")]
            for index, row in enumerate(rows): self.confirm(*row, f"symbol:{index}")
            self.assertEqual("hit", symbols.composition_lookup("◇ α +", {}, self.provider)["status"])
        finally:
            self.links = old

    def test_correction_invalidates_only_dependent_hypotheses_and_versions_remain(self):
        claims = self.train_grid()
        self.assertEqual("hit", self.links.composition_lookup("do xa q", {}, self.provider)["status"])
        self.links.decide(claims[-1], confirmed=False, source_ref="correction:cq")
        self.assertEqual("fallback", self.links.composition_lookup("do xa q", {}, self.provider)["status"])
        with self.db.connect() as db:
            versions = db.execute("SELECT COUNT(*) FROM semantic_differential_hypothesis_versions").fetchone()[0]
            released_other = db.execute("""SELECT COUNT(*) FROM semantic_differential_hypotheses
                WHERE status='released' AND feature='tok:xa'""").fetchone()[0]
        self.assertGreater(versions, 0)
        self.assertGreater(released_other, 0)

    def test_restart_persists_hypotheses_evaluations_and_active_mode(self):
        self.train_grid(); first = self.links.composition_lookup("do xa q", {}, self.provider)
        restarted = SemanticLinks(EveDatabase(self.path), {}, {"enabled": True, "mode": "active"})
        second = restarted.composition_lookup("do xa q", {}, self.provider)
        self.assertEqual(first["hit"]["plan"], second["hit"]["plan"])
        with self.db.connect() as db:
            self.assertEqual(SCHEMA_VERSION, db.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual(2, db.execute("SELECT COUNT(*) FROM semantic_differential_evaluations").fetchone()[0])

    def test_candidate_bounds_fail_closed(self):
        bounded = SemanticLinks(EveDatabase(Path(self.tmp.name) / "bounded.db"), {}, {
            "mode": "active", "max_lookup_candidates": 2,
        })
        old = self.links; self.links = bounded
        try:
            for index, row in enumerate([("do xa p", "A", "p"), ("do xa r", "A", "r"),
                                         ("do xb p", "B", "p")]):
                self.confirm(*row, f"bounded:{index}")
            result = bounded.composition_lookup("do xa q", {}, self.provider)
            self.assertEqual("fallback", result["status"])
            self.assertTrue(result["truncated"])
            self.assertEqual("candidate_space_truncated", result["reason"])
        finally:
            self.links = old

    def test_productive_algorithm_contains_no_language_specific_semantic_tables(self):
        source = inspect.getsource(DifferentialSemantics)
        for forbidden in ("synonym", "negation", "entity-name", "turn_off\":", "licht", "flur"):
            self.assertNotIn(forbidden, source.casefold())

if __name__ == "__main__":
    unittest.main()
