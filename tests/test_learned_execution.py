import copy
import json
import unittest

import test_native_semantic_learning as fixtures
from eve_agent.learned_execution import replay_recipe, select_replay
from eve_agent.transport_access import transport_access


class ReplayHome(fixtures.SyntheticHome):
    ignore_writes = False
    timeout_write = False
    missing_service = False

    def execute_native_operation(self, operation, parameters):
        if parameters["path"] == "/api/services":
            self.calls.append((operation, copy.deepcopy(parameters)))
            return {"status": "completed", "response": {"body": [
                {"domain": "light", "services": {} if self.missing_service else {"p": {}, "q": {}, "r": {}}}]}}
        if parameters["method"] == "POST" and self.timeout_write:
            self.calls.append((operation, copy.deepcopy(parameters)))
            raise RuntimeError("timeout after dispatch")
        if parameters["method"] == "POST" and self.ignore_writes:
            self.calls.append((operation, copy.deepcopy(parameters)))
            return {"status": "completed", "response": {"status": 200, "body": []}}
        return super().execute_native_operation(operation, parameters)


class LearnedExecutionTest(unittest.TestCase):
    setUp = fixtures.NativeSemanticLearningTest.setUp
    call = staticmethod(fixtures.NativeSemanticLearningTest.call)
    results = staticmethod(fixtures.NativeSemanticLearningTest.results)
    action = fixtures.NativeSemanticLearningTest.action
    feedback = fixtures.NativeSemanticLearningTest.feedback

    def prepare(self):
        self.home = ReplayHome()
        self.agent.home_assistant = self.home

    def forbid_model(self):
        self.llm.request_tool_turn.reset_mock()
        self.llm.request_tool_turn.side_effect = AssertionError("Replay must not call the LLM")
        self.home.calls.clear()

    def test_exact_verified_repeat_skips_model_and_persists_provenance(self):
        self.prepare()
        learned = self.action("do xa p")
        self.forbid_model()
        answer = self.agent.respond("do xa p")
        self.assertEqual("Erledigt.", answer)
        self.llm.request_tool_turn.assert_not_called()
        self.assertEqual(["GET", "GET", "POST", "GET"], [args["method"] for _, args in self.home.calls])
        self.assertEqual("exact", self.agent._turn_state_details["semantic_reuse"])
        with self.db.connect() as c:
            turn = c.execute("SELECT id,knowledge_flow_json FROM turns ORDER BY created_at DESC LIMIT 1").fetchone()
            self.assertIn('"decision_origin": "semantic_replay"', turn["knowledge_flow_json"])
            proof = c.execute("SELECT source_turn_id FROM memory_evidence WHERE claim_id=? AND evidence_type='reuse_result'",
                              (learned["claim_id"],)).fetchone()
            self.assertEqual(turn["id"], proof["source_turn_id"])

    def test_legacy_experience_requires_actual_verified_state_evidence(self):
        self.prepare()
        hit = self.action("do xa p")["experience"]
        hit["plan"].pop("replay_observations")
        self.assertIsNone(replay_recipe(self.agent.semantic_links, hit))
        result = {"status": "success", "action_results": [{"entity_id": "light.A", "service": "light.p",
                  "status": "success", "verification": {"final_decision": "target_confirmed",
                  "observations": [{"state": "p", "target_match": True, "stale": False}]}}]}
        with self.db.connect() as c:
            self.agent.semantic_links._evidence(c, hit["id"], "provider_result", result, "legacy-proof")
        prepared = replay_recipe(self.agent.semantic_links, hit)
        self.assertEqual("p", prepared[1][0]["value"])

    def test_released_dynamic_semantics_executes_without_model(self):
        self.prepare()
        self.action("do xa p")
        self.feedback("Das war richtig.")
        self.forbid_model()
        self.agent.respond("p xa do")
        self.llm.request_tool_turn.assert_not_called()
        self.assertEqual("similarity", self.agent._turn_state_details["semantic_reuse"])
        self.assertEqual("light.A", next(args["body"]["entity_id"] for _, args in self.home.calls if args["method"] == "POST"))

    def test_wrong_dynamic_match_blocks_variant_without_invalidating_original(self):
        self.prepare()
        learned = self.action("do xa p")
        self.feedback("Das war richtig.")
        self.forbid_model()
        self.agent.respond("p xa do")
        with self.db.connect() as c:
            message = c.execute("SELECT id,conversation_id FROM messages WHERE role='assistant' ORDER BY created_at DESC LIMIT 1").fetchone()
        self.agent.semantic_links.execution_feedback(message["conversation_id"], message["id"], "incorrect")
        source = self.agent.semantic_links.experience(learned["claim_id"])
        self.assertEqual("valid", source["validity"])
        context = self.agent._native_tool_runtime.semantic_session.context
        self.assertIsNone(select_replay(self.agent.semantic_links, "p xa do", context, self.home.semantic_provider_identity()))
        self.assertIsNotNone(select_replay(self.agent.semantic_links, "do xa p", context, self.home.semantic_provider_identity()))

    def test_shadow_similarity_does_not_execute_directly(self):
        self.prepare()
        self.action("do xa p")
        self.feedback("Das war richtig.")
        self.agent.semantic_links.configure_similarity({"enabled": True, "mode": "shadow"})
        self.home.calls.clear()
        self.llm.request_tool_turn.side_effect = lambda *a, **k: {"content": "Modellantwort.", "tool_calls": []}
        self.agent.respond("p xa do")
        self.assertTrue(self.llm.request_tool_turn.called)
        self.assertFalse(any(args["method"] == "POST" for _, args in self.home.calls))

    def test_released_composition_executes_new_combination_without_model(self):
        self.prepare()
        for text, entity, service in [("do xa p", "light.A", "p"), ("do xa r", "light.A", "r"),
                                      ("do xb p", "light.B", "p"), ("do xb q", "light.B", "q"),
                                      ("do xb r", "light.B", "r"), ("do xc p", "light.C", "p"),
                                      ("do xc q", "light.C", "q")]:
            self.action(text, entity, service)
            self.feedback("Das war richtig.")
        self.forbid_model()
        self.agent.respond("do xa q")
        self.llm.request_tool_turn.assert_not_called()
        self.assertEqual("composition", self.agent._turn_state_details["semantic_reuse"])
        write = next(args for _, args in self.home.calls if args["method"] == "POST")
        self.assertEqual("/api/services/light/q", write["path"])
        self.assertEqual({"entity_id": "light.A"}, write["body"])
        claim = self.agent.semantic_links.experience(self.agent._turn_state_details["semantic_link_id"])
        self.assertEqual("", claim["differential_provenance_root"], "Composition must not manufacture independent training roots")
        self.assertEqual("differential_composition", claim["interpretation_source"])
        with self.db.connect() as c:
            evidence_types = {r[0] for r in c.execute('SELECT evidence_type FROM memory_evidence WHERE claim_id=?', (claim['id'],))}
        self.assertIn('differential_interpretation', evidence_types)
        self.assertNotIn('llm_interpretation', evidence_types)

    def test_uncertain_write_never_calls_model_or_retries(self):
        self.prepare()
        self.action("do xa p")
        self.home.timeout_write = True
        self.forbid_model()
        self.agent.respond("do xa p")
        self.llm.request_tool_turn.assert_not_called()
        self.assertEqual(1, sum(args["method"] == "POST" for _, args in self.home.calls))
        self.assertEqual("operational_unresolved", self.agent._turn_state)
        self.assertTrue(self.agent._turn_state_details["write_retry_forbidden"])

    def test_transport_acceptance_without_goal_is_not_success(self):
        self.prepare()
        self.action("do xa p")
        self.home.states["light.A"] = "r"
        self.home.ignore_writes = True
        self.forbid_model()
        self.agent.respond("do xa p")
        self.assertEqual("operational_unresolved", self.agent._turn_state)
        self.assertEqual(1, sum(args["method"] == "POST" for _, args in self.home.calls))
        self.llm.request_tool_turn.assert_not_called()

    def test_missing_service_falls_back_before_writing(self):
        self.prepare()
        self.action("do xa p")
        self.home.missing_service = True
        self.home.calls.clear()
        self.llm.request_tool_turn.side_effect = lambda *a, **k: {"content": "Dienst fehlt.", "tool_calls": []}
        self.agent.respond("do xa p")
        self.assertTrue(self.llm.request_tool_turn.called)
        self.assertFalse(any(args["method"] == "POST" for _, args in self.home.calls))

    def test_public_transport_cannot_replay_private_device_actions(self):
        self.prepare()
        self.action("do xa p")
        self.home.calls.clear()
        self.llm.request_tool_turn.side_effect = lambda *a, **k: {"content": "Nicht freigegeben.", "tool_calls": []}
        with transport_access({}, public=True):
            self.agent.respond("do xa p")
        self.assertEqual([], self.home.calls)

    def test_unconfirmed_contextual_or_invalid_experience_is_not_replayed(self):
        self.prepare()
        learned = self.action("do xa p")
        context = self.agent._native_tool_runtime.semantic_session.context
        with self.db.connect() as c:
            original = json.loads(c.execute("SELECT payload_json FROM memory_claims WHERE id=?", (learned["claim_id"],)).fetchone()[0])
            for updates in [{"confirmation": "unconfirmed"}, {"validity": "invalid"}, {"context": {"focus": ["other"]}}]:
                c.execute("UPDATE memory_claims SET payload_json=? WHERE id=?", (json.dumps({**original, **updates}), learned["claim_id"]))
                c.commit()
                self.assertIsNone(select_replay(self.agent.semantic_links, "do xa p", context, self.home.semantic_provider_identity()))


if __name__ == "__main__":
    unittest.main()
