import tempfile
import unittest
from pathlib import Path
from eve_agent.semantic_links import SemanticLinks
from eve_agent.storage import EveDatabase


class SemanticLinksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'eve.db'
        self.links = SemanticLinks(EveDatabase(self.path))
        self.context = {'conversation_id': 'c', 'history': [], 'focus': [], 'pending': None, 'task_active': False}
        self.provider = {'provider': 'home_assistant', 'endpoint': 'http://ha'}
        self.plan = {'effect': 'write', 'context_required': False,
                     'actions': [{'type': 'call_service', 'entity_id': 'light.a', 'service': 'light.turn_on'}]}

    def learn(self):
        return self.links.learn('Bitte Licht', self.context, self.provider, self.plan,
                                {'status': 'success'}, source_ref='turn:1')

    def confirmed(self):
        i = self.learn()
        self.links.decide(i, confirmed=True, source_ref='user:2')
        return i

    def lookup(self, text='Bitte Licht', context=None):
        return self.links.lookup(text, self.context if context is None else context, self.provider)

    def test_success_does_not_confirm(self):
        self.learn()
        self.assertIsNone(self.lookup())
        self.assertEqual(self.links.export()[0]['confirmation'], 'unconfirmed')

    def test_persistent_confirmation_and_evidence(self):
        i = self.confirmed()
        restarted = SemanticLinks(EveDatabase(self.path))
        self.assertEqual(restarted.lookup('Bitte Licht', self.context, self.provider)['id'], i)
        self.assertEqual(len(restarted.export()[0]['evidence']), 3)

    def test_exact_text_no_normalization(self):
        self.confirmed()
        for text in ['bitte Licht', 'Bitte Licht ', 'Mach Licht an']:
            self.assertIsNone(self.lookup(text))

    def test_context_and_provider_identity(self):
        self.confirmed()
        self.assertIsNone(self.lookup(context={**self.context, 'history': [{'role': 'user', 'content': 'x'}]}))
        self.assertIsNone(self.links.lookup('Bitte Licht', self.context, {**self.provider, 'endpoint': 'http://other'}))

    def test_user_can_explicitly_release_context_conditions(self):
        i = self.learn()
        self.links.decide(i, confirmed=True, source_ref='user:2', context_independent=True)
        self.assertIsNotNone(self.lookup(context={**self.context, 'history': [{'content': 'x'}], 'focus': ['light.b']}))
        self.assertIsNone(self.lookup(context={**self.context, 'conversation_id': 'other'}))

    def test_temporary_and_denied_results_preserve_interpretation(self):
        i = self.confirmed()
        for status in ['network_error', 'rejected', 'outcome_uncertain']:
            self.links.feedback(i, {'status': status}, source_ref='provider:3')
            self.assertIsNotNone(self.lookup())
        self.assertEqual(self.lookup()['failures'], 3)

    def test_resource_and_service_invalidation_preserve_evidence(self):
        i = self.confirmed()
        self.links.feedback(i, {'status': 'invalid'}, source_ref='provider:3', invalid_reason='resource_missing')
        self.assertIsNone(self.lookup())
        self.assertEqual(len(self.links.export()[0]['evidence']), 4)
        with self.assertRaises(ValueError):
            self.links.decide(i, confirmed=True, source_ref='user:4')

    def test_user_correction_blocks_reuse(self):
        i = self.confirmed()
        self.links.decide(i, confirmed=False, source_ref='user:3')
        self.assertIsNone(self.lookup())

    def test_competing_links_fail_closed(self):
        self.confirmed()
        self.confirmed()
        self.assertIsNone(self.lookup())

    def test_versioned_correction(self):
        old = self.confirmed()
        new = self.learn()
        self.links.decide(new, confirmed=True, source_ref='user:4', supersedes=old)
        self.assertEqual(self.lookup()['version'], 2)
        self.assertEqual(self.lookup()['id'], new)
        self.assertEqual(self.links.export()[1]['relations'][0]['relation_type'], 'supersedes')

    def test_ambiguous_context_and_redacted_plan_not_learned(self):
        for plan in [{**self.plan, 'clarification': 'Which?'}, {**self.plan, 'context_required': True},
                     {**self.plan, 'actions': [{'type': 'call_service'}]}]:
            self.assertIsNone(self.links.learn('x', {}, self.provider, plan, {}, source_ref='t'))

    def test_action_experience_is_excluded_from_general_memory_retrieval(self):
        from eve_agent.memory_compiler import MemoryCompiler, MemoryNeed
        from eve_agent.memory_v2 import MemoryV2Runtime
        self.confirmed()
        compiler = MemoryCompiler(self.links.database)
        runtime = MemoryV2Runtime(self.links.database, compiler)
        self.assertNotIn('semantic_links', runtime._scopes_for_query('Bitte Licht'))
        need = MemoryNeed(consumer='answer', query='Bitte Licht', scopes=('semantic_links',))
        self.assertEqual(compiler._retrieve(need), {})
