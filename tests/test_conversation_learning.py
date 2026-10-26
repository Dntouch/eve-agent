import threading
import json
from types import SimpleNamespace
from unittest.mock import patch
import time
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from eve_agent.conversation_learning import ConversationLearningCoordinator
from eve_agent.shadow_learning import ProductiveLearningPipeline, ShadowLearningCancelled
from eve_agent.storage import ConversationStore, EveDatabase


def proposal(context, value):
    return {
        "decision_type": "create_active", "memory_worthy": True,
        "reason_code": "conversation_batch_test", "uncertainty": 0.0,
        "clarification_recommended": False, "authority": "user_direct",
        "temporal_class": "stable", "change_type": None,
        "claim": {
            "kind": "opaque_fact", "scope": "user:self",
            "canonical_key": f"v2:test:{value}", "slot_key": f"v2:test:{value}",
            "display_text": f"Dauerhafte Information {value}",
            "payload": {"subject": "user:self", "property": "test", "value": value},
            "valid_from": None, "valid_until": None,
        },
        "evidence": [{
            "source_type": "user_message", "source_id": context["user_message"]["id"],
            "stance": "supports", "property": None, "external_reference": None,
        }],
        "matched_claim_ids": [], "relations": [],
    }


class BatchLLM:
    model = "batch-learning-test"

    def __init__(self, *, block=False):
        self.calls = 0
        self.block = block
        self.entered = threading.Event()
        self.cancellation = None

    @contextmanager
    def cancellable(self, cancellation):
        self.cancellation = cancellation
        try:
            yield
        finally:
            self.cancellation = None

    def analyze_conversation_learning(self, contexts):
        self.calls += 1
        self.entered.set()
        if self.block:
            while True:
                self.cancellation.checkpoint()
                time.sleep(.005)
        return {"turns": [
            {"turn_id": context["turn_id"], "proposal": proposal(context, str(index))}
            for index, context in enumerate(contexts, 1)
        ]}


class ContextBoundBatchLLM(BatchLLM):
    def __init__(self, maximum_batch_size):
        super().__init__()
        self.maximum_batch_size = maximum_batch_size
        self.batch_sizes = []

    def analyze_conversation_learning(self, contexts):
        from eve_agent.llm import LocalLLMError
        self.calls += 1
        self.batch_sizes.append(len(contexts))
        if len(contexts) > self.maximum_batch_size:
            diagnostic = RuntimeError(
                "HTTP-400-Response: request exceeds the context window: requests are never truncated"
            )
            raise LocalLLMError("Lokaler LLM-Endpunkt antwortete mit HTTP 400.") from diagnostic
        return {"turns": [
            {"turn_id": context["turn_id"], "proposal": proposal(context, context["turn_id"])}
            for context in contexts
        ]}


class WorkingMemoryFallbackLLM:
    model = 'working-memory-fallback-test'
    generation_max_tokens = 2048

    def __init__(self):
        self.tool_rounds = 0
        self.direct_calls = 0

    def analyze_conversation_learning(self, contexts):
        from eve_agent.llm import LocalLLMContextLimitError
        self.direct_calls += 1
        raise LocalLLMContextLimitError('request exceeds the context window')

    def conversation_learning_context_budget(self, contexts):
        return {'fits': False, 'input_tokens': 12000, 'context_tokens': 9000}

    def context_budget(self, messages, tools):
        size = len(json.dumps({'messages': messages, 'tools': tools}, ensure_ascii=False))
        return {'fits': size < 24000, 'input_tokens': size, 'context_tokens': 24000}

    def request_tool_turn(self, messages, tools, max_tokens, temperature, *, role):
        self.tool_rounds += 1
        if self.tool_rounds == 1:
            runtime = messages[-1]['content']
            data = json.loads(runtime[runtime.index('{'):])
            reference = data['working_memory']['request_reference']
            return {'content': '', 'tool_calls': [{
                'id': 'read-learning-turn', 'name': 'working_memory__read',
                'arguments': {'reference': reference, 'pointer': '/text/turns/0/turn_id'},
            }]}
        turn_id = json.loads(messages[-1]['content'])['content']
        context = {'turn_id': turn_id, 'user_message': {'id': 'unused'}}
        value = proposal(context, 'working-memory')
        value['evidence'] = []
        value['decision_type'] = 'no_persist'
        value['memory_worthy'] = False
        value['claim'] = None
        value['reason_code'] = 'transient_request'
        return {'content': json.dumps({'turns': [{'turn_id': turn_id, 'proposal': value}]}),
                'tool_calls': []}


class ConversationLearningTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = EveDatabase(Path(self.temp.name) / "eve.db")
        self.conversations = ConversationStore(self.database)
        self.conversation_id = self.conversations.create("Learning")['id']

    def turn(self, index):
        turn_id = f"turn-{index}"
        self.conversations.append_turn(
            self.conversation_id, f"Dauerhafte Information {index}", "Verstanden.",
            turn_id=turn_id, assistant_metadata={"route": "chat"},
        )
        return turn_id

    def test_chatto_sender_and_room_reach_learning_and_persisted_evidence(self):
        source = {"transport": "chatto", "sender_id": "sebastian-id",
                  "sender_name": "Sebastian", "room_id": "room-one",
                  "room_kind": "channel", "access_profile": "public_channel"}
        self.conversations.append_turn(
            self.conversation_id, "Dauerhafte Information", "Verstanden.",
            turn_id="chatto-turn", user_metadata={"conversation_source": source},
        )
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        snapshot = pipeline._snapshot("chatto-turn")
        context = pipeline._model_context(snapshot, [])
        self.assertEqual(context["user_message"]["conversation_source"], source)
        pipeline.accept_turn("chatto-turn")
        pipeline.process_batch(["chatto-turn"])
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT metadata_json FROM memory_observations WHERE message_id=? AND source_type='user_message'",
                (snapshot["user_message_id"],),
            ).fetchone()
        self.assertEqual(json.loads(row[0])["conversation_source"], source)

    def failure_retry(self, correction="Nutze das strukturierte Memory-Inventar"):
        from eve_agent.turn_failures import failure_report
        from eve_agent.llm import LocalLLMError
        report=failure_report(LocalLLMError("Das lokale LLM lieferte weder Antwort noch Tool-Aufruf."),
                              turn_id="failed-one",conversation_id=self.conversation_id,input_text="Alle Lichter")
        self.conversations.record_failure(self.conversation_id,report)
        self.conversations.record_retry(self.conversation_id,"retry-one","failed-one",correction)
        self.conversations.append_turn(self.conversation_id,correction,"Fertig",turn_id="retry-one",
            tool_events=[{"tool":"memory","status":"completed","result":{"status":"completed","total_matches":16}}])
        return report

    def test_confirmed_user_instruction_revises_candidate_instead_of_only_appending(self):
        first = self.turn('1')
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        snap = pipeline._snapshot(first)
        raw = proposal(pipeline._model_context(snap, []), '1')
        raw['decision_type'] = 'create_candidate'
        raw['authority'] = 'model_inference'
        pipeline.accept_turn(first)
        old = pipeline._persist(snap, pipeline._validate_proposal(raw, snap, []), 'test', {}, time.perf_counter())
        self.conversations.append_turn(self.conversation_id, snap['user_content'], 'Bestätigt', turn_id='confirmed')
        current = pipeline._snapshot('confirmed')
        raw = proposal(pipeline._model_context(current, []), '1')
        raw['claim']['payload']['epistemic_kind'] = 'user_instruction'
        normalized = pipeline._validate_proposal(raw, current, [])
        self.assertEqual('create_active', normalized['decision_type'])
        pipeline.accept_turn('confirmed')
        new = pipeline._persist(current, normalized, 'test', {}, time.perf_counter())
        with self.database.connect() as c:
            self.assertEqual('retired', c.execute('SELECT lifecycle FROM memory_claims WHERE id=?',(old['claim_id'],)).fetchone()[0])
            row = c.execute('SELECT lifecycle,payload_json FROM memory_claims WHERE id=?',(new['claim_id'],)).fetchone()
            self.assertEqual('active', row[0])
            self.assertEqual('user_instruction', json.loads(row[1])['epistemic_kind'])
        self.assertNotEqual(old['claim_id'], new['claim_id'])

    def test_user_instruction_requires_verbatim_current_user_evidence(self):
        tid = self.turn('instruction')
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        snapshot = pipeline._snapshot(tid)
        context = pipeline._model_context(snapshot, [])
        value = proposal(context, 'instruction')
        value['claim']['display_text'] = snapshot['user_content']
        value['claim']['payload']['epistemic_kind'] = 'user_instruction'
        valid = pipeline._validate_proposal(value, snapshot, [])
        self.assertEqual('create_active', valid['decision_type'])
        value['claim']['display_text'] = 'Invented cause unrelated to the user source'
        invalid = pipeline._validate_proposal(value, snapshot, [])
        self.assertEqual('undetermined', invalid['decision_type'])
        self.assertEqual('user_instruction_not_grounded_verbatim', invalid['reason_code'])

    def test_instruction_formatting_restores_exact_source_without_paraphrasing(self):
        tid = self.turn('Private Daten bleiben privat.\n\nAuch gegenüber mir.')
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        snapshot = pipeline._snapshot(tid)
        context = pipeline._model_context(snapshot, [])
        value = proposal(context, 'instruction')
        value['claim']['payload']['epistemic_kind'] = 'user_instruction'
        value['claim']['display_text'] = 'Private Daten bleiben privat. Auch gegenüber mir.'
        valid = pipeline._validate_proposal(value, snapshot, [])
        self.assertEqual('create_active', valid['decision_type'])
        self.assertEqual('Private Daten bleiben privat.\n\nAuch gegenüber mir.', valid['claim']['display_text'])
        value['claim']['display_text'] = 'Private Daten sind privat. Auch gegenüber mir.'
        invalid = pipeline._validate_proposal(value, snapshot, [])
        self.assertEqual('user_instruction_not_grounded_verbatim', invalid['reason_code'])

    def test_execution_receipts_link_attempts_without_assessing_task_success(self):
        from eve_agent.working_memory import WorkingMemoryStore
        store = WorkingMemoryStore(self.database)
        workspace = store.open(self.conversation_id)
        work_turn, _ = store.begin_turn(workspace, self.conversation_id, {'task': 'test'}, 'trace')
        ids = []
        for index, result in enumerate([
                {'status': 'error', 'projection_complete': False},
                {'status': 'completed', 'content': [{'x': 1}], 'projection_complete': True}]):
            call = store.start_call(workspace, work_turn, str(index), 'working_memory', 'read', 'read',
                                    {'reference': 'original', 'fields': ['x.y'] if not index else ['/x/y']})
            store.dispatch_call(workspace, call)
            store.finish_call(workspace, work_turn, call, result)
            ids.append(call)
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        snapshot = pipeline._snapshot(self.turn('receipt-learning'))
        snapshot['working_memory'] = {'work_turn_id': work_turn}
        trace = pipeline._model_context(snapshot, [])['execution_trace']
        self.assertEqual(ids, [r['call_reference'] for r in trace])
        self.assertIsNone(trace[0]['previous_call_reference'])
        self.assertEqual(ids[0], trace[1]['previous_call_reference'])
        self.assertEqual(['/x/y'], trace[1]['input']['fields'])
        self.assertFalse(trace[1]['task_success_assessed'])
        self.assertNotIn('content', trace[1]['result_metadata'])
        self.assertIsNotNone(trace[1]['result_reference'])
        snapshot['conversation_id'] = 'other-conversation'
        self.assertEqual([], pipeline._execution_trace(snapshot))

    def test_execution_trace_does_not_duplicate_published_tool_event_payload(self):
        from eve_agent.working_memory import WorkingMemoryStore
        store = WorkingMemoryStore(self.database)
        workspace = store.open(self.conversation_id)
        work_turn, _ = store.begin_turn(workspace, self.conversation_id, {'task': 'test'}, 'dedup')
        call = store.start_call(workspace, work_turn, 'dedup-call', 'web', 'search', 'read',
                                {'query': 'published once'})
        store.dispatch_call(workspace, call)
        store.finish_call(workspace, work_turn, call,
                          {'status': 'completed', 'sources': [{'title': 'full evidence'}]})
        turn = 'deduplicated-learning'
        self.conversations.append_turn(
            self.conversation_id, 'Prüfe den Turn', 'Ergebnis', turn_id=turn,
            assistant_metadata={'route': 'web', 'working_memory': {'work_turn_id': work_turn}},
            tool_events=[{'tool': 'web', 'status': 'returned', 'input': {'query': 'published once'},
                          'result': {'status': 'completed', 'sources': [{'title': 'full evidence'}]}}],
        )
        context = ProductiveLearningPipeline(
            self.database, BatchLLM(),
        )._model_context(ProductiveLearningPipeline(
            self.database, BatchLLM(),
        )._snapshot(turn), [])
        self.assertEqual('full evidence', context['tool_events'][0]['result']['sources'][0]['title'])
        receipt = context['execution_trace'][0]
        self.assertEqual('tool_events', receipt['payload_source'])
        self.assertNotIn('input', receipt)
        self.assertNotIn('result_metadata', receipt)

    def test_explicit_episode_keeps_original_diagnostics_without_evidence_promotion(self):
        source = self.turn('source')
        self.conversations.append_turn(self.conversation_id, 'Korrigiere die Auswahl', 'Erledigt',
            turn_id='corrected', tool_events=[{'tool':'working_memory','status':'error',
                'input':{'pointer':'/wrong','fields':['x.y']},
                'result':{'status':'error','projection_complete':False,
                          'projection_diagnostics':{'paths':['/x/'+str(i) for i in range(100)]},
                          'content':['private original values']}}])
        target = self.turn('learning')
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        pipeline.accept_episode(target, [source, 'corrected'])
        self.assertTrue(pipeline.accept_episode(target, [source, 'corrected'])['idempotent'])
        context = pipeline._model_context(pipeline._snapshot(target), [])
        episode = context['learning_episode']
        self.assertTrue(episode['context_only'])
        tool = episode['turns'][1]['tool_events'][0]
        self.assertEqual('/wrong', tool['input']['pointer'])
        self.assertEqual(100, len(tool['result']['projection_diagnostics']['paths']))
        self.assertNotIn('content', tool['result'])
        self.assertNotIn('evidence_reference', tool)
        evidence = [{'source_type':'user_message','source_id':pipeline._snapshot(source)['user_message_id']}]
        self.assertEqual('invented_message_reference', pipeline._validated_evidence(evidence,pipeline._snapshot(target)))
        self.assertTrue(pipeline.accept_episode(target, [source])['idempotent'])
        with self.assertRaises(ValueError): pipeline.accept_episode(source, [target])

    def test_evidence_reference_is_copied_from_the_actual_turn(self):
        self.failure_retry()
        pipeline=ProductiveLearningPipeline(self.database,BatchLLM())
        snapshot=pipeline._snapshot('retry-one');context=pipeline._model_context(snapshot,[])
        self.assertEqual({'source_type':'user_message','source_id':snapshot['user_message_id']},
                         context['user_message']['evidence_reference'])
        self.assertEqual({'source_type':'provider_result','source_id':snapshot['tools'][0]['id']},
                         context['tool_events'][0]['evidence_reference'])
        self.assertEqual(['source_type','source_id'],context['evidence_contract']['required'])
        self.assertNotIn('evidence_reference',context['assistant_context'])

    def direct_result_turn(self):
        turn = 'direct-result'
        self.conversations.append_turn(self.conversation_id, 'Prüfe den Abruf', 'Ergebnis', turn_id=turn,
            tool_events=[{'tool':'working_memory', 'status':'completed', 'input':{},
                'result':{'projection_complete':True,'reference':'original',
                          'content':{'a/b':{'x~y':[None, False, 0]}}}}])
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        snapshot = pipeline._snapshot(turn)
        return pipeline, snapshot, snapshot['tools'][0]['id']

    def test_direct_result_evidence_preserves_types_and_resolves_actual_pointers(self):
        pipeline, snapshot, source = self.direct_result_turn()
        published = pipeline._model_context(snapshot, [])['tool_events'][0]['result_evidence']['observed_fields']
        self.assertIn({'source_type':'provider_result','source_id':source,
                       'result_pointer':'/projection_complete','observed_value':True}, published)
        def check(pointer, value):
            return pipeline._validated_evidence([{'source_type':'provider_result','source_id':source,
                'result_pointer':pointer,'observed_value':value}], snapshot)
        for pointer, value in [('/projection_complete', True), ('/content/a~1b/x~0y/0', None),
                               ('/content/a~1b/x~0y/1', False), ('/content/a~1b/x~0y/2', 0)]:
            with self.subTest(pointer=pointer):
                result = check(pointer, value)
                self.assertIsInstance(result, list)
                self.assertEqual(value, result[0]['observed_value'])
        for value in ['true', 1, None, False]:
            self.assertEqual('result_evidence_value_mismatch', check('/projection_complete', value))
        self.assertEqual('result_evidence_pointer_not_found', check('/missing', None))
        self.assertEqual('result_evidence_invalid_pointer', check('/bad~2key', True))
        self.assertEqual('result_evidence_invalid_pointer', check('projection_complete', True))
        self.assertIsInstance(check('', json.loads(snapshot['tools'][0]['result_json'])), list)
        missing = {'source_type':'provider_result','source_id':source,'result_pointer':'/projection_complete'}
        self.assertEqual('result_evidence_missing_value', pipeline._validated_evidence([missing], snapshot))
        missing['source_id'] = 'invented'
        self.assertEqual('invented_tool_reference', pipeline._validated_evidence([missing], snapshot))
        self.assertEqual('result_evidence_requires_tool_source', pipeline._validated_evidence([
            {'source_type':'user_message','source_id':snapshot['user_message_id'],
             'result_pointer':'','observed_value':True}], snapshot))

    def test_pointer_revision_reports_escaped_children_from_original_result(self):
        pipeline, snapshot, source = self.direct_result_turn()
        pipeline.accept_turn(snapshot['turn_id'])
        raw = proposal(pipeline._model_context(snapshot, []), 'pointer-revision')
        raw['evidence'] = [{'source_type': 'provider_result', 'source_id': source,
                            'result_pointer': '/content/a/b', 'observed_value': None}]
        rejected = pipeline._validate_proposal(raw, snapshot, [])
        self.assertEqual('result_evidence_pointer_not_found', rejected['reason_code'])
        pipeline._persist_unresolved(snapshot, rejected, 'test', {})
        feedback = pipeline._model_context(snapshot, [])['learning_revision']
        error = next(item for item in feedback['field_errors']
                     if item.get('code') == 'pointer_not_found_in_original_tool_result')
        self.assertEqual('/content/a/b', error['requested_pointer'])
        self.assertIn('/content/a~1b', [item['pointer']
                                      for item in error['structure_at_failure']['available_children']])

    def test_refinement_inherits_validated_target_lifecycle(self):
        turn = self.turn('refinement-lifecycle')
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        snapshot = pipeline._snapshot(turn)
        raw = proposal(pipeline._model_context(snapshot, []), 'refinement-lifecycle')
        raw['decision_type'] = 'refine_claim'
        raw['authority'] = 'model_inference'
        raw['matched_claim_ids'] = ['target-claim']
        raw['claim'].pop('lifecycle', None)
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO memory_claims
                   (id,claim_kind,scope,canonical_key,display_text,payload_json,lifecycle,
                    verification_policy,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,'candidate','unknown',?,?)""",
                ('target-claim', raw['claim']['kind'], raw['claim']['scope'],
                 raw['claim']['canonical_key'], 'existing target', '{}',
                 '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'),
            )
        candidate = {**raw['claim'], 'id': 'target-claim', 'claim_kind': raw['claim']['kind'],
                     'lifecycle': 'candidate', 'slot_key': None}
        result = pipeline._validate_proposal(raw, snapshot, [candidate])
        self.assertEqual('refine_claim', result['decision_type'])
        self.assertEqual('candidate', result['claim']['lifecycle'])
        self.assertTrue(result['claim']['canonical_key'].startswith(
            raw['claim']['canonical_key'] + ':refinement:'
        ))

    def test_array_tool_result_is_described_without_reconstructing_its_content(self):
        turn = 'array-tool-result'
        self.conversations.append_turn(
            self.conversation_id, 'Nutze die gefundenen Memory-Einträge', 'Erledigt', turn_id=turn,
            tool_events=[{'tool': 'memory', 'status': 'completed', 'input': {'query': 'test'},
                          'result': [{'memory_id': 'one', 'content': 'privater Inhalt'},
                                     {'memory_id': 'two', 'content': 'weiterer Inhalt'}]}],
        )
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        context = pipeline._model_context(pipeline._snapshot(turn), [])
        event = context['tool_events'][0]
        self.assertEqual({'root_type': 'list', 'item_count': 2}, event['result'])
        self.assertEqual(2, event['observed_outcome']['result_count'])
        self.assertEqual('list', event['material']['result_type'])
        self.assertEqual([], event['result_evidence']['observed_fields'])
        self.assertNotIn('privater Inhalt', json.dumps(event, ensure_ascii=False))

    def test_distinct_values_from_one_tool_result_have_distinct_observations(self):
        pipeline, snapshot, source = self.direct_result_turn()
        def analyze(contexts):
            value = proposal(contexts[0], 'multiple-properties')
            value['evidence'] = [
                {'source_type': 'provider_result', 'source_id': source, 'result_pointer': '/projection_complete', 'observed_value': True},
                {'source_type': 'provider_result', 'source_id': source, 'result_pointer': '/reference', 'observed_value': 'original'},
                {'source_type': 'provider_result', 'source_id': source, 'result_pointer': '/projection_complete', 'observed_value': True},
            ]
            return {'turns': [{'turn_id': snapshot['turn_id'], 'proposal': value}]}
        pipeline.llm = SimpleNamespace(model='multi-property-test', analyze_conversation_learning=analyze)
        result = pipeline.process_batch([snapshot['turn_id']])[0]
        self.assertEqual('applied', result['application_status'])
        with self.database.connect() as c:
            evidence = c.execute('SELECT observation_id,payload_json FROM memory_evidence').fetchall()
            self.assertEqual(2, len(evidence))
            self.assertEqual(2, len({row[0] for row in evidence}))
            self.assertEqual({'/reference', '/projection_complete'}, {json.loads(row[1])['result_pointer'] for row in evidence})
            self.assertEqual([], c.execute('PRAGMA foreign_key_check').fetchall())

    def test_working_memory_learning_accepts_a_complete_markdown_json_fence(self):
        turn = self.turn('fenced-working-result')
        llm = WorkingMemoryFallbackLLM()
        original = llm.request_tool_turn
        def request(*args, **kwargs):
            message = original(*args, **kwargs)
            if not message.get('tool_calls'):
                message['content'] = '```json\n' + message['content'] + '\n```'
            return message
        llm.request_tool_turn = request
        result = ProductiveLearningPipeline(self.database, llm).process_batch([turn])[0]
        self.assertEqual('applied', result['application_status'])
        self.assertEqual('no_persist', result['decision_type'])

    def test_output_limit_remains_an_output_error_without_context_recovery(self):
        from eve_agent.llm import LocalLLMOutputLimitError
        turn = self.turn('output-limit')
        llm = WorkingMemoryFallbackLLM()
        def request(*args, **kwargs): raise LocalLLMOutputLimitError('length', '{"turns": [')
        llm.request_tool_turn = request
        with patch('eve_agent.working_context.WorkingMemorySession.recover') as recover:
            result = ProductiveLearningPipeline(self.database, llm).process_batch([turn])[0]
        self.assertEqual('failed', result['application_status'])
        self.assertEqual('LocalLLMOutputLimitError', result['reason_code'])
        self.assertEqual('length', result['details']['finish_reason'])
        self.assertEqual('{"turns": [', result['details']['partial_response'])
        recover.assert_not_called()

    def test_direct_evidence_candidate_persists_pointer_and_value_without_promotion(self):
        pipeline, snapshot, source = self.direct_result_turn()
        def analyze(contexts):
            item = proposal(contexts[0], 'direct-result-procedure')
            item.update(decision_type='create_candidate', authority='model_inference')
            item['claim']['payload'] = {'epistemic_kind':'procedural_hypothesis'}
            item['evidence'] = [{'source_type':'provider_result','source_id':source,
                                'result_pointer':'/projection_complete','observed_value':True}]
            return {'turns':[{'turn_id':snapshot['turn_id'],'proposal':item}]}
        pipeline.llm = SimpleNamespace(model='direct-test', analyze_conversation_learning=analyze)
        result = pipeline.process_batch([snapshot['turn_id']])[0]
        self.assertEqual('applied', result['application_status'])
        with self.database.connect() as c:
            self.assertEqual('candidate', c.execute('SELECT lifecycle FROM memory_claims').fetchone()[0])
            payload = json.loads(c.execute('SELECT payload_json FROM memory_evidence').fetchone()[0])
            self.assertEqual('/projection_complete', payload['result_pointer'])
            self.assertIs(True, payload['observed_value'])
            observation = json.loads(c.execute("SELECT structured_value_json FROM memory_observations WHERE tool_event_id=?", (source,)).fetchone()[0])
            self.assertEqual('/projection_complete', observation['result_pointer'])
            self.assertIs(True, observation['observed_value'])

    def test_direct_result_does_not_replace_resource_binding_requirements(self):
        pipeline, snapshot, source = self.direct_result_turn()
        direct = {'source_type':'provider_result','source_id':source,
                  'result_pointer':'/projection_complete','observed_value':True}
        evidence = pipeline._validated_evidence([direct], snapshot)
        raw = proposal(pipeline._model_context(snapshot, []), 'binding')
        raw['claim'].update(kind='provider_binding', payload={'provider':'working_memory',
            'subject':'user:self','property':'test','external_reference':'original'})
        self.assertEqual('provider_binding_requires_separate_sources', pipeline._normalize_new_claim(
            raw['claim'], 'create_candidate', 'model_inference', evidence, snapshot))
        mixed = [{**evidence[0], 'property':'invented', 'external_reference':'invented'}]
        self.assertEqual('provider_binding_requires_separate_sources', pipeline._normalize_new_claim(
            raw['claim'], 'create_candidate', 'model_inference', mixed, snapshot))
        resource = {'source_type':'provider_result','source_id':source,
                    'property':'projection_complete','external_reference':'original'}
        self.assertIsInstance(pipeline._validated_evidence([resource], snapshot), list)

    def test_unused_nullable_selection_does_not_mask_origin_validation(self):
        turn = self.turn('null-selection')
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        snapshot = pipeline._snapshot(turn)
        item = proposal(pipeline._model_context(snapshot, []), 'null-selection')
        item['evidence'][0].update(result_pointer=None, observed_value=None)
        item['claim']['payload']['epistemic_kind'] = 'user_instruction'
        item['claim']['display_text'] = 'Not a quotation from this user'
        result = pipeline._validate_proposal(item, snapshot, [])
        self.assertEqual('user_instruction_not_grounded_verbatim', result['reason_code'])
        item['evidence'][0]['result_pointer'] = ''
        self.assertEqual('result_evidence_requires_tool_source',
                         pipeline._validate_proposal(item, snapshot, [])['reason_code'])

    def test_revision_shows_rejected_proposal_once_and_pinpoints_origin_fields(self):
        turn = self.turn('origin-revision')
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        pipeline.accept_turn(turn)
        snapshot = pipeline._snapshot(turn)
        original = proposal(pipeline._model_context(snapshot, []), 'origin-revision')
        original['claim']['display_text'] = 'UNIQUE_REJECTED_PROCEDURE_731'
        original['claim']['payload']['epistemic_kind'] = 'user_instruction'
        rejected = pipeline._validate_proposal(original, snapshot, [])
        self.assertEqual('user_instruction_not_grounded_verbatim', rejected['reason_code'])
        attempt = pipeline._persist_unresolved(snapshot, rejected, 'test', {})
        context = pipeline._model_context(snapshot, [])
        feedback = context['learning_revision']
        self.assertEqual(1, json.dumps(context).count('UNIQUE_REJECTED_PROCEDURE_731'))
        self.assertEqual('rejected_not_evidence', feedback['previous_proposal_status'])
        self.assertNotIn('raw_proposal', feedback['validation_result']['details'])
        self.assertEqual(original, feedback['previous_proposal'])
        paths = {error['path'] for error in feedback['field_errors']}
        self.assertIn('/claim/display_text', paths)
        self.assertIn('/claim/payload/epistemic_kind', paths)
        self.assertEqual('model_inference', context['provenance_contract']['inferred_procedure']['authority'])
        self.assertEqual('create_candidate', context['provenance_contract']['inferred_procedure']['decision_type'])
        self.assertTrue(context['assistant_context']['context_only'])
        self.assertEqual(snapshot['assistant_content'], context['assistant_context']['content'])
        with self.database.connect() as c:
            stored = json.loads(c.execute('SELECT structured_value_json FROM memory_observations WHERE id=?',
                                          (attempt['attempt_observation_id'],)).fetchone()[0])
        self.assertEqual(original, stored['proposal']['details']['raw_proposal'])

    def test_wrong_origin_authority_has_specific_diagnosis_without_rewriting(self):
        turn = self.turn('wrong-origin-authority')
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        pipeline.accept_turn(turn)
        snapshot = pipeline._snapshot(turn)
        original = proposal(pipeline._model_context(snapshot, []), 'wrong-origin-authority')
        original['claim']['display_text'] = snapshot['user_content']
        original['claim']['payload']['epistemic_kind'] = 'user_instruction'
        original['authority'] = 'model_inference'
        rejected = pipeline._validate_proposal(original, snapshot, [])
        pipeline._persist_unresolved(snapshot, rejected, 'test', {})
        feedback = pipeline._model_context(snapshot, [])['learning_revision']
        paths = {error['path'] for error in feedback['field_errors']}
        self.assertIn('/authority', paths)
        self.assertIn('/claim/payload/epistemic_kind', paths)
        self.assertNotIn('/claim/display_text', paths)
        self.assertEqual('model_inference', feedback['previous_proposal']['authority'])

    def test_malformed_claim_does_not_break_revision_context(self):
        turn = self.turn('malformed-claim')
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        pipeline.accept_turn(turn)
        snapshot = pipeline._snapshot(turn)
        pipeline._persist_unresolved(snapshot, {'decision_type': 'undetermined', 'reason_code': 'invalid_claim_shape',
            'details': {'raw_proposal': {'claim': ['malformed'], 'evidence': []}}}, 'test', {})
        feedback = pipeline._model_context(snapshot, [])['learning_revision']
        self.assertEqual('invalid_claim_shape', feedback['reason_code'])
        self.assertNotIn('instruction_provenance', feedback)

    def test_revision_diagnosis_exposes_contract_fields_not_replacement_lesson(self):
        turn = 'revision-diagnostics'
        self.conversations.append_turn(self.conversation_id, 'Lies die Daten', 'Ergebnis', turn_id=turn,
            tool_events=[{'tool': 'working_memory', 'status': 'completed', 'input': {},
                          'result': {'reference': 'original-reference', 'projection_complete': True,
                                     'content': ['not copied']}}])
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        pipeline.accept_turn(turn)
        snapshot = pipeline._snapshot(turn)
        raw = proposal(pipeline._model_context(snapshot, []), 'diagnostic')
        raw['claim']['payload']['epistemic_kind'] = 'user_instruction'
        raw['evidence'].append({'source_type': 'provider_result', 'source_id': snapshot['tools'][0]['id']})
        rejected = pipeline._validate_proposal(raw, snapshot, [])
        pipeline._persist_unresolved(snapshot, rejected, 'test', {})
        feedback = pipeline._model_context(snapshot, [])['learning_revision']
        self.assertEqual(['property', 'external_reference'], feedback['field_errors'][0]['missing_fields'])
        self.assertFalse(feedback['instruction_provenance']['display_text_occurs_verbatim'])
        binding = feedback['provider_bindings'][0]
        self.assertEqual('original-reference', binding['published_string_values']['reference'])
        self.assertIn('projection_complete', binding['published_properties'])
        self.assertNotIn('content', binding['published_properties'])
        self.assertNotIn('replacement_claim', feedback)

    def test_revision_publishes_turn_scoped_claim_reference_error(self):
        turn = self.turn('claim-reference')
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        pipeline.accept_turn(turn)
        snapshot = pipeline._snapshot(turn)
        raw = proposal(pipeline._model_context(snapshot, []), 'claim-reference')
        raw['matched_claim_ids'] = ['claim-from-another-turn']
        rejected = pipeline._validate_proposal(raw, snapshot, [])
        pipeline._persist_unresolved(snapshot, rejected, 'test', {})
        feedback = pipeline._model_context(snapshot, [])['learning_revision']
        error = next(item for item in feedback['field_errors']
                     if item.get('code') == 'claim_not_published_for_current_turn')
        self.assertEqual('/matched_claim_ids', error['path'])
        self.assertEqual(['claim-from-another-turn'], error['invalid_values'])
        self.assertEqual([], feedback['claim_references']['allowed_claim_ids'])

    def test_rejected_proposal_is_revised_with_feedback_only_for_affected_turn(self):
        turns = [self.turn('revision'), self.turn('valid')]
        contexts_seen = []
        def analyze(contexts):
            contexts_seen.append(contexts)
            output = []
            for context in contexts:
                item = proposal(context, context['turn_id'])
                if len(contexts_seen) == 1 and context['turn_id'] == turns[0]:
                    item['evidence'][0]['source_type'] = 'assistant_message'
                output.append({'turn_id': context['turn_id'], 'proposal': item})
            return {'turns': output}
        llm = SimpleNamespace(model='revision-test', analyze_conversation_learning=analyze)
        pipeline = ProductiveLearningPipeline(self.database, llm)
        results = pipeline.process_batch(turns)
        self.assertEqual(2, len(contexts_seen))
        self.assertEqual([turns[0]], [c['turn_id'] for c in contexts_seen[1]])
        feedback = contexts_seen[1][0]['learning_revision']
        self.assertTrue(feedback['context_only'])
        self.assertEqual('non_evidence_source', feedback['reason_code'])
        self.assertEqual('assistant_message', feedback['previous_proposal']['evidence'][0]['source_type'])
        self.assertEqual(['applied', 'applied'], [r['application_status'] for r in results])
        self.assertEqual(feedback['attempt_observation_id'], results[0]['details']['revision_of_attempt'])
        with self.database.connect() as c:
            self.assertEqual(2, c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])
            self.assertIsNotNone(c.execute('SELECT id FROM memory_observations WHERE id=?',
                                          (feedback['attempt_observation_id'],)).fetchone())

    def test_revisions_are_isolated_per_turn(self):
        turns = [self.turn('isolated-a'), self.turn('isolated-b')]
        batches = []

        def analyze(contexts):
            batches.append([context['turn_id'] for context in contexts])
            output = []
            for context in contexts:
                item = proposal(context, context['turn_id'])
                if len(contexts) > 1:
                    item['evidence'][0]['source_type'] = 'assistant_message'
                output.append({'turn_id': context['turn_id'], 'proposal': item})
            return {'turns': output}

        pipeline = ProductiveLearningPipeline(
            self.database, SimpleNamespace(model='isolated-revision-test',
                                           analyze_conversation_learning=analyze),
        )
        results = pipeline.process_batch(turns)
        self.assertEqual([turns, [turns[0]], [turns[1]]], batches)
        self.assertEqual(['applied', 'applied'], [item['application_status'] for item in results])

    def test_rejected_revision_stays_failed_and_resumption_receives_latest_attempt(self):
        turn = self.turn('revision-rejected')
        seen = []
        def analyze(contexts):
            seen.append(contexts)
            item = proposal(contexts[0], 'invalid')
            item['evidence'][0]['source_id'] = 'invented'
            return {'turns': [{'turn_id': turn, 'proposal': item}]}
        pipeline = ProductiveLearningPipeline(self.database,
            SimpleNamespace(model='revision-test', analyze_conversation_learning=analyze))
        result = pipeline.process_batch([turn])[0]
        self.assertEqual('failed', result['application_status'])
        self.assertEqual(2, len(seen))
        with self.database.connect() as c:
            self.assertEqual(0, c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])
        pipeline.retry_turn(turn)
        result = pipeline.process_batch([turn])[0]
        self.assertEqual(result['reason_code'], seen[2][0]['learning_revision']['reason_code'])
        self.assertNotIn('previous_proposal', seen[2][0]['learning_revision'])
        self.assertFalse(seen[2][0]['learning_revision']['previous_proposal_in_context'])
        self.assertIn('previous_proposal', seen[3][0]['learning_revision'])
        self.assertEqual('failed', result['application_status'])
        self.assertEqual(4, len(seen))
        self.assertNotEqual(seen[1][0]['learning_revision']['attempt_observation_id'],
                            seen[2][0]['learning_revision']['attempt_observation_id'])

    def test_malformed_revision_cannot_write_other_turn_or_discard_valid_results(self):
        turn = self.turn('bad-revision')
        calls = []
        def analyze(contexts):
            calls.append(contexts)
            item = proposal(contexts[0], 'invalid')
            item['evidence'][0]['source_id'] = 'invented'
            return {'turns': [{'turn_id': turn if len(calls) == 1 else 'foreign-turn', 'proposal': item}]}
        pipeline = ProductiveLearningPipeline(self.database,
            SimpleNamespace(model='revision-test', analyze_conversation_learning=analyze))
        result = pipeline.process_batch([turn])[0]
        self.assertEqual('failed', result['application_status'])
        self.assertEqual('revision', result['details']['stage'])
        self.assertEqual('invalid_batch_turn_response', result['details']['message'])
        with self.database.connect() as c:
            self.assertEqual(0, c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])
            self.assertEqual('failed', c.execute('SELECT status FROM memory_learning_jobs').fetchone()[0])

    def test_paraphrased_instruction_can_be_revised_using_original_user_source(self):
        turn = self.turn('instruction-repair')
        seen = []
        def analyze(contexts):
            seen.append(contexts)
            context = contexts[0]
            value = proposal(context, 'instruction-repair')
            value['claim']['payload']['epistemic_kind'] = 'user_instruction'
            value['claim']['display_text'] = 'Paraphrased instruction' if len(seen) == 1 else context['user_message']['content']
            return {'turns': [{'turn_id': turn, 'proposal': value}]}
        pipeline = ProductiveLearningPipeline(self.database, SimpleNamespace(model='instruction-repair', analyze_conversation_learning=analyze))
        result = pipeline.process_batch([turn])[0]
        self.assertEqual('applied', result['application_status'])
        self.assertEqual(2, len(seen))
        self.assertEqual('user_instruction_not_grounded_verbatim', seen[1][0]['learning_revision']['reason_code'])
        with self.database.connect() as c:
            claim = c.execute('SELECT display_text,payload_json FROM memory_claims').fetchone()
        self.assertEqual('Dauerhafte Information instruction-repair', claim[0])
        self.assertEqual('user_instruction', json.loads(claim[1])['epistemic_kind'])

    def test_batch_duplicate_identity_attaches_both_sources_once(self):
        turns = [self.turn('same-a'), self.turn('same-b')]
        def analyze(contexts):
            return {'turns': [{'turn_id': context['turn_id'], 'proposal': proposal(context, 'same-key')}
                              for context in contexts]}
        pipeline = ProductiveLearningPipeline(self.database, SimpleNamespace(model='duplicate-test', analyze_conversation_learning=analyze))
        results = pipeline.process_batch(turns)
        self.assertEqual(['applied', 'applied'], [result['application_status'] for result in results])
        self.assertEqual('append_supporting_evidence', results[1]['decision_type'])
        with self.database.connect() as c:
            self.assertEqual(1, c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])
            self.assertEqual(2, c.execute('SELECT count(*) FROM memory_evidence').fetchone()[0])
        self.assertTrue(all(item['idempotent'] for item in pipeline.process_batch(turns)))

    def test_transaction_rechecks_identity_even_when_proposals_were_prevalidated(self):
        turns = [self.turn('stale-a'), self.turn('stale-b')]
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        pending = []
        for turn in turns:
            pipeline.accept_turn(turn)
            snapshot = pipeline._snapshot(turn)
            raw = proposal(pipeline._model_context(snapshot, []), 'stale-key')
            pending.append((snapshot, pipeline._validate_proposal(raw, snapshot, [])))
        results = [pipeline._persist(snapshot, value, 'test', {}, time.perf_counter()) for snapshot, value in pending]
        self.assertEqual('append_supporting_evidence', results[1]['decision_type'])
        with self.database.connect() as c:
            self.assertEqual(1, c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])
            self.assertEqual(2, c.execute('SELECT count(*) FROM memory_evidence').fetchone()[0])

    def test_persistence_error_does_not_discard_following_valid_turns(self):
        import sqlite3
        turns = [self.turn('bad-write'), self.turn('good-write')]
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        original = pipeline._persist
        def persist(snapshot, *args):
            if snapshot['turn_id'] == turns[0]:
                raise sqlite3.IntegrityError('test unique collision')
            return original(snapshot, *args)
        with patch.object(pipeline, '_persist', side_effect=persist):
            results = pipeline.process_batch(turns)
        self.assertEqual(['failed', 'applied'], [result['application_status'] for result in results])
        self.assertEqual('IntegrityError', results[0]['reason_code'])
        self.assertEqual('persistence', results[0]['details']['stage'])
        with self.database.connect() as c:
            self.assertEqual(1, c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])
            self.assertEqual('applied', c.execute('SELECT status FROM memory_learning_jobs WHERE turn_id=?', (turns[1],)).fetchone()[0])

    def test_revision_transport_error_keeps_original_reason_and_valid_sibling(self):
        from eve_agent.llm import LocalLLMError
        turns = [self.turn('revision-error'), self.turn('revision-good')]
        def analyze(contexts):
            if len(contexts) == 1:
                raise LocalLLMError('empty revision response')
            items = [{'turn_id': context['turn_id'], 'proposal': proposal(context, context['turn_id'])} for context in contexts]
            items[0]['proposal']['evidence'][0]['source_type'] = 'assistant_output'
            return {'turns': items}
        pipeline = ProductiveLearningPipeline(self.database, SimpleNamespace(model='revision-error-test', analyze_conversation_learning=analyze))
        results = pipeline.process_batch(turns)
        self.assertEqual(['failed', 'applied'], [result['application_status'] for result in results])
        self.assertEqual('non_evidence_source', results[0]['details']['original_reason_code'])
        self.assertEqual('empty revision response', results[0]['details']['message'])
        self.assertEqual('revision', results[0]['details']['stage'])
        with self.database.connect() as c:
            attempts = [json.loads(row[0]) for row in c.execute("SELECT structured_value_json FROM memory_observations WHERE turn_id=? AND external_ref LIKE 'learning_attempt:%' ORDER BY created_at", (turns[0],))]
        self.assertEqual(2, len(attempts))
        self.assertEqual('non_evidence_source', attempts[0]['reason_code'])
        self.assertEqual('LocalLLMError', attempts[1]['reason_code'])
        self.assertIsNotNone(attempts[1]['revision_of_attempt'])

    def test_partial_response_retries_only_missing_turn_and_preserves_success(self):
        from eve_agent.llm import LocalLLMError
        turns = [self.turn('present'), self.turn('missing')]
        calls = []
        def analyze(contexts):
            calls.append([context['turn_id'] for context in contexts])
            if len(contexts) == 1:
                raise LocalLLMError('missing turn unavailable')
            return {'turns': [{'turn_id': turns[0], 'proposal': proposal(contexts[0], 'present')}]}
        pipeline = ProductiveLearningPipeline(self.database, SimpleNamespace(model='partial-test', analyze_conversation_learning=analyze))
        results = pipeline.process_batch(turns)
        self.assertEqual(['applied', 'failed'], [result['application_status'] for result in results])
        self.assertEqual([turns, [turns[1]]], calls)

    def test_rejected_evidence_is_failed_with_original_output_and_can_be_retried(self):
        turn=self.turn(1);llm=BatchLLM();pipeline=ProductiveLearningPipeline(self.database,llm)
        original=llm.analyze_conversation_learning
        def malformed(contexts):
            raw=original(contexts)
            raw['turns'][0]['proposal']['evidence'][0]['source_type']='assistant_output'
            raw['turns'][0]['proposal']['diagnostic_material']=['unchanged']*70
            return raw
        llm.analyze_conversation_learning=malformed
        result=pipeline.process_batch([turn])[0]
        self.assertEqual('failed',result['application_status'])
        attempt=result['attempt_observation_id']
        with self.database.connect() as c:
            job=dict(c.execute('SELECT * FROM memory_learning_jobs WHERE turn_id=?',(turn,)).fetchone())
            observation=json.loads(c.execute('SELECT structured_value_json FROM memory_observations WHERE id=?',
                                            (result['attempt_observation_id'],)).fetchone()[0])
            self.assertEqual(0,c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])
            self.assertEqual(0,c.execute('SELECT count(*) FROM memory_learning_decisions').fetchone()[0])
        self.assertEqual('failed',job['status']);self.assertEqual('non_evidence_source',job['error_class'])
        raw=observation['proposal']['details']['raw_proposal']
        self.assertEqual('assistant_output',raw['evidence'][0]['source_type'])
        self.assertEqual(70,len(raw['diagnostic_material']))
        llm.analyze_conversation_learning=original
        pipeline.retry_turn(turn);result=pipeline.process_batch([turn])[0]
        self.assertEqual('applied',result['application_status'])
        with self.database.connect() as c:
            self.assertEqual(2,c.execute('SELECT attempt_count FROM memory_learning_jobs WHERE turn_id=?',(turn,)).fetchone()[0])
            self.assertIsNotNone(c.execute('SELECT id FROM memory_observations WHERE id=?',(attempt,)).fetchone())
            self.assertEqual(1,c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])

    def test_malformed_batch_response_is_recorded_without_partial_claims(self):
        from eve_agent.llm import LearningResponseError
        turns=[self.turn(1),self.turn(2)];llm=BatchLLM()
        raw='{"turns":[]} {"extra":"invalid JSON"}'
        def fail(contexts):raise LearningResponseError('invalid JSON',raw)
        llm.analyze_conversation_learning=fail
        pipeline=ProductiveLearningPipeline(self.database,llm)
        results = pipeline.process_batch(turns)
        self.assertEqual(['failed', 'failed'], [result['application_status'] for result in results])
        with self.database.connect() as c:
            self.assertEqual(['failed','failed'],[r[0] for r in c.execute('SELECT status FROM memory_learning_jobs ORDER BY turn_id')])
            self.assertEqual(0,c.execute('SELECT count(*) FROM memory_learning_decisions').fetchone()[0])
            self.assertEqual(0,c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])
            attempts=[json.loads(r[0]) for r in c.execute("SELECT structured_value_json FROM memory_observations WHERE json_extract(metadata_json,'$.kind')='learning_attempt'")]
        self.assertEqual(2,len(attempts))
        self.assertTrue(all(item['proposal']['details']['raw_response']==raw for item in attempts))

    def test_one_preparation_failure_does_not_discard_other_turns(self):
        turns = [self.turn('bad-preparation'), self.turn('valid-preparation')]
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        original = pipeline._model_context

        def prepare(snapshot, candidates, **kwargs):
            if snapshot['turn_id'] == turns[0]:
                raise AttributeError('unsupported result shape')
            return original(snapshot, candidates, **kwargs)

        with patch.object(pipeline, '_model_context', side_effect=prepare):
            results = pipeline.process_batch(turns)
        self.assertEqual(turns, [item['turn_id'] for item in results])
        self.assertEqual(['failed', 'applied'], [item['application_status'] for item in results])
        with self.database.connect() as connection:
            statuses = {row['turn_id']: row['status'] for row in connection.execute(
                'SELECT turn_id,status FROM memory_learning_jobs'
            )}
            self.assertEqual('failed', statuses[turns[0]])
            self.assertEqual('applied', statuses[turns[1]])
            self.assertEqual(1, connection.execute('SELECT count(*) FROM memory_claims').fetchone()[0])

    def test_generation_failure_isolates_bad_turn_without_repeating_whole_batch(self):
        from eve_agent.llm import EmptyModelResponseError, LocalLLMOutputLimitError
        for failure in (EmptyModelResponseError(finish_reason='stop', stream_done=True),
                        LocalLLMOutputLimitError('length', '{')):
            with self.subTest(failure=type(failure).__name__):
                turns = [self.turn(type(failure).__name__ + str(i)) for i in range(4)]
                llm = BatchLLM()
                groups = []

                def analyze(contexts):
                    ids = [context['turn_id'] for context in contexts]
                    groups.append(ids)
                    if turns[0] in ids:
                        raise failure
                    return {'turns': [{'turn_id': context['turn_id'],
                                      'proposal': proposal(context, context['turn_id'])}
                                     for context in contexts]}

                llm.analyze_conversation_learning = analyze
                results = ProductiveLearningPipeline(self.database, llm).process_batch(turns)
                self.assertEqual([4, 2, 1, 1, 2], [len(group) for group in groups])
                self.assertEqual('failed', results[0]['application_status'])
                self.assertTrue(all(result['application_status'] == 'applied' for result in results[1:]))
                self.assertEqual(type(failure).__name__, results[0]['reason_code'])

    def test_context_rejection_splits_complete_batch_without_losing_turns(self):
        turns = [self.turn(index) for index in range(4)]
        llm = ContextBoundBatchLLM(maximum_batch_size=2)
        results = ProductiveLearningPipeline(self.database, llm).process_batch(turns)
        self.assertEqual([4, 2, 2], llm.batch_sizes)
        self.assertEqual(turns, [item['turn_id'] for item in results])
        self.assertEqual(['applied'] * 4, [item['application_status'] for item in results])
        with self.database.connect() as connection:
            self.assertEqual(4, connection.execute(
                "SELECT count(*) FROM memory_learning_jobs WHERE status='applied'"
            ).fetchone()[0])
            self.assertEqual(4, connection.execute('SELECT count(*) FROM memory_claims').fetchone()[0])

    def test_learning_entry_supplies_exact_paths_and_preserves_original_after_reset(self):
        turn = self.turn('indexed-entry')
        llm = WorkingMemoryFallbackLLM()
        pipeline = ProductiveLearningPipeline(self.database, llm)
        context = pipeline._model_context(pipeline._snapshot(turn), [])
        context['tool_events'] = [{'id': 'tool-1', 'tool': 'local_search', 'status': 'returned',
                                  'result': {'large': 'UNABRIDGED-SOURCE-' * 10000}}]
        rounds = []

        def request(messages, tools, *args, **kwargs):
            entry = json.loads(messages[1]['content'])
            rounds.append(entry)
            self.assertEqual(entry['inline']['user_message'], context['user_message'])
            self.assertEqual(entry['tool_index'][0]['pointer'], '/text/turns/0/tool_events/0')
            self.assertLess(len(messages[1]['content']), 14000)
            if len(rounds) == 1:
                return {'content': '', 'tool_calls': [{'id': 'reset', 'name': 'working_memory__reset_context', 'arguments': {}}]}
            value = proposal(context, 'entry')
            value.update(decision_type='no_persist', memory_worthy=False, claim=None, evidence=[])
            return {'content': json.dumps({'turns': [{'turn_id': turn, 'proposal': value}]}), 'tool_calls': []}

        llm.request_tool_turn = request
        with patch.object(pipeline, '_model_context', return_value=context):
            result = pipeline.process_batch([turn])[0]
        self.assertEqual(result['decision_type'], 'no_persist')
        self.assertEqual(len(rounds), 2)
        self.assertEqual(rounds[0]['original_reference'], rounds[1]['original_reference'])
        from eve_agent.working_memory import WorkingMemoryStore
        with self.database.connect() as c:
            wid = c.execute('SELECT workspace_id FROM memory_work_objects WHERE id=?',
                            (rounds[0]['original_reference'],)).fetchone()[0]
        original = WorkingMemoryStore(self.database).value(wid, rounds[0]['original_reference'])
        self.assertEqual(original['text']['turns'][0], context)

    def test_repeated_working_memory_reads_stop_with_persisted_diagnosis(self):
        turn = self.turn('stalled-navigation')
        llm = WorkingMemoryFallbackLLM()
        seen = []

        def request(messages, tools, *args, **kwargs):
            entry = json.loads(messages[1]['content'])
            seen.append(messages)
            return {'content': '', 'tool_calls': [{'id': 'read-' + str(len(seen)),
                'name': 'working_memory__read', 'arguments': {
                    'reference': entry['original_reference'], 'pointer': '/text/turns/0/user_message'}}]}

        llm.request_tool_turn = request
        result = ProductiveLearningPipeline(self.database, llm).process_batch([turn])[0]
        self.assertEqual(result['application_status'], 'failed')
        self.assertEqual(result['reason_code'], 'LearningProgressError')
        self.assertEqual(result['details']['response_evidence']['reason'], 'learning_navigation_stalled')
        self.assertEqual(len(seen), 7)
        with self.database.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM memory_work_turns').fetchone()[0], 'failed')
            self.assertEqual(c.execute('SELECT count(*) FROM memory_claims').fetchone()[0], 0)
            results = [json.loads(row[0]) for row in c.execute(
                "SELECT v.structured_value_json FROM memory_work_calls c JOIN memory_work_objects o "
                "ON o.id=c.result_id JOIN memory_observations v ON v.id=o.observation_id")]
        self.assertTrue(any(item.get('learning_progress', {}).get('new_material') is False for item in results))

    def test_novel_selections_still_have_a_finite_model_round_budget(self):
        turn = self.turn('round-budget')
        llm = WorkingMemoryFallbackLLM()
        # This test exercises the model-round guard. Context compaction has its
        # own tests and must not replace the fixture entry midway through this one.
        llm.context_budget = lambda messages, tools: {'fits': True, 'input_tokens': 0, 'context_tokens': 100000}
        rounds = []

        def request(messages, tools, *args, **kwargs):
            entry = json.loads(messages[1]['content'])
            rounds.append(1)
            return {'content': '', 'tool_calls': [{'id': str(len(rounds)), 'name': 'working_memory__read',
                'arguments': {'reference': entry['original_reference'],
                              'pointer': '/text/turns/0/user_message/content',
                              'offset': len(rounds) - 1, 'limit': 1}}]}

        llm.request_tool_turn = request
        result = ProductiveLearningPipeline(self.database, llm).process_batch([turn])[0]
        self.assertEqual(result['reason_code'], 'LearningProgressError')
        self.assertEqual(result['details']['response_evidence']['reason'], 'learning_model_round_budget')
        self.assertEqual(len(rounds), 24)

    def test_working_memory_inference_is_cancellable_and_keeps_job_pending(self):
        turn = self.turn('cancel-working-memory')
        llm = WorkingMemoryFallbackLLM()
        entered = threading.Event()
        bound = []

        @contextmanager
        def cancellable(cancellation):
            bound.append(cancellation)
            try:
                yield
            finally:
                bound.pop()

        def request(*args, **kwargs):
            self.assertTrue(bound)
            entered.set()
            while True:
                bound[-1].checkpoint()
                time.sleep(.005)

        llm.cancellable = cancellable
        llm.request_tool_turn = request
        pipeline = ProductiveLearningPipeline(self.database, llm)
        caught = []
        worker = threading.Thread(target=lambda: self._capture(caught, pipeline.process_batch, [turn]))
        worker.start()
        self.assertTrue(entered.wait(2))
        pipeline.prioritize_interactive_turn()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertIsInstance(caught[0], ShadowLearningCancelled)
        with self.database.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM memory_learning_jobs').fetchone()[0], 'pending')
            self.assertEqual(c.execute('SELECT status FROM memory_work_turns').fetchone()[0], 'cancelled')

    def test_single_oversized_turn_is_paged_through_working_memory(self):
        turn = self.turn('oversized-working-memory')
        llm = WorkingMemoryFallbackLLM()
        pipeline = ProductiveLearningPipeline(self.database, llm)
        snapshot = pipeline._snapshot(turn)
        context = pipeline._model_context(snapshot, [])
        context['large_material'] = {'content': 'x' * 10_000_000}
        with patch.object(pipeline, '_model_context', return_value=context):
            result = pipeline.process_batch([turn])[0]
        self.assertEqual('applied', result['application_status'])
        self.assertEqual(0, llm.direct_calls)
        self.assertEqual(2, llm.tool_rounds)
        with self.database.connect() as connection:
            self.assertGreater(connection.execute(
                "SELECT count(*) FROM memory_work_objects WHERE kind='user_request'"
            ).fetchone()[0], 0)
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM memory_workspaces WHERE retention_class='temporary_learning'"
            ).fetchone()[0])
            self.assertEqual(0, connection.execute(
                """SELECT count(*) FROM memory_work_bindings b
                   JOIN memory_workspaces w ON w.id=b.workspace_id
                   WHERE w.retention_class='temporary_learning'"""
            ).fetchone()[0])
            self.assertEqual('no_persist', connection.execute(
                'SELECT status FROM memory_learning_jobs WHERE turn_id=?', (turn,)
            ).fetchone()[0])

    def test_failed_working_memory_turn_does_not_discard_other_turns(self):
        turns = [self.turn('bad-working-memory'), self.turn('valid-working-memory')]
        llm = ContextBoundBatchLLM(maximum_batch_size=0)
        pipeline = ProductiveLearningPipeline(self.database, llm)

        def working_memory(context, cancellation):
            if context['turn_id'] == turns[0]:
                raise RuntimeError('unreadable work object')
            value = proposal(context, 'working-memory-success')
            return {'turns': [{'turn_id': context['turn_id'], 'proposal': value}]}

        with patch.object(pipeline, '_analyze_context_via_working_memory', side_effect=working_memory):
            results = pipeline.process_batch(turns)
        self.assertEqual(turns, [item['turn_id'] for item in results])
        self.assertEqual(['failed', 'applied'], [item['application_status'] for item in results])
        with self.database.connect() as connection:
            statuses = dict(connection.execute(
                'SELECT turn_id,status FROM memory_learning_jobs'
            ).fetchall())
        self.assertEqual('failed', statuses[turns[0]])
        self.assertEqual('applied', statuses[turns[1]])

    def test_forged_source_id_remains_rejected(self):
        turn=self.turn(1);llm=BatchLLM()
        def analyze(contexts):
            item=proposal(contexts[0],'forged')
            item['evidence'][0]['source_id']='not-published'
            return {'turns':[{'turn_id':turn,'proposal':item}]}
        llm.analyze_conversation_learning=analyze
        pipeline=ProductiveLearningPipeline(self.database,llm)
        result=pipeline.process_batch([turn])[0]
        self.assertEqual('failed',result['application_status'])
        self.assertEqual('invented_message_reference',result['reason_code'])
        with self.database.connect() as c:self.assertEqual(0,c.execute('SELECT count(*) FROM memory_claims').fetchone()[0])

    def test_legacy_rejected_no_persist_is_requeued_without_rewriting_decision(self):
        turn=self.turn(1);pipeline=ProductiveLearningPipeline(self.database,BatchLLM())
        pipeline.accept_turn(turn)
        with self.database.connect() as c:
            c.execute("INSERT INTO memory_learning_decisions(id,decision_type,method,rationale,metadata_json,created_at) VALUES ('old','no_persist','llm_batch','non_evidence_source',?, '2026')",
                      (json.dumps({'proposal_decision_type':'undetermined','reason_code':'non_evidence_source'}),))
            c.execute("UPDATE memory_learning_jobs SET status='no_persist',decision_id='old' WHERE turn_id=?",(turn,))
        pipeline.retry_turn(turn)
        pipeline.process_batch([turn])
        with self.database.connect() as c:
            self.assertEqual('non_evidence_source',c.execute("SELECT rationale FROM memory_learning_decisions WHERE id='old'").fetchone()[0])
            self.assertEqual('applied',c.execute('SELECT status FROM memory_learning_jobs WHERE turn_id=?',(turn,)).fetchone()[0])
            self.assertEqual(1,c.execute("SELECT count(*) FROM audit_events WHERE event_type='learning_retry'").fetchone()[0])
        with self.assertRaises(ValueError):pipeline.retry_turn(turn)

    def test_intentional_no_persist_stays_terminal_and_is_not_reclassified(self):
        turn=self.turn(1);llm=BatchLLM()
        llm.analyze_conversation_learning=lambda contexts:{'turns':[{'turn_id':turn,'proposal':{
            'decision_type':'no_persist','memory_worthy':False,'evidence':[],'reason_code':'transient_request'}}]}
        pipeline=ProductiveLearningPipeline(self.database,llm);result=pipeline.process_batch([turn])[0]
        self.assertEqual('applied',result['application_status'])
        with self.database.connect() as c:self.assertEqual('no_persist',c.execute('SELECT status FROM memory_learning_jobs').fetchone()[0])
        with self.assertRaises(ValueError):pipeline.retry_turn(turn)

    def test_status_counts_only_applied_turns_with_persisted_evidence_as_learned(self):
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        valid = self.turn('evidenced')
        pipeline.accept_turn(valid)
        pipeline.process_batch([valid])
        inconsistent = self.turn('missing-evidence')
        pipeline.accept_turn(inconsistent)
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE memory_learning_jobs SET status='applied' WHERE turn_id=?", (inconsistent,),
            )
        coordinator = ConversationLearningCoordinator(
            self.database, pipeline,
            {'enabled': False, 'idle_delay_seconds': 3600, 'batch_size': 4}, autostart=False,
        )
        status = coordinator.status()
        self.assertEqual(1, status['learned'])
        self.assertEqual(2, status['applied'])
        self.assertEqual(1, status['applied_without_evidence'])
        self.assertEqual(1, status['evidence_records'])
        self.assertEqual(1, status['evidenced_claims'])

    def test_learning_job_details_expose_persisted_turn_decision_claim_and_evidence(self):
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        turn = self.turn('visible-result')
        pipeline.accept_turn(turn)
        pipeline.process_batch([turn])

        other_turn = self.turn('unrelated-execution')
        with self.database.connect() as connection:
            for source_turn, event_id, entity in [(turn, 'trace-own', 'light.hall'),
                                                   (other_turn, 'trace-other', 'light.kitchen')]:
                source = connection.execute('SELECT * FROM turns WHERE id=?', (source_turn,)).fetchone()
                connection.execute(
                    'INSERT INTO conversation_tool_events '
                    '(id,conversation_id,message_id,ordinal,tool,status,summary,input_json,result_json,created_at) '
                    'VALUES (?,?,?,0,?,?,?,?,?,?)',
                    (event_id, source['conversation_id'], source['assistant_message_id'],
                     'home_assistant', 'success', 'Licht ausschalten',
                     json.dumps({'entity_id': entity}), json.dumps({'status': 'success'}), source['created_at']),
                )

        page = pipeline.learning_jobs('evidenced', limit=10)

        self.assertEqual(1, page['total'])
        self.assertFalse(page['page']['has_more'])
        item = page['items'][0]
        self.assertEqual(turn, item['turn_id'])
        self.assertEqual('applied', item['status'])
        self.assertEqual('create_active', item['decision_type'])
        self.assertEqual('Dauerhafte Information visible-result', item['user_content'])
        self.assertEqual(1, item['evidence_count'])
        self.assertEqual(1, len(item['claims']))
        self.assertEqual('Dauerhafte Information 1', item['claims'][0]['display_text'])
        self.assertEqual(turn, item['claims'][0]['evidence'][0]['source_turn_id'])
        self.assertEqual(['trace-own'], [event['id'] for event in item['tool_events']])
        self.assertEqual({'entity_id': 'light.hall'}, item['tool_events'][0]['input'])
        self.assertEqual({'status': 'success'}, item['tool_events'][0]['result'])
        self.assertEqual([], item['recognized_actions'])
        self.assertEqual({'execution': 'unknown', 'learning': 'yes'}, item['llm_usage'])
        for origin, expected in [('native_tool', 'yes'), ('semantic_replay', 'no')]:
            with self.database.connect() as connection:
                connection.execute('UPDATE turns SET knowledge_flow_json=? WHERE id=?',
                                   (json.dumps({'stages': [{'kind': 'turn_state', 'details': {
                                       'decision_origin': origin, 'semantic_reuse': 'composition'}}]}), turn))
            refreshed = pipeline.learning_jobs('evidenced')['items'][0]
            self.assertEqual(expected, refreshed['llm_usage']['execution'])
            self.assertEqual('composition' if origin == 'semantic_replay' else None, refreshed['execution_path'])

    def test_learning_job_details_distinguish_no_persist_and_reject_unknown_status(self):
        turn = self.turn('transient')
        llm = BatchLLM()
        llm.analyze_conversation_learning = lambda contexts: {'turns': [{'turn_id': turn, 'proposal': {
            'decision_type': 'no_persist', 'memory_worthy': False, 'evidence': [],
            'reason_code': 'transient_request',
        }}]}
        pipeline = ProductiveLearningPipeline(self.database, llm)
        pipeline.accept_turn(turn)
        pipeline.process_batch([turn])

        page = pipeline.learning_jobs('no_persist')
        self.assertEqual(1, page['total'])
        self.assertEqual([], page['items'][0]['claims'])
        self.assertEqual('transient_request', page['items'][0]['rationale'])
        with self.assertRaises(ValueError):
            pipeline.learning_jobs('made-up')

    def test_coordinator_completes_queue_while_exposing_rejected_turn(self):
        turn=self.turn(1);llm=BatchLLM()
        llm.analyze_conversation_learning=lambda contexts:{'turns':[{'turn_id':turn,'proposal':{
            'decision_type':'create_active','evidence':[{'source_type':'assistant_output','source_id':'invented'}]}}]}
        pipeline=ProductiveLearningPipeline(self.database,llm)
        coordinator=ConversationLearningCoordinator(self.database,pipeline,{'enabled':True,'idle_delay_seconds':3600,'batch_size':4})
        self.addCleanup(coordinator.close);coordinator.accept_turn(turn);coordinator.run_now()
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            status=coordinator.status()
            if status['status']=='completed':break
            time.sleep(.01)
        self.assertEqual('completed',status['status'])
        self.assertEqual('non_evidence_source',status['last_error'])
        self.assertEqual(1,status['failed'])

    def test_rejected_turn_does_not_block_later_pending_turn(self):
        turns = [self.turn('rejected'), self.turn('valid-after-rejection')]
        calls = []

        def analyze(contexts):
            calls.append([context['turn_id'] for context in contexts])
            context = contexts[0]
            item = proposal(context, context['turn_id'])
            if context['turn_id'] == turns[0]:
                item['evidence'][0]['source_type'] = 'assistant_output'
            return {'turns': [{'turn_id': context['turn_id'], 'proposal': item}]}

        pipeline = ProductiveLearningPipeline(
            self.database, SimpleNamespace(model='continue-after-rejection',
                                           analyze_conversation_learning=analyze),
        )
        coordinator = ConversationLearningCoordinator(
            self.database, pipeline,
            {'enabled': True, 'idle_delay_seconds': 3600, 'batch_size': 1},
        )
        self.addCleanup(coordinator.close)
        for turn in turns:
            coordinator.accept_turn(turn)
        coordinator.run_now()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = coordinator.status()
            if (status['pending'] == 0 and status['running'] == 0
                    and status['status'] == 'completed'):
                break
            time.sleep(.01)
        self.assertEqual(0, status['pending'])
        self.assertEqual(1, status['failed'])
        self.assertEqual(1, status['learned'])
        self.assertEqual('completed', status['status'])
        self.assertIn([turns[1]], calls)

    def test_coordinator_does_not_hot_loop_after_preparation_error(self):
        turn = self.turn('preparation-error')
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        coordinator = ConversationLearningCoordinator(
            self.database, pipeline,
            {'enabled': True, 'idle_delay_seconds': 3600, 'batch_size': 4},
        )
        self.addCleanup(coordinator.close)
        coordinator.accept_turn(turn)
        with patch.object(pipeline, 'process_batch', side_effect=AttributeError('bad result shape')) as run:
            coordinator.run_now()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                status = coordinator.status()
                if status['status'] == 'failed':
                    break
                time.sleep(.01)
            time.sleep(.08)
        self.assertEqual('failed', status['status'])
        self.assertEqual('AttributeError', status['last_error'])
        self.assertEqual(1, run.call_count)
        self.assertEqual(1, status['pending'])

    def test_batch_receives_failure_correction_and_observed_result(self):
        self.failure_retry()
        llm=BatchLLM()
        pipeline=ProductiveLearningPipeline(self.database,llm)
        contexts=[]
        original=llm.analyze_conversation_learning
        llm.analyze_conversation_learning=lambda items: (contexts.extend(items),original(items))[1]
        pipeline.process_batch(["retry-one"])
        episode=contexts[0]["failure_episodes"][0]
        self.assertEqual("failed-one",episode["failure"]["turn_id"])
        self.assertTrue(episode["explicit_retry"])
        self.assertEqual("Nutze das strukturierte Memory-Inventar",episode["correction"])
        self.assertEqual("completed",contexts[0]["tool_events"][0]["status"])
        self.assertEqual(16,contexts[0]["tool_events"][0]["observed_outcome"]["result_count"])
        with self.database.connect() as db:
            self.assertEqual(["candidate"],[row[0] for row in db.execute("SELECT lifecycle FROM memory_claims")])

    def test_user_correction_is_stored_as_instruction_not_confirmed_cause(self):
        correction="Nutze das strukturierte Memory-Inventar"
        self.failure_retry(correction)
        llm=SimpleNamespace(model="test")
        def analyze(contexts):
            item=proposal(contexts[0],"correction")
            item["claim"]["display_text"]=correction
            return {"turns":[{"turn_id":"retry-one","proposal":item}]}
        llm.analyze_conversation_learning=analyze
        ProductiveLearningPipeline(self.database,llm).process_batch(["retry-one"])
        with self.database.connect() as db:
            row=db.execute("SELECT lifecycle,display_text,payload_json FROM memory_claims").fetchone()
        self.assertEqual("active",row[0])
        self.assertIn("keine bestätigte Fehlerursache",row[1])
        self.assertEqual("user_instruction",json.loads(row[2])["epistemic_kind"])

    def test_unknown_cause_cannot_support_existing_active_fact(self):
        self.failure_retry()
        pipeline=ProductiveLearningPipeline(self.database,BatchLLM())
        snapshot=pipeline._snapshot("retry-one")
        normalized={"decision_type":"append_supporting_evidence","claim":None}
        with patch.object(pipeline,"_validate_proposal_contract",return_value=normalized):
            result=pipeline._validate_proposal({},snapshot,[])
        self.assertEqual("undetermined",result["decision_type"])
        self.assertEqual("failure_lesson_requires_independent_evidence",result["reason_code"])

    def test_guessed_cause_is_never_an_active_fact_even_with_user_authority(self):
        self.failure_retry()
        llm=SimpleNamespace(model="guess-test")
        def analyze(contexts):
            item=proposal(contexts[0],"guessed-cause")
            item["claim"]["display_text"]="EVE hat keine Administratorrechte"
            return {"turns":[{"turn_id":"retry-one","proposal":item}]}
        llm.analyze_conversation_learning=analyze
        ProductiveLearningPipeline(self.database,llm).process_batch(["retry-one"])
        with self.database.connect() as db:
            self.assertEqual("candidate",db.execute("SELECT lifecycle FROM memory_claims").fetchone()[0])

    def test_failure_links_cannot_cross_conversation_boundaries(self):
        self.failure_retry()
        other=self.conversations.create("Other")["id"]
        with self.assertRaises(ValueError):
            self.conversations.record_retry(other,"other-turn","failed-one","correction")

    def test_multiple_turns_use_one_model_call(self):
        llm = BatchLLM()
        pipeline = ProductiveLearningPipeline(self.database, llm)
        turns = [self.turn(1), self.turn(2)]

        results = pipeline.process_batch(turns)

        self.assertEqual(1, llm.calls)
        self.assertEqual(turns, [item["turn_id"] for item in results])
        with self.database.connect() as connection:
            self.assertEqual(2, connection.execute("SELECT count(*) FROM memory_claims").fetchone()[0])
            self.assertEqual(
                ["applied", "applied"],
                [row[0] for row in connection.execute(
                    "SELECT status FROM memory_learning_jobs ORDER BY turn_id"
                ).fetchall()],
            )

    def test_interactive_priority_cancels_batch_without_partial_claims(self):
        llm = BatchLLM(block=True)
        pipeline = ProductiveLearningPipeline(self.database, llm)
        turns = [self.turn(1), self.turn(2)]
        caught = []

        worker = threading.Thread(target=lambda: self._capture(caught, pipeline.process_batch, turns))
        worker.start()
        self.assertTrue(llm.entered.wait(1))
        pipeline.prioritize_interactive_turn()
        worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(1, len(caught))
        self.assertIsInstance(caught[0], ShadowLearningCancelled)
        with self.database.connect() as connection:
            self.assertEqual(0, connection.execute("SELECT count(*) FROM memory_claims").fetchone()[0])
            self.assertEqual(
                ["pending", "pending"],
                [row[0] for row in connection.execute(
                    "SELECT status FROM memory_learning_jobs ORDER BY turn_id"
                ).fetchall()],
            )

    def test_coordinator_commits_first_turn_before_second_and_preserves_it_on_pause(self):
        llm = BatchLLM()
        original = llm.analyze_conversation_learning
        second_entered = threading.Event()

        def analyze(contexts):
            if llm.calls:
                llm.block = True
                second_entered.set()
            return original(contexts)

        llm.analyze_conversation_learning = analyze
        pipeline = ProductiveLearningPipeline(self.database, llm)
        coordinator = ConversationLearningCoordinator(self.database, pipeline,
            {'enabled': True, 'idle_delay_seconds': 3600, 'batch_size': 2})
        self.addCleanup(coordinator.close)
        first, second = self.turn('first-commit'), self.turn('second-pause')
        coordinator.accept_turn(first)
        coordinator.accept_turn(second)
        coordinator.run_now()
        self.assertTrue(second_entered.wait(2))
        with self.database.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM memory_learning_jobs WHERE turn_id=?', (first,)).fetchone()[0], 'applied')
        coordinator.pause()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with self.database.connect() as c:
                status = c.execute('SELECT status FROM memory_learning_jobs WHERE turn_id=?', (second,)).fetchone()[0]
            if status == 'pending':
                break
            time.sleep(.01)
        self.assertEqual(status, 'pending')
        with self.database.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM memory_learning_jobs WHERE turn_id=?', (first,)).fetchone()[0], 'applied')

    def test_coordinator_advances_after_navigation_stalls(self):
        first, second = self.turn('stalled-first'), self.turn('next-success')
        llm = WorkingMemoryFallbackLLM()

        def request(messages, tools, *args, **kwargs):
            entry = json.loads(messages[1]['content'])
            if entry['turn_id'] == first:
                return {'content': '', 'tool_calls': [{'name': 'working_memory__status', 'arguments': {}}]}
            context = {'user_message': entry['inline']['user_message']}
            value = proposal(context, 'next-success')
            return {'content': json.dumps({'turns': [{'turn_id': second, 'proposal': value}]}), 'tool_calls': []}

        llm.request_tool_turn = request
        pipeline = ProductiveLearningPipeline(self.database, llm)
        coordinator = ConversationLearningCoordinator(self.database, pipeline,
            {'enabled': True, 'idle_delay_seconds': 3600, 'batch_size': 2})
        self.addCleanup(coordinator.close)
        coordinator.accept_turn(first)
        coordinator.accept_turn(second)
        coordinator.run_now()
        deadline = time.monotonic() + 3
        jobs = {}
        while time.monotonic() < deadline:
            with self.database.connect() as c:
                jobs = dict(c.execute('SELECT turn_id,status FROM memory_learning_jobs'))
            if jobs.get(second) == 'applied':
                break
            time.sleep(.01)
        self.assertEqual(jobs, {first: 'failed', second: 'applied'})

    def test_coordinator_pause_and_resume_are_persistent(self):
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        coordinator = ConversationLearningCoordinator(
            self.database, pipeline,
            {"enabled": True, "idle_delay_seconds": 30, "batch_size": 4},
            autostart=False,
        )
        self.addCleanup(coordinator.close)
        coordinator.accept_turn(self.turn(1))
        self.assertEqual(1, coordinator.status()["pending"])
        self.assertEqual("paused", coordinator.pause()["status"])
        self.assertTrue(coordinator.status()["pause_requested"])
        resumed = coordinator.resume()
        self.assertEqual("waiting", resumed["status"])
        self.assertFalse(resumed["pause_requested"])

    def test_run_now_processes_pending_turn_without_waiting_for_idle_delay(self):
        llm = BatchLLM()
        pipeline = ProductiveLearningPipeline(self.database, llm)
        coordinator = ConversationLearningCoordinator(
            self.database, pipeline,
            {"enabled": True, "idle_delay_seconds": 3600, "batch_size": 4},
        )
        self.addCleanup(coordinator.close)
        coordinator.accept_turn(self.turn(1))

        coordinator.run_now()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            current = coordinator.status()
            if current["learned"] == 1 and current["status"] == "completed":
                break
            time.sleep(.01)

        status = coordinator.status()
        self.assertEqual(1, llm.calls)
        self.assertEqual(1, status["learned"])
        self.assertEqual(0, status["pending"])
        self.assertEqual("completed", status["status"])

    def test_run_now_leaves_historical_failures_untouched(self):
        llm = BatchLLM()
        pipeline = ProductiveLearningPipeline(self.database, llm)
        failed = self.turn('historical-failure')
        pending = self.turn('new-pending')
        pipeline.accept_turn(failed)
        pipeline.accept_turn(pending)
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE memory_learning_jobs SET status='failed',error_class='old_error' WHERE turn_id=?",
                (failed,),
            )
        coordinator = ConversationLearningCoordinator(
            self.database, pipeline,
            {"enabled": True, "idle_delay_seconds": 3600, "batch_size": 4},
        )
        self.addCleanup(coordinator.close)
        coordinator.run_now()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            status = coordinator.status()
            if status['status'] == 'completed':
                break
            time.sleep(.01)
        with self.database.connect() as connection:
            jobs = {row['turn_id']: row['status'] for row in connection.execute(
                'SELECT turn_id,status FROM memory_learning_jobs'
            )}
        self.assertEqual('failed', jobs[failed])
        self.assertEqual('applied', jobs[pending])
        self.assertEqual(1, llm.calls)

    def test_failed_jobs_require_explicit_retry(self):
        pipeline = ProductiveLearningPipeline(self.database, BatchLLM())
        turn = self.turn('retry-explicitly')
        pipeline.accept_turn(turn)
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE memory_learning_jobs SET status='failed',error_class='old_error' WHERE turn_id=?",
                (turn,),
            )
        coordinator = ConversationLearningCoordinator(
            self.database, pipeline,
            {"enabled": True, "idle_delay_seconds": 3600, "batch_size": 4}, autostart=False,
        )
        self.addCleanup(coordinator.close)
        status = coordinator.retry_failed()
        self.assertEqual(1, status['requeued_failed'])
        self.assertEqual(1, status['pending'])

    @staticmethod
    def _capture(errors, function, *args):
        try:
            function(*args)
        except Exception as exc:
            errors.append(exc)


if __name__ == "__main__":
    unittest.main()
