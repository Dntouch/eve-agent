import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_native_semantic_learning as fixtures
from test_learned_execution import ReplayHome
from eve_agent.shadow_learning import ProductiveLearningPipeline


class ConversationSemanticsTest(unittest.TestCase):
    setUp = fixtures.NativeSemanticLearningTest.setUp
    call = staticmethod(fixtures.NativeSemanticLearningTest.call)
    results = staticmethod(fixtures.NativeSemanticLearningTest.results)
    action = fixtures.NativeSemanticLearningTest.action
    feedback = fixtures.NativeSemanticLearningTest.feedback

    def completed_turn(self, text="Hey EVE, bitte do xa p."):
        self.home = ReplayHome()
        self.agent.home_assistant = self.home
        anchor = self.action("do xa p")["experience"]
        self.feedback("Das war richtig.")
        responses = iter([
            self.call("eve__load_capabilities", {"capabilities": ["home_assistant"]}),
            self.call("home_assistant__http_request", {"method": "POST", "path": "/api/services/light/p", "body": {"entity_id": "light.A"}}),
            self.call("home_assistant__http_request", {"method": "GET", "path": "/api/states/light.A"}),
            {"content": "Ausgeführt.", "tool_calls": []},
        ])
        self.llm.request_tool_turn.side_effect = lambda *a, **k: next(responses)
        with patch("eve_agent.learned_execution.try_replay", return_value=None):
            self.agent.respond(text)
        with self.db.connect() as c:
            turn = c.execute("SELECT id FROM turns ORDER BY created_at DESC LIMIT 1").fetchone()[0]
        return turn, anchor

    @staticmethod
    def proposal(context):
        semantic = context["semantic_learning"]
        group = semantic["action_candidates"][0]
        ref, observation = next((r, o) for r, o in semantic["observations"].items()
                                if o["parameters"].get("path") == "/api/states/light.A")
        return {"decision_type": "no_persist", "memory_worthy": False,
                "reason_code": "one_time_command_with_reusable_formulation", "uncertainty": 0.0,
                "clarification_recommended": False, "claim": None, "evidence": [],
                "matched_claim_ids": [], "relations": [],
                "semantic_learning_reason": "A new explicit formulation of the published action, with a verified goal.",
                "semantic_formulation": {"call_references": list(semantic["executions"]),
                    "assessment": {"status": "resolved", "context_keys": [], "user_grounding": "explicit",
                        "utterance_quote": semantic["current_formulation"], "basis": "Same explicit target and action.",
                        "uncertainties": [], "action_link": {"kind": "existing",
                            "representation_id": group["representation_id"],
                            "anchor_claim_id": group["examples"][0]["claim_id"], "basis": "Same meaning as the published example."}},
                    "outcome": "success", "outcome_basis": "Readback confirms the requested result.",
                    "evidence": [{"call_reference": ref, "pointer": "/response/body/state",
                                  "value": observation["result"]["response"]["body"]["state"]}]}}

    def pipeline(self, mutate=None):
        def analyze(contexts):
            items = []
            for context in contexts:
                proposal = self.proposal(context)
                if mutate:
                    mutate(proposal, context)
                items.append({"turn_id": context["turn_id"], "proposal": proposal})
            return {"turns": items}
        return ProductiveLearningPipeline(self.db,
            SimpleNamespace(model="semantic-learning-fixture", analyze_conversation_learning=analyze),
            semantic_links=self.agent.semantic_links)

    def test_new_formulation_reuses_meaning_and_executes_without_model(self):
        turn, anchor = self.completed_turn()
        pipeline = self.pipeline()
        pipeline.accept_turn(turn)
        calls_before = len(self.home.calls)
        result = pipeline.process_batch([turn])[0]
        self.assertEqual("applied", result["application_status"], result)
        self.assertEqual(calls_before, len(self.home.calls), "Deferred learning must never execute devices")
        learned = result["semantic_learning"]
        self.assertEqual("new_formulation", learned["kind"])
        self.assertTrue(learned["direct_execution"])
        self.assertEqual(anchor["action_representation_id"], learned["action_id"])
        experience = self.agent.semantic_links.experience(learned["claim_id"])
        self.assertEqual("Hey EVE, bitte do xa p.", experience["utterance"])
        with self.db.connect() as c:
            self.assertEqual(1, c.execute("SELECT COUNT(*) FROM memory_claims WHERE scope='semantic_actions'").fetchone()[0])
        page = pipeline.learning_jobs("evidenced")
        self.assertEqual(learned, page["items"][0]["semantic_learning"])
        self.assertEqual(learned["claim_id"], page["items"][0]["claims"][0]["id"])
        with self.db.connect() as c:
            message = c.execute('SELECT assistant_message_id FROM turns WHERE id=?', (turn,)).fetchone()[0]
        self.agent.semantic_links.execution_feedback(self.agent.conversation_id, message, 'correct')
        self.assertEqual('confirmed', self.agent.semantic_links.experience(learned['claim_id'])['confirmation'])
        self.llm.request_tool_turn.reset_mock()
        self.llm.request_tool_turn.side_effect = AssertionError("No model call for the learned formulation")
        self.agent.respond("Hey EVE, bitte do xa p.")
        self.llm.request_tool_turn.assert_not_called()
        self.assertEqual("exact", self.agent._turn_state_details["semantic_reuse"])

    def test_repeated_processing_does_not_duplicate_formulation_or_root(self):
        turn, _ = self.completed_turn()
        pipeline = self.pipeline()
        pipeline.accept_turn(turn)
        first = pipeline.process_batch([turn])[0]
        with self.db.connect() as c:
            before = c.execute("SELECT COUNT(*) FROM memory_claims WHERE scope='semantic_links'").fetchone()[0]
            c.execute("UPDATE memory_learning_jobs SET status='pending',decision_id=NULL WHERE turn_id=?", (turn,))
        second = pipeline.process_batch([turn])[0]
        self.assertEqual(first["semantic_learning"]["claim_id"], second["semantic_learning"]["claim_id"])
        self.assertEqual("supporting_evidence", second["semantic_learning"]["kind"])
        with self.db.connect() as c:
            self.assertEqual(before, c.execute("SELECT COUNT(*) FROM memory_claims WHERE scope='semantic_links'").fetchone()[0])

    def test_online_learning_is_reported_without_a_second_experience(self):
        self.home = ReplayHome()
        self.agent.home_assistant = self.home
        online = self.action("do xa p")
        with self.db.connect() as c:
            turn = c.execute("SELECT id FROM turns ORDER BY created_at DESC LIMIT 1").fetchone()[0]
        def already_recorded(raw, context):
            raw['semantic_formulation'] = None
            raw['semantic_learning_reason'] = 'This exact execution was already recorded online.'
        pipeline = self.pipeline(already_recorded)
        pipeline.accept_turn(turn)
        result = pipeline.process_batch([turn])[0]
        self.assertEqual('supporting_evidence', result['semantic_learning']['kind'])
        self.assertEqual(online['claim_id'], result['semantic_learning']['claim_id'])
        with self.db.connect() as c:
            self.assertEqual(1, c.execute("SELECT COUNT(*) FROM memory_claims WHERE scope='semantic_links'").fetchone()[0])

    def test_semantic_write_and_general_claim_rollback_together(self):
        turn, _ = self.completed_turn()
        def with_fact(raw, context):
            raw.update(decision_type='create_candidate', memory_worthy=True, authority='model_inference',
                claim={'kind': 'opaque_fact', 'scope': 'user:self', 'canonical_key': 'v2:semantic-atomic-test',
                       'display_text': 'An inferred candidate', 'payload': {'epistemic_kind': 'inferred_procedure'}},
                evidence=[{'source_type': 'user_message', 'source_id': context['user_message']['id']}])
        pipeline = self.pipeline(with_fact)
        pipeline.accept_turn(turn)
        original = pipeline.conversation_semantics.persist
        def fail_after_write(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('simulated failure after semantic write')
        with self.db.connect() as c:
            before = c.execute('SELECT COUNT(*) FROM memory_claims').fetchone()[0]
        with patch.object(pipeline.conversation_semantics, 'persist', side_effect=fail_after_write):
            result = pipeline.process_batch([turn])[0]
        self.assertEqual('failed', result['application_status'], result)
        with self.db.connect() as c:
            self.assertEqual(before, c.execute('SELECT COUNT(*) FROM memory_claims').fetchone()[0])
            self.assertEqual(0, c.execute("SELECT COUNT(*) FROM memory_claims WHERE canonical_key='v2:semantic-atomic-test'").fetchone()[0])

    def test_incorrect_value_foreign_reference_or_goal_transport_status_is_rejected(self):
        turn, _ = self.completed_turn()
        for mutate in [lambda p, c: p["semantic_formulation"]["evidence"][0].update(value=True),
                       lambda p, c: p["semantic_formulation"]["call_references"].append("another-turn"),
                       lambda p, c: p["semantic_formulation"]["evidence"][0].update(pointer="/response/status", value=200),
                       lambda p, c: p["semantic_formulation"]["assessment"]["action_link"].update(anchor_claim_id="unpublished")]:
            pipeline = self.pipeline(mutate)
            snapshot = pipeline._snapshot(turn)
            context = pipeline._model_context(snapshot, [])
            raw = self.proposal(context)
            mutate(raw, context)
            result = pipeline._validate_proposal(raw, snapshot, [])
            self.assertEqual("undetermined", result["decision_type"], result)

    def test_context_dependent_formulation_is_not_released_for_direct_execution(self):
        turn, _ = self.completed_turn("Mach das bitte wieder so.")
        def contextual(proposal, context):
            assessment = proposal["semantic_formulation"]["assessment"]
            assessment.update(user_grounding="contextual", context_keys=["focus"],
                              action_link={"kind": "none", "basis": "Meaning depends on current focus."})
        pipeline = self.pipeline(contextual)
        pipeline.accept_turn(turn)
        result = pipeline.process_batch([turn])[0]
        self.assertEqual("applied", result["application_status"], result)
        self.assertTrue(result["semantic_learning"]["context_dependent"])
        self.assertFalse(result["semantic_learning"]["direct_execution"])

    def test_new_meaning_creates_an_action_and_formulation(self):
        turn, _ = self.completed_turn()
        def new_meaning(raw, context):
            raw['semantic_formulation']['assessment']['action_link'] = {
                'kind': 'new', 'meaning': 'An explicitly assessed new fixture meaning',
                'basis': 'Model-declared new meaning, not an inferred equivalence.'}
        pipeline = self.pipeline(new_meaning)
        pipeline.accept_turn(turn)
        result = pipeline.process_batch([turn])[0]
        self.assertEqual('new_action', result['semantic_learning']['kind'])
        self.assertTrue(result['semantic_learning']['direct_execution'])
        with self.db.connect() as c:
            self.assertEqual(2, c.execute("SELECT COUNT(*) FROM memory_claims WHERE scope='semantic_actions'").fetchone()[0])

    def test_explicit_nonreusable_decision_stays_visible(self):
        turn, _ = self.completed_turn()
        def not_reusable(raw, context):
            raw['semantic_formulation'] = None
            raw['semantic_learning_reason'] = 'Meaning is not sufficiently established.'
        pipeline = self.pipeline(not_reusable)
        pipeline.accept_turn(turn)
        pipeline.process_batch([turn])
        item = pipeline.learning_jobs('no_persist')['items'][0]
        self.assertEqual('not_reusable', item['semantic_learning']['kind'])
        self.assertEqual('Meaning is not sufficiently established.', item['semantic_learning']['reason'])

    def test_missing_original_provider_identity_is_not_reconstructed(self):
        turn, _ = self.completed_turn()
        with self.db.connect() as c:
            for row in c.execute("SELECT e.id,e.result_json FROM conversation_tool_events e JOIN turns t ON t.assistant_message_id=e.message_id WHERE t.id=?", (turn,)).fetchall():
                data = json.loads(row["result_json"])
                data.pop("provider_identity", None)
                c.execute("UPDATE conversation_tool_events SET result_json=? WHERE id=?", (json.dumps(data), row["id"]))
        pipeline = self.pipeline()
        context = pipeline._model_context(pipeline._snapshot(turn), [])
        self.assertFalse(context["semantic_learning"]["available"])

    def test_omitted_semantic_decision_is_not_silently_no_persist(self):
        turn, _ = self.completed_turn()
        pipeline = self.pipeline()
        snapshot = pipeline._snapshot(turn)
        raw = self.proposal(pipeline._model_context(snapshot, []))
        raw.pop("semantic_formulation")
        self.assertEqual("undetermined", pipeline._validate_proposal(raw, snapshot, [])["decision_type"])

    def test_semantic_actions_are_not_general_fact_append_targets(self):
        turn, _ = self.completed_turn()
        pipeline = self.pipeline()
        snapshot = pipeline._snapshot(turn)
        candidates = pipeline._claim_candidates(pipeline._candidate_context(snapshot))
        self.assertFalse(any(c['scope'].startswith('semantic_') for c in candidates))
        self.assertTrue(pipeline._model_context(snapshot, candidates)['semantic_learning']['action_candidates'])


if __name__ == "__main__":
    unittest.main()
