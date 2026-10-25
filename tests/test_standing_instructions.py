import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from eve_agent.agent import EveAgent
from eve_agent.memory_compiler import MemoryCompiler
from eve_agent.memory_v2 import MemoryV2Runtime
from eve_agent.minimal import CORE_PROMPT, NativeToolRuntime
from eve_agent.shadow_learning import ProductiveLearningPipeline
from eve_agent.state import StateBus
from eve_agent.storage import ConversationStore, EveDatabase
from eve_agent.working_context import WorkingMemorySession


class StandingInstructionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = EveDatabase(self.root / 'eve.db')
        self.chats = ConversationStore(self.db)
        self.chat = self.chats.create()['id']
        self.memory = MemoryV2Runtime(self.db, MemoryCompiler(self.db))

    def learn(self, text, *, applicability='always', kind='user_instruction', display=None):
        import uuid
        turn = uuid.uuid4().hex
        user, _ = self.chats.append_turn(self.chat, text, 'Verstanden.', turn_id=turn)
        pipeline = ProductiveLearningPipeline(self.db)
        snapshot = pipeline._snapshot(turn)
        proposal = {'decision_type': 'create_active', 'memory_worthy': True,
            'reason_code': 'explicit_user_instruction', 'uncertainty': 0,
            'authority': 'user_direct', 'temporal_class': 'stable', 'change_type': 'new',
            'clarification_recommended': False, 'matched_claim_ids': [], 'relations': [],
            'claim': {'kind': 'opaque_fact', 'scope': 'user:self', 'canonical_key': 'v2:instruction:' + turn,
                'display_text': display or text, 'payload': {'epistemic_kind': kind, 'applicability': applicability}},
            'evidence': [{'source_type': 'user_message', 'source_id': user['id']}]}
        checked = pipeline._validate_proposal(proposal, snapshot, [])
        if checked['decision_type'] == 'create_active':
            pipeline._persist(snapshot, checked, 'test_grounded_instruction', {}, time.perf_counter())
        return checked

    def test_explicit_global_instruction_reaches_unrelated_turn_and_context_reset(self):
        instruction = 'Vergleiche Ergebnisse mit dem Ziel und prüfe erfolglose Ansätze neu.'
        self.assertEqual('create_active', self.learn(instruction)['decision_type'])
        llm = SimpleNamespace(request_tool_turn=Mock(return_value={'content': 'Okay.', 'tool_calls': []}),
                              max_tokens=1500, runtime_model_info=lambda: {})
        agent = EveAgent('EVE', self.memory, llm, StateBus(self.root / 'runtime'), conversations=self.chats)
        agent.conversation_id = self.chat
        NativeToolRuntime(agent).respond('Passwort: dummy-fixture-value')
        messages = llm.request_tool_turn.call_args.args[0]
        self.assertEqual(CORE_PROMPT, messages[0]['content'].split('\nTemporary credentials:')[0])
        self.assertNotIn(instruction, messages[0]['content'])
        self.assertIn(instruction, messages[-1]['content'])
        session = WorkingMemorySession(agent, 'Eine ganz andere Aufgabe.', [], 'fixture-trace')
        seed = session._seed(CORE_PROMPT, [])
        self.assertIn(instruction, json.dumps(seed, ensure_ascii=False))
        claim = self.memory.standing_instructions()[0]['memory_id']
        with self.db.connect() as c:
            c.execute("UPDATE memory_claims SET lifecycle='retired' WHERE id=?", (claim,))
        self.assertEqual([], self.memory.standing_instructions())
        self.assertNotIn(instruction, json.dumps(session._seed(CORE_PROMPT, []), ensure_ascii=False))

    def test_durable_user_statement_stays_searchable_without_becoming_global(self):
        fact = "Miras Lesetermin findet jede Woche dienstags um 10 Uhr statt."
        checked = self.learn(fact, applicability='query', kind='user_statement')
        self.assertEqual('create_active', checked['decision_type'])
        database = EveDatabase(self.db.path)
        reopened = MemoryV2Runtime(database, MemoryCompiler(database))
        self.assertEqual([], reopened.standing_instructions())
        self.assertIn(fact, [hit.text for hit in reopened.retrieve('Miras Lesetermin')])
        instruction = 'Antworte mir grundsätzlich auf Deutsch, unabhängig vom Thema.'
        self.assertEqual('create_active', self.learn(instruction)['decision_type'])
        self.assertEqual([instruction], [item['content'] for item in reopened.standing_instructions()])
        self.assertIn(fact, [hit.text for hit in reopened.retrieve('Miras Lesetermin')])

    def test_query_rules_candidates_expired_and_unsupported_claims_are_not_global(self):
        self.learn('Thematische Anweisung.', applicability='query')
        rejected = self.learn('Ein beobachteter Wert.', kind='tool_observation')
        self.assertEqual('global_instruction_requires_user_grounding', rejected['reason_code'])
        rejected = self.learn('Wirklicher Nutzertext.', display='Erfundene Anweisung.')
        self.assertEqual('user_instruction_not_grounded_verbatim', rejected['reason_code'])
        self.learn('Nicht mehr gültig.')
        with self.db.connect() as c:
            c.execute("UPDATE memory_claims SET valid_until='2020-01-01' WHERE display_text='Nicht mehr gültig.'")
        self.learn('Noch unbestätigt.')
        with self.db.connect() as c:
            c.execute("UPDATE memory_claims SET lifecycle='candidate' WHERE display_text='Noch unbestätigt.'")
        self.assertEqual([], self.memory.standing_instructions())
