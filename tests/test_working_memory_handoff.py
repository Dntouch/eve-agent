"""State handoff and recovery invariants; no live providers or model server."""
import io
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from eve_agent.agent import EveAgent
from eve_agent.backend_turns import TurnCancelled
from eve_agent.llm import EmptyModelResponseError, LocalLLMOutputLimitError, OpenAICompatibleLLM
from eve_agent.memory_compiler import MemoryCompiler
from eve_agent.memory_v2 import MemoryV2Runtime
from eve_agent.minimal import CORE_PROMPT, NativeToolRuntime
from eve_agent.state import StateBus
from eve_agent.storage import ConversationStore, EveDatabase
from eve_agent.working_context import WorkingMemorySession


def call(name, arguments):
    return {'content': '', 'tool_calls': [{'id': name, 'name': name, 'arguments': arguments}]}


class HandoffTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = EveDatabase(self.root / 'eve.db')
        self.conversations = ConversationStore(self.db)
        self.llm = SimpleNamespace(request_tool_turn=Mock(), generation_max_tokens=None, use_server_limits=True)
        self.agent = EveAgent('EVE', MemoryV2Runtime(self.db, MemoryCompiler(self.db)), self.llm,
                              StateBus(self.root / 'runtime'), conversations=self.conversations)
        self.agent.conversation_id = self.conversations.create()['id']
        self.runtime = NativeToolRuntime(self.agent)

    def session(self):
        return WorkingMemorySession(self.agent, 'Nur analysieren, nichts verändern.', [], 'trace')

    def checkpoint(self, frames, tools):
        control = json.loads(frames[-1]['content'])['checkpoint_boundary']
        self.assertEqual([{'role': 'system', 'content': CORE_PROMPT}],
                         [m for m in frames if m['role'] == 'system'])
        self.assertEqual(['working_memory__checkpoint'], [t['function']['name'] for t in tools])
        result = call('working_memory__checkpoint', {'expected_revision': control['expected_revision'],
            'state': {'goal': 'Analyse', 'constraints': ['Keine Änderungen'],
                      'findings': ['Provider liefert bereits Bilder'], 'open_questions': ['Direkter URL-Abruf?'],
                      'next_step': 'Veröffentlichten Vertrag prüfen'},
            'references': [control['request_reference']]})
        if control['reason'] == 'turn_complete':
            result['tool_calls'][0]['arguments']['state']['completed_answer'] = frames[-2]['content']
        return result

    def test_boundary_saves_model_state_and_no_provider_is_replayed(self):
        self.llm.request_working_checkpoint = Mock(side_effect=self.checkpoint)
        self.llm.request_tool_turn.side_effect = [
            call('eve__load_capabilities', {'capabilities': ['local_files', 'working_memory']}),
            call('local_files__fetch', {}),
            call('working_memory__reset_context', {}),
            {'content': 'Bericht und Plan.', 'tool_calls': []}]
        provider = Mock(return_value={'file': 'web_tools.py', 'content': 'Bilddaten sind bereits vorhanden.'})
        self.agent.local_files = SimpleNamespace(minimal_contract=lambda: {'description': 'Testbestand',
            'operations': {'fetch': {'effect': 'read', 'parameters_schema': {'type': 'object', 'properties': {}}}}},
            execute_operation=provider)
        answer = self.runtime.respond('Nur analysieren, nichts verändern.')
        self.assertEqual('Bericht und Plan.', answer)
        self.assertEqual(1, provider.call_count)
        self.assertEqual(1, self.llm.request_working_checkpoint.call_count)
        session = self.runtime.working_session
        entry = session.entry()
        self.assertEqual(1, entry['revision'])
        with self.db.connect() as c:
            outcome = c.execute('SELECT answer_id FROM memory_work_turns WHERE id=?', (session.turn_id,)).fetchone()[0]
        self.assertEqual(answer, session.store.value(session.workspace_id, outcome))
        resumed = WorkingMemorySession(self.agent, 'Fortsetzen', [], 'after-completion').entry()
        self.assertEqual(outcome, resumed['latest_turn_outcome']['model_answer_reference'])
        self.assertFalse(entry['checkpoint_is_verified_fact'])
        fresh = self.llm.request_tool_turn.call_args.args[0]
        data = json.loads(fresh[2]['content'].split(': ', 1)[1])
        self.assertEqual(['Keine Änderungen'], data['model_authored_checkpoint']['constraints'])
        self.assertEqual('saved', data['checkpoint_capture']['status'])
        self.assertIn('execution_delta_reference', data)
        checkpoint_frames = self.llm.request_working_checkpoint.call_args_list[0].args[0]
        self.assertIn('Bilddaten sind bereits vorhanden.', json.dumps(checkpoint_frames))
        self.assertEqual([], session.store.manifest(session.workspace_id)['uncertain_calls'])

    def test_capacity_checkpoint_preserves_large_original_without_copying_it(self):
        session = self.session()
        self.llm.request_working_checkpoint = Mock(side_effect=self.checkpoint)
        def measure(frames, tools):
            size = len(json.dumps([frames, tools]))
            return {'fits': size < 12000, 'input_tokens': size, 'context_tokens': 12000}
        self.llm.context_budget = measure
        original = {'raw': 'unchanged' * 20000}
        descriptor = session.store.put(session.workspace_id, original, kind='tool_result')
        messages = [{'role': 'system', 'content': CORE_PROMPT}, {'role': 'user', 'content': session.input['text']},
            {'role': 'assistant', 'tool_calls': [{'id': 'fetch', 'type': 'function',
                'function': {'name': 'fixture__fetch', 'arguments': '{}'}}], 'content': ''},
            {'role': 'tool', 'tool_call_id': 'fetch', 'content': json.dumps(original)}]
        session.tool_frame(messages[-1], descriptor)
        session.prepare(messages, [], {}, {'loaded_capabilities': []}, CORE_PROMPT, self.runtime._published_tools)
        self.assertEqual(original, session.store.value(session.workspace_id, descriptor['reference']))
        self.assertEqual(0, self.llm.request_working_checkpoint.call_count)
        self.assertTrue(measure(messages, [])['fits'])
        self.assertNotIn('unchanged' * 100, json.dumps(messages))
        self.assertIn(descriptor['reference'], json.dumps(messages))
        # A real handoff still captures a model checkpoint.
        session.capture_checkpoint(messages, CORE_PROMPT, 'capacity')
        self.assertEqual(1, self.llm.request_working_checkpoint.call_count)

    def test_bad_checkpoint_never_overwrites_previous_state_or_leaves_uncertain_call(self):
        for failure in ('empty', 'foreign', 'stale', 'wrong_tool'):
            with self.subTest(failure=failure):
                session = self.session()
                prior = session.store.checkpoint(session.workspace_id, {'known': 'old'},
                    expected_revision=session.entry()['revision'], turn_id=session.turn_id)['checkpoint']['reference']
                other = session.store.create()
                foreign = session.store.put(other, {'private': True})['reference']
                def bad(frames, tools):
                    result = self.checkpoint(frames, tools)
                    params = result['tool_calls'][0]['arguments']
                    if failure == 'empty': params['state'] = {}
                    if failure == 'foreign': params['references'] = [foreign]
                    if failure == 'stale': params['expected_revision'] -= 1
                    if failure == 'wrong_tool': result['tool_calls'][0]['name'] = 'shell__execute'
                    return result
                self.llm.request_working_checkpoint = Mock(side_effect=bad)
                session.capture_checkpoint([{'role': 'system', 'content': CORE_PROMPT}], CORE_PROMPT, 'capacity')
                self.assertEqual(prior, session.entry()['checkpoint_reference'])
                self.assertEqual({'known': 'old'}, session.store.value(session.workspace_id, prior))
                self.assertEqual('failed', session.checkpoint_capture['status'])
                self.assertEqual([], session.store.manifest(session.workspace_id)['uncertain_calls'])

    def test_cancellation_is_not_swallowed_by_checkpoint_capture(self):
        session = self.session()
        self.llm.request_working_checkpoint = Mock(side_effect=TurnCancelled('cancelled'))
        with self.assertRaises(TurnCancelled):
            session.capture_checkpoint([{'role': 'system', 'content': CORE_PROMPT}], CORE_PROMPT, 'capacity')
        self.assertIsNone(session.entry()['checkpoint_reference'])

    def test_checkpoint_accepts_existing_historical_source_outside_current_frames(self):
        session = self.session()
        source = session.store.put(session.workspace_id, {'original': 'past observation'})
        def checkpoint(frames, tools):
            response = self.checkpoint(frames, tools)
            response['tool_calls'][0]['arguments']['references'].append(source['observation_id'])
            return response
        self.llm.request_working_checkpoint = Mock(side_effect=checkpoint)
        session.capture_checkpoint([{'role': 'system', 'content': CORE_PROMPT}], CORE_PROMPT, 'capacity')
        self.assertEqual('saved', session.checkpoint_capture['status'])
        reference = session.entry()['checkpoint_reference']
        with self.db.connect() as c:
            links = [r[0] for r in c.execute('SELECT to_id FROM memory_work_links WHERE from_id=?', (reference,))]
        self.assertIn(source['reference'], links)

    def test_rereading_receipts_does_not_retrigger_checkpoint_or_context_recovery(self):
        session = self.session()
        source = session.store.put(session.workspace_id, {'stdout': 'original failure text'})
        def read(reference, pointer, call_id):
            parameters = {'reference': reference, 'pointer': pointer}
            result = session.store.read(session.workspace_id, **parameters)
            identifier = session.store.start_call(session.workspace_id, session.turn_id, call_id,
                                                 'working_memory', 'read', 'read', parameters)
            session.store.dispatch_call(session.workspace_id, identifier)
            return session.store.finish_call(session.workspace_id, session.turn_id, identifier, result)
        receipt = read(source['reference'], '/stdout', 'first-read')
        signature = session._material_signature()
        self.llm.request_working_checkpoint = Mock(side_effect=self.checkpoint)
        session.capture_checkpoint([{'role': 'system', 'content': CORE_PROMPT}], CORE_PROMPT, 'capacity')
        read(receipt['reference'], '/content', 'second-read')
        self.assertEqual(signature, session._material_signature())
        session.capture_checkpoint([{'role': 'system', 'content': CORE_PROMPT}], CORE_PROMPT, 'capacity')
        self.assertEqual(1, self.llm.request_working_checkpoint.call_count)
        data = json.loads(session._seed(CORE_PROMPT, [])[-1]['content'].split(': ', 1)[1])
        self.assertEqual(1, data['execution_activity']['repeated_content_reads'])
        self.assertEqual(1, data['execution_activity']['repeated_returned_results'])

    def test_empty_response_continues_from_checkpoint_after_write_exactly_once(self):
        self.llm.request_working_checkpoint = Mock(side_effect=self.checkpoint)
        empty = EmptyModelResponseError(finish_reason='stop', stream_done=True, reasoning_chars=17083)
        self.llm.request_tool_turn.side_effect = [call('eve__load_capabilities', {'capabilities': ['shell']}),
            call('shell__execute', {'command': 'synthetic command'}), empty,
            {'content': 'Bericht aus gesicherten Ergebnissen.', 'tool_calls': []}]
        execute = Mock(return_value={'status': 'completed', 'stdout': 'evidence', 'exit_code': 0})
        self.agent.shell = SimpleNamespace(enabled=True, native_contract=lambda: {'description': 'Synthetic shell',
            'operations': {'execute': {'effect': 'write', 'parameters_schema': {'type': 'object',
                'properties': {'command': {'type': 'string'}}, 'required': ['command']}}}},
            execute_native_operation=execute)
        self.assertEqual('Bericht aus gesicherten Ergebnissen.', self.runtime.respond('Analysiere.'))
        self.assertEqual(1, execute.call_count)
        self.assertEqual(4, self.llm.request_tool_turn.call_count)
        self.assertEqual(1, self.llm.request_working_checkpoint.call_count)
        session = self.runtime.working_session
        observations = session.store.list_objects(session.workspace_id, kind='model_response_error')['items']
        self.assertEqual(empty.response_evidence, session.store.value(session.workspace_id, observations[0]['reference']))

    def test_repeated_empty_response_stops_despite_new_checkpoint(self):
        self.llm.request_working_checkpoint = Mock(side_effect=self.checkpoint)
        self.llm.request_tool_turn.side_effect = EmptyModelResponseError(finish_reason='stop')
        with self.assertRaises(EmptyModelResponseError):
            self.runtime.respond('Auftrag')
        self.assertEqual(2, self.llm.request_tool_turn.call_count)
        self.assertEqual(1, self.llm.request_working_checkpoint.call_count)

    def test_repeated_output_limit_keeps_its_category_after_checkpoint_recovery(self):
        self.llm.request_working_checkpoint = Mock(side_effect=self.checkpoint)
        self.llm.request_tool_turn.side_effect = LocalLLMOutputLimitError('length', 'partial, not a final answer')
        with self.assertRaises(LocalLLMOutputLimitError):
            self.runtime.respond('Auftrag')
        self.assertEqual(2, self.llm.request_tool_turn.call_count)
        self.assertEqual(1, self.llm.request_working_checkpoint.call_count)
        with self.db.connect() as connection:
            messages = connection.execute("SELECT content,metadata_json FROM messages WHERE role='assistant'").fetchall()
        self.assertEqual(['Vorgang fehlgeschlagen.'], [m['content'] for m in messages])
        self.assertEqual('failed', json.loads(messages[0]['metadata_json'])['runtime_status'])

    def test_base_prompt_is_byte_identical_to_pre_change_contract(self):
        self.assertEqual('ff172335332be70a7df1385d657face9b18cce783acc9099432da744615de72d',
                         hashlib.sha256(CORE_PROMPT.encode()).hexdigest())

    def test_new_session_gets_checkpoint_and_delta_references(self):
        session = self.session()
        self.llm.request_working_checkpoint = Mock(side_effect=self.checkpoint)
        session.capture_checkpoint([{'role': 'system', 'content': CORE_PROMPT}], CORE_PROMPT, 'capacity')
        identifier = session.store.start_call(session.workspace_id, session.turn_id, 'after', 'fixture', 'read', 'read', {})
        session.store.dispatch_call(session.workspace_id, identifier)
        result = session.store.finish_call(session.workspace_id, session.turn_id, identifier, {'evidence': 'after checkpoint'})
        restarted = WorkingMemorySession(self.agent, 'Fortsetzen', [], 'restart')
        # Simulate a model transport without checkpoint serialization support.
        del self.llm.request_working_checkpoint
        frames, _, _ = restarted.prepare([{'role': 'system', 'content': CORE_PROMPT}], [], {},
            {'loaded_capabilities': []}, CORE_PROMPT, self.runtime._published_tools, force=True)
        data = json.loads(frames[2]['content'].split(': ', 1)[1])
        self.assertEqual('Analyse', data['model_authored_checkpoint']['goal'])
        delta = restarted.store.value(restarted.workspace_id, data['execution_delta_reference'])
        self.assertEqual([result['reference']], [item['result_reference'] for item in delta['calls']])
        self.assertFalse(delta['model_answers_are_verified_facts'])

    def test_workspace_switch_saves_old_state_without_mixing_source_frames(self):
        session = self.session()
        old_workspace = session.workspace_id
        new_workspace = session.store.create()
        new_checkpoint = session.store.checkpoint(new_workspace, {'goal': 'Other workspace'}, expected_revision=0)
        self.llm.request_working_checkpoint = Mock(side_effect=self.checkpoint)
        messages = [{'role': 'system', 'content': CORE_PROMPT},
                    {'role': 'user', 'content': 'Old source material, do not copy to another workspace.'}]
        session.execute('open', {'workspace_id': new_workspace})
        frames, _, _ = session.prepare(messages, [], {}, {'loaded_capabilities': []}, CORE_PROMPT,
                                      self.runtime._published_tools)
        self.assertIsNotNone(session.store.manifest(old_workspace)['checkpoint_reference'])
        self.assertEqual(new_checkpoint['checkpoint']['reference'], session.entry()['checkpoint_reference'])
        self.assertNotIn('Old source material', json.dumps(frames))
        self.assertEqual(1, self.llm.request_working_checkpoint.call_count)


