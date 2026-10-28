import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

import test_native_semantic_learning as fixtures
from test_learned_execution import ReplayHome
from eve_agent.shadow_learning import ProductiveLearningPipeline


class ConversationSemanticsTest(unittest.TestCase):
    setUp = fixtures.NativeSemanticLearningTest.setUp
    call = staticmethod(fixtures.NativeSemanticLearningTest.call)
    results = staticmethod(fixtures.NativeSemanticLearningTest.results)
    action = fixtures.NativeSemanticLearningTest.action
    feedback = fixtures.NativeSemanticLearningTest.feedback

    def test_general_rejection_does_not_discard_a_valid_formulation(self):
        turn, _ = self.completed_turn()
        def invalid_fact(raw, context):
            raw.update(decision_type='create_candidate', memory_worthy=True,
                claim={'kind': 'provider_binding', 'scope': 'user:self', 'canonical_key': 'bad-binding',
                       'display_text': 'Unvollständige Gerätebindung', 'payload': {}},
                evidence=[{'source_type': 'user_message', 'source_id': context['user_message']['id']}])
        pipeline = self.pipeline(invalid_fact); pipeline.accept_turn(turn)
        before = len(self.home.calls)
        result = pipeline.process_batch([turn])[0]
        self.assertEqual('failed', result['general_learning']['status'])
        self.assertEqual('new_formulation', result['semantic_learning']['kind'])
        self.assertTrue(result['semantic_learning']['direct_execution'])
        self.assertEqual(before, len(self.home.calls))
        self.assertEqual(result['semantic_learning'], pipeline.learning_jobs('failed')['items'][0]['semantic_learning'])
        pipeline.retry_turn(turn)
        second = pipeline.process_batch([turn])[0]
        self.assertEqual(result['semantic_learning']['claim_id'], second['semantic_learning']['claim_id'])

    def test_legacy_parameter_storage_matches_only_the_same_wire_request(self):
        from copy import deepcopy
        from eve_agent.semantic_links import action_identity
        old = {'effect':'write','actions':[{'type':'call_service','entity_id':'light.a',
               'service':'light.turn_on','data':{'brightness':42}}]}
        current = deepcopy(old); current['actions'][0]['parameters'] = current['actions'][0].pop('data')
        self.assertEqual(action_identity(old), action_identity(current))
        for key,value in [('parameters',{'brightness':43}),('service','light.turn_off'),
                          ('entity_id','light.b'),('extra',True)]:
            changed=deepcopy(current); changed['actions'][0][key]=value
            self.assertNotEqual(action_identity(old), action_identity(changed))
        conflict=deepcopy(current); conflict['actions'][0]['data']={'brightness':43}
        self.assertNotEqual(action_identity(old), action_identity(conflict))
        typed=deepcopy(current); typed['actions'][0]['parameters']={'brightness':True}
        self.assertNotEqual(action_identity(old), action_identity(typed))
        self.assertIn('data',old['actions'][0])

    def test_work_memory_finishes_through_schema_tool_without_schema_in_prompt(self):
        turn, _ = self.completed_turn()
        pipeline = self.pipeline()
        context = pipeline._model_context(pipeline._snapshot(turn), [])
        proposal = self.proposal(context)
        proposal.update(authority=None, temporal_class=None, change_type=None)
        invalid = json.loads(json.dumps(proposal))
        invalid['semantic_formulation']['assessment']['action_link'].pop('anchor_claim_id')
        replies = [self.call('learning__submit', {'turns':[{'turn_id':turn,'proposal':p}]})
                   for p in (invalid,proposal)]
        model = Mock(side_effect=replies)
        pipeline.llm = SimpleNamespace(model='structured-test', request_tool_turn=model, max_tokens=2000)
        before = len(self.home.calls)
        value = pipeline._analyze_context_via_working_memory(context, Mock())
        self.assertEqual(proposal, value['turns'][0]['proposal'])
        self.assertEqual(before, len(self.home.calls))
        self.assertEqual(2, model.call_count)
        for call in model.call_args_list:
            self.assertEqual('required', call.kwargs['tool_choice'])
            self.assertNotIn('Return exactly one JSON object matching this schema', call.args[0][0]['content'])
            self.assertNotIn('"properties":', call.args[0][0]['content'])
            self.assertTrue(any(t['function']['name']=='learning__submit' for t in call.args[1]))
        feedback = next(json.loads(m['content']) for m in model.call_args.args[0] if m['role']=='tool')
        self.assertEqual('schema_validation_failed', feedback['message'])
        self.assertTrue(any("anchor_claim_id" in e.get('message', '') for e in feedback['field_errors']))
        self.assertNotIn('"proposal":', json.dumps(feedback))

    def test_large_history_keeps_exact_execution_references_in_compact_entry(self):
        turn, _ = self.completed_turn()
        pipeline = self.pipeline()
        context = pipeline._model_context(pipeline._snapshot(turn), [])
        context['semantic_learning']['context_at_execution']['history'] = [{'role':'user','content':'x'*20000}]
        entry = pipeline._working_learning_entry(context, 'original')
        compact = entry['inline']['semantic_learning']
        self.assertEqual(context['semantic_learning']['executions'], compact['executions'])
        self.assertEqual(context['semantic_learning']['goal_observation_refs'], compact['goal_observation_refs'])
        self.assertNotIn('context_at_execution', compact)
        self.assertIn('original_pointer', compact)

    def test_published_schema_cannot_claim_success_without_a_goal_reference(self):
        from eve_agent.learning_contract import learning_response_format
        from jsonschema import Draft202012Validator, ValidationError
        turn, _ = self.completed_turn()
        pipeline = self.pipeline(); context = pipeline._model_context(pipeline._snapshot(turn), [])
        context['semantic_learning']['goal_observation_refs'] = []
        raw = self.proposal(context)
        raw.update(authority=None, temporal_class=None, change_type=None)
        schema = learning_response_format(contexts=[context])['json_schema']['schema']
        with self.assertRaises(ValidationError): Draft202012Validator(schema).validate(raw)
        raw['semantic_formulation'].update(outcome='outcome_uncertain', evidence=[])
        Draft202012Validator(schema).validate(raw)

    def test_interrupted_two_branch_learning_resumes_without_finalizing_early(self):
        turn, _ = self.completed_turn()
        pipeline = self.pipeline(); pipeline.accept_turn(turn)
        with patch.object(pipeline.conversation_semantics, 'persist', side_effect=KeyboardInterrupt('restart')):
            with self.assertRaises(KeyboardInterrupt):
                pipeline.process_batch([turn])
        with self.db.connect() as c:
            self.assertEqual('running', c.execute('SELECT status FROM memory_learning_jobs WHERE turn_id=?', (turn,)).fetchone()[0])
            count = c.execute('SELECT count(*) FROM memory_learning_decisions').fetchone()[0]
        pipeline.pending_turns()
        result = pipeline.process_batch([turn])[0]
        self.assertEqual('applied', result['application_status'], result)
        with self.db.connect() as c:
            self.assertEqual(count, c.execute('SELECT count(*) FROM memory_learning_decisions').fetchone()[0])

    def test_broken_membership_is_repaired_on_same_occurrence_without_new_experience(self):
        turn, anchor = self.completed_turn()
        pipeline = self.pipeline(); pipeline.accept_turn(turn)
        first = pipeline.process_batch([turn])[0]['semantic_learning']
        original = self.agent.semantic_links.experience(first['claim_id'])
        with self.db.connect() as c:
            row = c.execute('SELECT payload_json FROM memory_claims WHERE id=?', (first['claim_id'],)).fetchone()
            payload = json.loads(row[0]); payload.update(action_link_status='insufficient_evidence', action_link_reason='reference_not_published')
            payload.pop('action_representation_id')
            c.execute('UPDATE memory_claims SET payload_json=? WHERE id=?', (json.dumps(payload), first['claim_id']))
            c.execute("UPDATE memory_learning_jobs SET status='failed' WHERE turn_id=?", (turn,))
            count = c.execute("SELECT count(*) FROM memory_claims WHERE scope='semantic_links'").fetchone()[0]
        before = len(self.home.calls)
        pipeline.retry_turn(turn)
        learned = pipeline.process_batch([turn])[0]['semantic_learning']
        self.assertEqual('relinked', learned['kind'])
        self.assertEqual(first['claim_id'], learned['claim_id'])
        repaired = self.agent.semantic_links.experience(learned['claim_id'])
        self.assertEqual(original['differential_provenance_root'], repaired['differential_provenance_root'])
        self.assertEqual(anchor['action_representation_id'], repaired['action_representation_id'])
        self.assertNotIn('action_link_reason', repaired)
        self.assertEqual(before, len(self.home.calls))
        with self.db.connect() as c:
            self.assertEqual(count, c.execute("SELECT count(*) FROM memory_claims WHERE scope='semantic_links'").fetchone()[0])

    def test_uncertain_candidate_can_keep_pre_action_observations_without_release(self):
        turn, _ = self.completed_turn()
        # Reorder only the recorded fixture observation, proving it predates dispatch.
        with self.db.connect() as c:
            rows = c.execute('SELECT id,ordinal FROM conversation_tool_events WHERE message_id=(SELECT assistant_message_id FROM turns WHERE id=?) AND tool=\'home_assistant\' ORDER BY ordinal', (turn,)).fetchall()
            c.execute('UPDATE conversation_tool_events SET ordinal=-1 WHERE id=?', (rows[-1]['id'],))
        def uncertain(raw, context):
            raw['semantic_formulation'].update(outcome='outcome_uncertain', outcome_basis='No post-action state evidence.')
            raw['semantic_formulation']['assessment']['action_link'] = {'kind': 'new', 'meaning': 'Fixture candidate', 'basis': 'Model interpretation.'}
        pipeline = self.pipeline(uncertain); pipeline.accept_turn(turn)
        before = len(self.home.calls)
        result = pipeline.process_batch([turn])[0]
        self.assertEqual('applied', result['application_status'], result)
        learned = result['semantic_learning']
        self.assertEqual('semantic_candidate', learned['kind'])
        self.assertEqual('candidate', learned['release'])
        self.assertFalse(learned['direct_execution'])
        self.assertEqual(before, len(self.home.calls))
        claim = self.agent.semantic_links.experience(learned['claim_id'])
        self.assertNotIn('replay_observations', claim['plan'])

    def test_success_needs_post_action_evidence_but_failed_attempts_do_not_poison_recovery(self):
        turn, _ = self.completed_turn()
        with self.db.connect() as c:
            assistant = c.execute('SELECT assistant_message_id FROM turns WHERE id=?', (turn,)).fetchone()[0]
            source = c.execute("SELECT * FROM conversation_tool_events WHERE message_id=? AND tool='home_assistant' ORDER BY ordinal LIMIT 1", (assistant,)).fetchone()
            failed = dict(source); failed.update(id='failed-attempt', ordinal=-1, status='failed',
                result_json=json.dumps({'status':'failed', 'provider_identity':self.home.semantic_provider_identity()}))
            columns=list(failed)
            c.execute('INSERT INTO conversation_tool_events ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')', [failed[k] for k in columns])
        pipeline = self.pipeline(); pipeline.accept_turn(turn)
        result = pipeline.process_batch([turn])[0]
        self.assertEqual('applied', result['application_status'], result)
        self.assertTrue(result['semantic_learning']['direct_execution'])

    def test_shared_contract_rejects_existing_meaning_without_anchor(self):
        turn, _ = self.completed_turn()
        pipeline = self.pipeline()
        snapshot = pipeline._snapshot(turn)
        raw = self.proposal(pipeline._model_context(snapshot, []))
        raw['semantic_formulation']['assessment']['action_link'].pop('anchor_claim_id')
        checked = pipeline._validate_proposal(raw, snapshot, [])
        self.assertEqual('undetermined', checked['decision_type'])
        self.assertIn('semantic_learning_error', checked)

    def test_missing_success_evidence_does_not_invent_a_goal(self):
        turn, _ = self.completed_turn()
        pipeline = self.pipeline()
        snapshot = pipeline._snapshot(turn)
        raw = self.proposal(pipeline._model_context(snapshot, []))
        raw['semantic_formulation']['evidence'] = []
        self.assertEqual('semantic_goal_targets_incomplete', pipeline._validate_proposal(raw, snapshot, [])['reason_code'])
        raw['semantic_formulation']['outcome'] = 'outcome_uncertain'
        checked = pipeline._validate_proposal(raw, snapshot, [])
        self.assertNotEqual('undetermined', checked['decision_type'])

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

    def test_semantic_failure_keeps_general_claim_and_retry_does_not_duplicate_it(self):
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
            self.assertEqual(before + 1, c.execute('SELECT COUNT(*) FROM memory_claims').fetchone()[0])
            self.assertEqual(1, c.execute("SELECT COUNT(*) FROM memory_claims WHERE canonical_key='v2:semantic-atomic-test'").fetchone()[0])
        self.assertEqual('rejected', result['semantic_learning']['kind'])
        pipeline.retry_turn(turn)
        recovered = pipeline.process_batch([turn])[0]
        self.assertEqual('applied', recovered['application_status'], recovered)
        with self.db.connect() as c:
            self.assertEqual(1, c.execute("SELECT COUNT(*) FROM memory_claims WHERE canonical_key='v2:semantic-atomic-test'").fetchone()[0])

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
