import unittest
import json
from unittest.mock import patch

from jsonschema import Draft202012Validator

from eve_agent.learning_contract import learning_response_format
from eve_agent.llm import LearningResponseError, OpenAICompatibleLLM


class LearningContractTest(unittest.TestCase):
    def test_schema_defines_storage_and_reference_shapes_without_size_caps(self):
        schema = learning_response_format(batch=True)['json_schema']['schema']
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        proposal = {'decision_type': 'create_active', 'memory_worthy': True, 'reason_code':'test',
            'uncertainty':0.0,'clarification_recommended':False,'authority':'user_direct','temporal_class':'stable',
            'change_type':None,'matched_claim_ids':[],'relations':[], 'claim': {
            'kind': 'opaque_fact', 'scope': 'user:self', 'canonical_key': 'v2:user:convention',
            'display_text': 'An arbitrary user convention', 'payload': {'meaning': 'model-authored'},
        }, 'evidence': [{'source_type': 'user_message', 'source_id': 'published-id'}]}
        value = {'turns': [{'turn_id': 'turn', 'proposal': proposal}]}
        validator.validate(value)
        proposal['claim']['kind'] = 'instruction'
        self.assertTrue(list(validator.iter_errors(value)))
        proposal['claim']['kind'] = 'opaque_fact'
        proposal['claim']['scope'] = 'workspace:not-a-long-term-scope'
        self.assertTrue(list(validator.iter_errors(value)))
        proposal['claim']['scope'] = 'user:self'
        proposal['evidence'][0]['source_type'] = 'assistant_output'
        self.assertTrue(list(validator.iter_errors(value)))
        def walk(node):
            if isinstance(node, dict):
                for key, child in node.items():
                    self.assertNotIn(key, {'maxItems', 'maxLength', 'maximum'})
                    walk(child)
            elif isinstance(node, list):
                for child in node: walk(child)
        walk(schema)

    def test_current_source_ids_are_published_without_including_episode_context(self):
        contexts = [{'user_message': {'id': 'user-current'},
            'tool_events': [{'evidence_reference': {'source_id': 'tool-current'}}],
            'learning_episode': {'turns': [{'user_message': {'id': 'old-user'}}]}}]
        schema = learning_response_format(contexts=contexts)['json_schema']['schema']
        evidence = schema['properties']['evidence']['items']
        self.assertEqual(['tool-current', 'user-current'], evidence['properties']['source_id']['enum'])
        validator = Draft202012Validator(evidence)
        validator.validate({'source_type':'provider_result','source_id':'tool-current',
                            'result_pointer':'/value','observed_value':True})
        self.assertTrue(list(validator.iter_errors({'source_type':'provider_result','source_id':'tool-typo'})))
        self.assertIn('observed_value', evidence['properties'])
        self.assertIn('result_pointer', evidence['properties'])

    def test_learning_calls_publish_machine_readable_contract_without_output_cap(self):
        llm = OpenAICompatibleLLM({'base_url': 'http://127.0.0.1:1/v1', 'model': 'test', 'use_server_limits': True})
        with patch.object(llm, '_request_stream', return_value='{"turns":[]}') as request:
            llm.analyze_conversation_learning([])
        self.assertEqual('json_schema', request.call_args.kwargs['response_format']['type'])
        self.assertIsNone(request.call_args.args[1])
        with patch.object(llm, '_request_stream', return_value='{"decision_type":"no_persist","evidence":[]}') as request:
            llm.analyze_shadow_learning({})
        self.assertEqual('json_schema', request.call_args.kwargs['response_format']['type'])
        self.assertIsNone(request.call_args.args[1])

    def test_parser_failure_keeps_exact_raw_response_for_diagnostics(self):
        llm = OpenAICompatibleLLM({'base_url': 'http://127.0.0.1:1/v1', 'model': 'test'})
        for raw in ('{"turns":[]} {"unexpected":"second object"}', '[{"turns":[]}]', 'text before {"turns":[]}'):
            with self.subTest(raw=raw), patch.object(llm, '_request_stream', return_value=raw):
                with self.assertRaises(LearningResponseError) as caught:
                    llm.analyze_conversation_learning([])
            self.assertEqual(raw, caught.exception.raw_response)

    def test_unwrapped_known_turn_is_recovered_without_inventing_other_turns(self):
        llm = OpenAICompatibleLLM({'base_url': 'http://127.0.0.1:1/v1', 'model': 'test'})
        entry = {'turn_id': 'first', 'proposal': {'decision_type': 'no_persist'}}
        with patch.object(llm, '_request_stream', return_value=json.dumps(entry)):
            result = llm.analyze_conversation_learning([{'turn_id': 'first'}, {'turn_id': 'second'}])
        self.assertEqual({'turns': [entry]}, result)
        with patch.object(llm, '_request_stream', return_value=json.dumps(entry)):
            with self.assertRaises(LearningResponseError):
                llm.analyze_conversation_learning([{'turn_id': 'other'}])

    def test_batch_schema_scopes_ids_and_cardinality_to_each_input_turn(self):
        contexts = [{'turn_id': 'first', 'user_message': {'id': 'first-user'}},
                    {'turn_id': 'second', 'user_message': {'id': 'second-user'}}]
        schema = learning_response_format(batch=True, contexts=contexts)['json_schema']['schema']
        Draft202012Validator.check_schema(schema)
        entry = schema['properties']['turns']['items']['anyOf'][0]
        self.assertEqual(['first'], entry['properties']['turn_id']['enum'])
        sources = entry['properties']['proposal']['properties']['evidence']['items']['properties']['source_id']['enum']
        self.assertEqual(['first-user'], sources)
        self.assertEqual(2, schema['properties']['turns']['minItems'])
        self.assertEqual(2, schema['properties']['turns']['maxItems'])
        self.assertFalse(Draft202012Validator(schema).is_valid({'turns': []}))

    def test_learning_json_accepts_only_one_complete_optional_fence(self):
        from eve_agent.learning_contract import parse_learning_json
        for raw in ['{"turns": []}', '```json\n{"turns": []}\n```', '```JSON\r\n{"turns": []}\r\n```']:
            self.assertEqual({'turns': []}, parse_learning_json(raw))
        for raw in ['Explanation\n```json\n{}\n```', '```json\n{} {}\n```', '```json\n{}\n```\nextra', '```json\n{']:
            with self.subTest(raw=raw), self.assertRaises(json.JSONDecodeError): parse_learning_json(raw)