class OutputBudgetTest(unittest.TestCase):
    def llm(self, **config):
        llm = OpenAICompatibleLLM({'base_url': 'http://127.0.0.1:1/v1', 'model': 'fixture', **config})
        llm.runtime_model_info = Mock(return_value={'provider': 'strata', 'context_length': 32768})
        return llm

    def measure(self, llm, count):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps({'input_tokens': count}).encode())):
            return llm.context_budget([{'role': 'user', 'content': 'test'}], [])

    def test_server_default_overrides_observed_and_no_output_cap_is_invented(self):
        llm = self.llm()
        unknown = self.measure(llm, 31767)
        self.assertIsNone(unknown['requested_output_tokens'])
        self.assertEqual('unknown', unknown['output_budget_basis'])
        llm._observe_generation({'completion_tokens': 2048})
        observed = self.measure(llm, 31767)
        self.assertTrue(observed['fits'])
        self.assertEqual('unknown', observed['output_budget_basis'])
        self.assertEqual(2048, observed['observed_completion_tokens'])
        llm.runtime_model_info.return_value['server_output_tokens'] = 4096
        known = self.measure(llm, 30000)
        self.assertFalse(known['fits'])
        self.assertEqual(4096, known['requested_output_tokens'])
        self.assertEqual('server_default', known['output_budget_basis'])
        self.assertIsNone(llm.generation_max_tokens)

    def test_manual_output_budget_remains_authoritative(self):
        llm = self.llm(use_server_limits=False, max_tokens=3000)
        llm._observe_generation({'completion_tokens': 5000})
        result = self.measure(llm, 30000)
        self.assertEqual(3000, result['requested_output_tokens'])
        self.assertEqual('configured', result['output_budget_basis'])
        self.assertFalse(result['fits'])

    def test_usage_is_recorded_even_when_generation_hits_output_limit(self):
        llm = self.llm()
        payload = {'choices': [{'finish_reason': 'length', 'message': {'content': '', 'reasoning_content': 'thinking'}}],
                   'usage': {'completion_tokens': 3500}}
        with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())):
            with self.assertRaises(LocalLLMOutputLimitError):
                llm.request_tool_turn([], [], None)
        self.assertEqual(3500, llm._observed_completion_tokens)
        self.assertTrue(self.measure(llm, 30000)['fits'])

    def test_checkpoint_transport_forces_only_persistence_and_does_not_publish_answer(self):
        llm = self.llm()
        payload = {'choices': [{'finish_reason': 'tool_calls', 'message': {'content': 'Internal state',
            'tool_calls': [{'id': 'cp', 'function': {'name': 'working_memory__checkpoint',
            'arguments': '{"state":{"goal":"test"},"expected_revision":0}'}}]}}]}
        answer, preview = [], []
        with llm.stream_answers(answer.append), llm.stream_tool_previews(preview.append, lambda: None):
            with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())) as opened:
                response = llm.request_working_checkpoint([], [])
            self.assertIsNotNone(llm._stream_callback.get())
        wire = json.loads(opened.call_args.args[0].data)
        self.assertEqual('working_memory__checkpoint', wire['tool_choice']['function']['name'])
        self.assertNotIn('max_tokens', wire)
        self.assertEqual([], answer)
        self.assertEqual([], preview)
        self.assertEqual('working_memory__checkpoint', response['tool_calls'][0]['name'])

    def test_streamed_checkpoint_uses_same_forced_choice_and_counts_reasoning_tokens(self):
        llm = self.llm()
        events = [
            {'choices': [{'delta': {'reasoning_content': 'private reasoning'}}]},
            {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'cp', 'function': {
                'name': 'working_memory__checkpoint', 'arguments': '{"expected_revision":0,"state":{"goal":"test"}}'}}]},
                'finish_reason': 'tool_calls'}]},
            {'choices': [], 'usage': {'prompt_tokens': 200, 'completion_tokens': 900}},
        ]
        class Stream:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def __iter__(self):
                return iter([('data: ' + json.dumps(event) + '\n\n').encode() for event in events] + [b'data: [DONE]\n\n'])
        reasoning, answer = [], []
        with llm.stream_answers(answer.append), llm.stream_reasoning(reasoning.append):
            with patch('urllib.request.urlopen', return_value=Stream()) as opened:
                result = llm.request_working_checkpoint([], [])
        wire = json.loads(opened.call_args.args[0].data)
        self.assertTrue(wire['stream'])
        self.assertEqual('working_memory__checkpoint', wire['tool_choice']['function']['name'])
        self.assertEqual(900, llm._observed_completion_tokens)
        self.assertEqual([], answer)
        self.assertEqual(['private reasoning'], reasoning)
        self.assertEqual('working_memory__checkpoint', result['tool_calls'][0]['name'])

    def test_server_generation_defaults_precedence_and_unlimited_mode(self):
        from urllib.parse import urlsplit
        for props, shared, expected, source in ((2048, {}, 2048, 'props'),
                (2048, {'max_tokens': 4096}, 4096, 'settings'),
                (-1, {}, None, 'props'), (2048, {'max_tokens': -1}, None, 'settings')):
            with self.subTest(props=props, shared=shared):
                llm = self.llm()
                responses = [io.BytesIO(json.dumps({'default_generation_settings': {'params': {'n_predict': props}}}).encode()),
                             io.BytesIO(json.dumps({'defaults': shared}).encode())]
                with patch('urllib.request.urlopen', side_effect=responses):
                    result = llm._server_generation_limit(urlsplit(llm.base_url))
                self.assertEqual(expected, result['server_output_tokens'])
                self.assertEqual(source, result['server_output_limit_source'])
