import unittest
from copy import deepcopy
import json
from unittest.mock import Mock
from eve_agent.llm import OpenAICompatibleLLM
from eve_agent.learning_drafts import validate_draft, fingerprint


class LearningDraftTest(unittest.TestCase):
    def setUp(self):
        self.context = {'turn_id': 't', 'conversation_id': 'private', 'claims': [],
                        'messages': [{'id': 'u', 'role': 'user', 'content': 'Was ist Horimono?'},
                                     {'id': 'a', 'role': 'assistant', 'content': '**Horimono** ist ein Begriff.'}]}
        self.draft = {'lessons': [{'key': 'topic', 'text': 'Horimono wurde besprochen.',
                                  'kind': 'encounter', 'status': 'observed_conversation',
                                  'evidence': [{'message_id': 'u', 'quote': 'Was ist Horimono?'}]}],
                      'relations': []}

    def test_encounter_retains_conversation_and_source_fingerprint(self):
        result = validate_draft(self.draft, self.context)
        self.assertEqual(result['conversation_id'], 'private')
        self.assertEqual(result['source_fingerprint'], fingerprint(self.context))
        self.assertEqual(result['status'], 'draft')

    def test_invented_or_foreign_source_is_rejected(self):
        self.draft['lessons'][0]['evidence'][0]['message_id'] = 'another-private-chat'
        with self.assertRaisesRegex(ValueError, 'exact_source_quote_required'):
            validate_draft(self.draft, self.context)

    def test_paraphrase_is_not_a_quote(self):
        self.draft['lessons'][0]['evidence'][0]['quote'] = 'Was bedeutet Horimono?'
        with self.assertRaisesRegex(ValueError, 'exact_source_quote_required'):
            validate_draft(self.draft, self.context)

    def test_assistant_fact_requires_unverified_status(self):
        lesson = self.draft['lessons'][0]
        lesson.update(kind='semantic', status='explicit_user',
                      evidence=[{'message_id': 'a', 'quote': '**Horimono** ist ein Begriff.'}])
        with self.assertRaisesRegex(ValueError, 'explicit_user_requires_user_sources_only'):
            validate_draft(self.draft, self.context)
        lesson['status'] = 'unverified'
        self.assertEqual(validate_draft(self.draft, self.context)['lessons'][0]['status'], 'unverified')

    def test_dialog_support_requires_both_speakers(self):
        self.draft['lessons'][0]['status'] = 'dialog_supported'
        with self.assertRaisesRegex(ValueError, 'dialog_support_requires_both_speakers'):
            validate_draft(self.draft, self.context)

    def test_observation_cannot_be_promoted_to_world_knowledge(self):
        self.draft['lessons'][0]['kind'] = 'semantic'
        with self.assertRaisesRegex(ValueError, 'conversation_observation_is_not_world_knowledge'):
            validate_draft(self.draft, self.context)

    def test_question_and_praise_cannot_be_marked_as_explicit_instruction(self):
        lesson = self.draft['lessons'][0]
        lesson.update(kind='instruction', status='explicit_user', text='Ask the author before sharing.')
        with self.assertRaisesRegex(ValueError, 'explicit_user_text_must_be_quoted'):
            validate_draft(self.draft, self.context)

    def test_confirmation_must_follow_the_cited_proposal(self):
        lesson = self.draft['lessons'][0]
        lesson.update(kind='instruction', status='dialog_supported', evidence=[
            {'message_id': 'u', 'quote': 'Was ist Horimono?'},
            {'message_id': 'a', 'quote': '**Horimono** ist ein Begriff.'}])
        with self.assertRaisesRegex(ValueError, 'dialog_confirmation_must_follow_proposal'):
            validate_draft(self.draft, self.context)
        self.context['messages'].append({'id': 'confirmation', 'role': 'user', 'content': 'Sehr gut!'})
        lesson['evidence'].append({'message_id': 'confirmation', 'quote': 'Sehr gut!'})
        self.assertEqual(validate_draft(self.draft, self.context)['status'], 'draft')

    def test_model_draft_retries_structural_error_and_stops(self):
        llm = object.__new__(OpenAICompatibleLLM)
        llm.generation_max_tokens = 1000
        invalid = deepcopy(self.draft)
        invalid['lessons'][0]['evidence'][0]['quote'] = 'invented quote'
        llm._request_stream = Mock(side_effect=[json.dumps(invalid), json.dumps(self.draft)])
        result = llm.analyze_learning_draft(self.context)
        self.assertEqual(result['status'], 'draft')
        self.assertEqual(llm._request_stream.call_count, 2)
        llm._request_stream = Mock(return_value=json.dumps(invalid))
        with self.assertRaisesRegex(ValueError, 'exact_source_quote_required'):
            llm.analyze_learning_draft(self.context)
        self.assertEqual(llm._request_stream.call_count, 2)

    def test_reports_all_invalid_lesson_paths(self):
        invalid = deepcopy(self.draft['lessons'][0])
        invalid['key'] = 'second'
        self.draft['lessons'].append(invalid)
        for lesson in self.draft['lessons']:
            lesson['evidence'][0]['quote'] = 'Invented quote'
        with self.assertRaises(ValueError) as caught:
            validate_draft(self.draft, self.context)
        self.assertIn('/lessons/0', str(caught.exception))
        self.assertIn('/lessons/1', str(caught.exception))

    def test_store_is_idempotent_and_never_creates_claims(self):
        import tempfile
        from pathlib import Path
        from eve_agent.storage import EveDatabase, ConversationStore
        from eve_agent.learning_drafts import episode_context, draft_context, LearningDraftStore
        with tempfile.TemporaryDirectory() as temp:
            db = EveDatabase(Path(temp) / 'eve.db')
            conversations = ConversationStore(db)
            cid = conversations.create('Private')['id']
            user, _ = conversations.append_turn(cid, 'Was ist Horimono?', 'Ein Begriff.', turn_id='episode')
            conversations.append_turn(cid, 'Future message', 'Future answer', turn_id='future')
            context = draft_context(episode_context(db, 'episode'))
            self.assertEqual(len(context['messages']), 2)
            self.draft['lessons'][0]['evidence'][0]['message_id'] = user['id']
            draft = validate_draft(self.draft, context)
            store = LearningDraftStore(db)
            one = store.save(draft, context)
            self.assertEqual(one, store.save(draft, context))
            self.assertEqual(store.inspect(one['observation_id']), draft)
            self.assertEqual(len(store.search(cid, 'Horimono')), 1)
            self.assertEqual(store.search('another-private-chat', 'Horimono'), [])
            with db.connect() as c:
                self.assertEqual(c.execute('SELECT count(*) FROM memory_claims').fetchone()[0], 0)
                self.assertEqual(c.execute('SELECT count(*) FROM memory_observations').fetchone()[0], 1)
                c.execute("UPDATE messages SET content='Changed' WHERE id=?", (user['id'],))
            with self.assertRaisesRegex(ValueError, 'draft_message_source_changed'):
                store.save(draft, context)

    def test_message_reference_resolves_original_without_model_copying(self):
        del self.draft['lessons'][0]['evidence'][0]['quote']
        result = validate_draft(self.draft, self.context)
        self.assertEqual(result['lessons'][0]['evidence'][0]['quote'], 'Was ist Horimono?')
        self.assertNotIn('quote', self.draft['lessons'][0]['evidence'][0])

    def test_topic_terms_keep_exact_source_vocabulary(self):
        lesson = self.draft['lessons'][0]
        lesson['topics'] = ['Horimono']
        self.assertEqual(validate_draft(self.draft, self.context)['lessons'][0]['topics'], ['Horimono'])
        lesson['topics'] = ['Irezumi']
        inferred = validate_draft(self.draft, self.context)['lessons'][0]
        self.assertEqual(inferred['topic_sources']['Irezumi'], [])

    def test_source_labels_are_derived_without_language_interpretation(self):
        lesson = self.draft['lessons'][0]
        del lesson['status']
        self.assertEqual(validate_draft(self.draft, self.context)['lessons'][0]['status'], 'observed_conversation')
        lesson.update(kind='semantic', text='Horimono is a topic.')
        self.assertEqual(validate_draft(self.draft, self.context)['lessons'][0]['status'], 'user_supported_inference')
        lesson['evidence'] = [{'message_id': 'a'}]
        self.assertEqual(validate_draft(self.draft, self.context)['lessons'][0]['status'], 'unverified')

    def test_generation_schema_publishes_only_real_sources(self):
        from jsonschema import Draft202012Validator
        from eve_agent.learning_drafts import draft_response_format
        schema = draft_response_format(self.context)['json_schema']['schema']
        draft = deepcopy(self.draft)
        del draft['lessons'][0]['status']
        draft['lessons'][0]['topics'] = ['Horimono']
        del draft['lessons'][0]['evidence'][0]['quote']
        validator = Draft202012Validator(schema)
        self.assertEqual(list(validator.iter_errors(draft)), [])
        draft['lessons'][0]['evidence'][0]['message_id'] = 'foreign-private-message'
        self.assertTrue(list(validator.iter_errors(draft)))

    def test_unpublished_relation_target_is_rejected(self):
        self.draft['relations'] = [{'from_key': 'topic', 'target_id': 'foreign', 'type': 'about',
                                  'rationale': 'topic', 'evidence': self.draft['lessons'][0]['evidence']}]
        with self.assertRaisesRegex(ValueError, 'published_relation_endpoints_required'):
            validate_draft(self.draft, self.context)
