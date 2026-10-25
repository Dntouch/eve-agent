import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from eve_agent.semantic_links import (
    SemanticLinks, ACTION_SCOPE, POLICY, character_similarity,
    structural_token_variant, surface_tokens,
)
from eve_agent.semantic_inspector import SemanticInspector, turn_semantics
from eve_agent.storage import EveDatabase, ConversationStore
from eve_agent.memory_compiler import MemoryCompiler, MemoryNeed
from eve_agent.memory_v2 import MemoryV2Runtime
from eve_agent.llm import OpenAICompatibleLLM


class SemanticActionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db=EveDatabase(Path(self.tmp.name)/'eve.db'); self.links=SemanticLinks(self.db)
        self.provider={'provider':'fixture','endpoint':'http://fixture.invalid'}
        self.context={'conversation_id':'c','history':[],'focus':[],'pending':None,'task_active':False}
        self.actions=[{'type':'call_service','entity_id':'cover.fixture','service':'cover.close_cover','desired_state':'closed'}]
        self.turn=0
    def plan(self,text,kind='new',group='',anchor='',keys=None,actions=None):
        return {'effect':'write','actions':copy.deepcopy(actions or self.actions),
            'semantic_learning':{'status':'resolved','context_keys':keys or [],'user_grounding':'explicit','uncertainties':[],
                'utterance_quote':text,'basis':'Fixture explicit user evidence.',
                'action_link':{'kind':kind,'representation_id':group,'anchor_claim_id':anchor,
                    'meaning':'Ressource vollständig schließen.' if kind=='new' else '',
                    'basis':'Fixture explicit equivalence to the referenced published interpretation.'}}}
    def learn(self,text,plan=None,published=None,context=None,provider=None,result=None):
        self.turn+=1
        i=self.links.learn(text,self.context if context is None else context,self.provider if provider is None else provider,
            plan or self.plan(text),result or {'status':'success'},source_ref='fixture:turn:'+str(self.turn),
            provider_validated=True,published_actions=published)
        return self.links.experience(i)
    def group(self):
        a=self.learn('Formulierung A'); candidates=self.links.action_candidates(self.provider,context=self.context)
        return a,candidates
    def member(self,text='Formulierung B'):
        a,p=self.group(); b=self.learn(text,self.plan(text,'existing',a['action_representation_id'],a['id']),p)
        return a,b,p

    def persisted_action(self, claim):
        store = ConversationStore(self.db)
        conversation = store.create('Feedback fixture')
        turn_id = 'feedback-turn-' + str(self.turn)
        user, assistant = store.append_turn(
            conversation['id'], claim['utterance'], 'Ausgeführt.', turn_id=turn_id,
            assistant_metadata={
                'turn_state': 'operational_resolved',
                'turn_state_details': {
                    'operational_execution': True,
                    'semantic_link_candidate_id': claim['id'],
                },
            },
        )
        self.links.attach_turn_provenance(claim['origin_ref'], turn_id, user['id'])
        return store, conversation, assistant

    def test_explicit_llm_equivalence_links_distinct_formulations_without_release(self):
        a,b,p=self.member()
        self.assertEqual(a['action_representation_id'],b['action_representation_id'])
        self.assertEqual(b['lifecycle'],'candidate'); self.assertEqual(b['confirmation'],'unconfirmed')
        self.assertIsNone(self.links.lookup(b['utterance'],self.context,self.provider))
        inspector=SemanticInspector(self.db.path)
        detail=inspector.action_detail(a['action_representation_id'])
        self.assertEqual(len(detail['members']),2); self.assertEqual(detail['item']['execution_authorization'],'none')
        self.assertIn('semantic_action_support',[e['evidence_type'] for e in detail['evidence']])
        self.assertEqual(inspector.summary()['stock']['linked_formulations'],2)
        self.assertEqual(inspector.summary()['stock']['version_relations'],0)
        restarted=SemanticLinks(EveDatabase(self.db.path))
        self.assertEqual(restarted.experience(b['id'])['action_representation_id'],a['action_representation_id'])

    def test_membership_edge_is_required_for_publication_and_exact_reuse(self):
        claim = self.learn('Kantenpflicht')
        self.links.decide(claim['id'], confirmed=True, source_ref='fixture:release')
        group_id = claim['action_representation_id']
        self.assertTrue(self.links.action_candidates(self.provider, context=self.context))
        self.assertIsNotNone(self.links.lookup(claim['utterance'], self.context, self.provider))

        with self.db.connect() as connection:
            connection.execute(
                """DELETE FROM memory_relations WHERE from_claim_id=? AND to_claim_id=?
                   AND relation_type='refines'""", (claim['id'], group_id),
            )

        self.assertEqual([], self.links.action_candidates(self.provider, context=self.context))
        self.assertIsNone(self.links.lookup(claim['utterance'], self.context, self.provider))

    def test_same_calls_without_equivalence_never_group(self):
        a,p=self.group(); plan=self.plan('Formulierung B'); plan['semantic_learning'].pop('action_link')
        b=self.learn('Formulierung B',plan,p)
        self.assertNotIn('action_representation_id',b); self.assertEqual(b['action_link_status'],'insufficient_evidence')
        self.assertEqual(SemanticInspector(self.db.path).summary()['stock']['action_representations'],1)

    def test_missing_uncertain_or_failed_evidence_cannot_create_group(self):
        for bad in ('uncertain','failed','none','grounding'):
            with self.subTest(bad=bad):
                text='Fixture '+bad; plan=self.plan(text)
                if bad=='uncertain':plan['semantic_learning']['status']='uncertain'
                if bad=='grounding':plan['semantic_learning']['user_grounding']='unknown'
                if bad=='none':plan['semantic_learning']['action_link']['kind']='none'
                r=self.learn(text,plan,result={'status':'failed'} if bad=='failed' else None)
                self.assertNotIn('action_representation_id',r)
        self.assertEqual(SemanticInspector(self.db.path).summary()['stock']['action_representations'],0)

    def test_reference_must_be_paired_published_and_current(self):
        a,p=self.group()
        for pub,anchor in (([],a['id']),(p,'invented')):
            r=self.learn('Unpublished',self.plan('Unpublished','existing',a['action_representation_id'],anchor),pub)
            self.assertNotIn('action_representation_id',r)
            self.assertEqual(r['action_link_reason'],'reference_not_published')
        self.links.decide(a['id'],confirmed=False,source_ref='fixture:user:no')
        r=self.learn('New after correction',self.plan('New after correction','existing',a['action_representation_id'],a['id']),p)
        self.assertEqual(r['action_link_reason'],'anchor_invalid')
        self.assertEqual(self.links.action_candidates(self.provider,context=self.context),[])

    def test_parameters_effect_context_and_provider_identity_are_exact_safety_constraints(self):
        a,p=self.group()
        for field in ('parameters','context','provider','effect'):
            text='Fixture '+field; plan=self.plan(text,'existing',a['action_representation_id'],a['id'])
            ctx=self.context; provider=self.provider
            if field=='parameters':plan['actions'][0]['data']={'position':50}
            if field=='context':plan['semantic_learning']['context_keys']=['conversation_id']
            if field=='provider':provider={**self.provider,'endpoint':'http://other.invalid'}
            if field=='effect':plan['effect']='read'; plan['actions']=[{'type':'get_state','entity_id':'cover.fixture'}]
            r=self.learn(text,plan,p,ctx,provider)
            self.assertEqual(r['action_link_status'],'conflict'); self.assertNotIn('action_representation_id',r)
        self.assertEqual(self.links.action_candidates({**self.provider,'endpoint':'http://other.invalid'},context=self.context),[])

    def test_group_evidence_does_not_change_independent_release_policy(self):
        a,b,p=self.member()
        again=self.learn(b['utterance'],self.plan(b['utterance'],'existing',a['action_representation_id'],a['id']),p)
        self.assertEqual(again['lifecycle'],'active'); self.assertEqual(again['automatic_policy'],POLICY)
        self.assertEqual(again['action_representation_id'],a['action_representation_id'])
        self.assertIsNotNone(self.links.lookup(b['utterance'],self.context,self.provider))
        self.assertIsNone(self.links.lookup('Noch unbekannte Variante',self.context,self.provider))

    def test_uncertain_conflicting_attempt_does_not_poison_strong_corroboration(self):
        text='Flurlicht ausschalten'
        first=self.learn(text)
        wrong_actions=[{'type':'call_service','entity_id':'light.wrong','service':'light.turn_off'}]
        weak=self.learn(text,self.plan(text,actions=wrong_actions),result={'status':'outcome_uncertain'})
        latest=self.learn(text)
        self.assertFalse(weak['strong_semantic_evidence'])
        self.assertEqual(latest['confirmation'],'corroborated')
        self.assertEqual(latest['lifecycle'],'active')
        self.assertEqual(self.links.lookup(text,self.context,self.provider)['id'],latest['id'])
        self.assertEqual(self.links.experience(first['id'])['lifecycle'],'retired')

    def test_lookup_repairs_candidates_blocked_only_by_weak_failed_attempts(self):
        text='Persistierte Flurlicht-Formulierung'
        wrong_actions=[{'type':'call_service','entity_id':'light.wrong','service':'light.turn_off'}]
        with patch.object(self.links,'_corroborate',return_value=None):
            first=self.learn(text)
            self.learn(text,self.plan(text,actions=wrong_actions),result={'status':'outcome_uncertain'})
            latest=self.learn(text)
        self.assertEqual(first['lifecycle'],'candidate')
        self.assertEqual(latest['lifecycle'],'candidate')
        repaired=self.links.lookup(text,self.context,self.provider)
        self.assertEqual(repaired['id'],latest['id'])
        self.assertEqual(repaired['confirmation'],'corroborated')
        self.assertEqual(self.links.experience(first['id'])['lifecycle'],'retired')

    def test_strong_conflicting_interpretations_still_fail_closed(self):
        text='Mehrdeutige starke Formulierung'
        wrong_actions=[{'type':'call_service','entity_id':'light.wrong','service':'light.turn_off'}]
        self.learn(text)
        self.learn(text,self.plan(text,actions=wrong_actions))
        self.learn(text)
        self.assertIsNone(self.links.lookup(text,self.context,self.provider))

    def test_targeted_rejection_preserves_other_formulations_and_prevents_regrouping(self):
        a,b,p=self.member(); self.links.decide(a['id'],confirmed=True,source_ref='fixture:user:yes')
        self.links.decide(b['id'],confirmed=False,source_ref='fixture:user:no')
        self.assertEqual(self.links.experience(b['id'])['action_link_status'],'invalid')
        self.assertIsNotNone(self.links.lookup(a['utterance'],self.context,self.provider))
        r=self.learn(b['utterance'],self.plan(b['utterance'],'existing',a['action_representation_id'],a['id']),p)
        self.assertEqual(r['action_link_reason'],'prior_user_contradiction'); self.assertEqual(r['lifecycle'],'candidate')
        detail=SemanticInspector(self.db.path).action_detail(a['action_representation_id'])
        self.assertIn('semantic_action_member_invalidated',[e['evidence_type'] for e in detail['evidence']])

    def test_action_feedback_confirms_exact_persisted_execution_and_can_be_undone(self):
        claim = self.learn('Feedback bestätigen')
        store, conversation, message = self.persisted_action(claim)
        before = self.links.experience(claim['id'])

        result = self.links.execution_feedback(conversation['id'], message['id'], 'correct')
        self.assertEqual(result, {'decision': 'correct', 'can_undo': True})
        confirmed = self.links.experience(claim['id'])
        self.assertEqual((confirmed['confirmation'], confirmed['usability'], confirmed['lifecycle']),
                         ('confirmed', 'explicit', 'active'))
        saved = store.messages(conversation['id'])['messages'][-1]['metadata']['semantic_feedback']
        self.assertEqual((saved['status'], saved['decision'], saved['claim_id']),
                         ('active', 'correct', claim['id']))
        with self.db.connect() as connection:
            provenance = connection.execute('''SELECT source_turn_id,source_message_id
                FROM memory_evidence WHERE claim_id=? AND evidence_type='ui_execution_feedback' ''',
                (claim['id'],)).fetchone()
        self.assertEqual(tuple(provenance), ('feedback-turn-1', message['id']))

        undone = self.links.execution_feedback(conversation['id'], message['id'], 'undo')
        self.assertEqual(undone, {'decision': None, 'can_undo': False})
        restored = self.links.experience(claim['id'])
        self.assertEqual((restored['confirmation'], restored['usability'], restored['lifecycle']),
                         (before['confirmation'], before['usability'], before['lifecycle']))
        self.assertNotIn('semantic_feedback', store.messages(conversation['id'])['messages'][-1]['metadata'])
        with self.db.connect() as connection:
            types = [row[0] for row in connection.execute(
                'SELECT evidence_type FROM memory_evidence WHERE claim_id=?', (claim['id'],))]
        self.assertNotIn('user_confirmation', types)
        self.assertIn('ui_execution_feedback_retracted', types)

    def test_incorrect_action_feedback_is_reversible_without_losing_later_technical_usage(self):
        claim = self.learn('Feedback verwerfen')
        store, conversation, message = self.persisted_action(claim)
        before = self.links.experience(claim['id'])
        self.links.execution_feedback(conversation['id'], message['id'], 'incorrect')
        rejected = self.links.experience(claim['id'])
        self.assertEqual((rejected['validity'], rejected['confirmation'], rejected['lifecycle']),
                         ('invalid', 'contradicted', 'invalid'))
        self.assertEqual(rejected['action_link_status'], 'invalid')

        self.links.feedback(claim['id'], {'status': 'success'}, source_ref='fixture:later-technical-result')
        self.links.execution_feedback(conversation['id'], message['id'], 'undo')
        restored = self.links.experience(claim['id'])
        self.assertEqual((restored['validity'], restored['confirmation'], restored['lifecycle']),
                         (before['validity'], before['confirmation'], before['lifecycle']))
        self.assertEqual(restored['action_link_status'], before['action_link_status'])
        self.assertEqual(restored['uses'], before['uses'] + 1)
        self.assertNotIn('semantic_feedback', store.messages(conversation['id'])['messages'][-1]['metadata'])

    def test_action_feedback_rejects_foreign_unexecuted_and_duplicate_messages(self):
        claim = self.learn('Feedback absichern')
        store, conversation, message = self.persisted_action(claim)
        other = store.create('Other')
        with self.assertRaises(KeyError):
            self.links.execution_feedback(other['id'], message['id'], 'correct')
        self.links.execution_feedback(conversation['id'], message['id'], 'correct')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.links.execution_feedback(conversation['id'], message['id'], 'incorrect')

    def test_action_feedback_accepts_a_semantic_lookup_reuse_result(self):
        claim = self.learn('Gelernte Aktion wiederverwenden')
        self.links.decide(claim['id'], confirmed=True, source_ref='fixture:explicit-confirmation')
        store = ConversationStore(self.db)
        conversation = store.create('Lookup feedback fixture')
        turn_id = 'feedback-reuse-turn'
        user, assistant = store.append_turn(
            conversation['id'], claim['utterance'], 'Erneut ausgeführt.', turn_id=turn_id,
            assistant_metadata={
                'turn_state': 'operational_resolved',
                'turn_state_details': {
                    'operational_execution': True,
                    'semantic_link_id': claim['id'],
                },
            },
        )
        self.links.feedback(claim['id'], {'status': 'success'}, source_ref='fixture:reuse-result')
        self.links.attach_turn_provenance('fixture:reuse-result', turn_id, user['id'])
        result = self.links.execution_feedback(conversation['id'], assistant['id'], 'correct')
        self.assertEqual(result['decision'], 'correct')
        self.assertEqual(self.links.experience(claim['id'])['confirmation'], 'confirmed')

    def test_explicit_context_release_and_provider_invalidation_invalidate_membership_only_as_needed(self):
        text='Context fixture'; a=self.learn(text,self.plan(text,keys=['focus']))
        self.links.decide(a['id'],confirmed=True,source_ref='fixture:user:release',context_independent=True)
        self.assertEqual(self.links.experience(a['id'])['action_link_status'],'invalid')
        self.assertIsNotNone(self.links.lookup(text,self.context,self.provider))
        self.assertEqual(self.links.action_candidates(self.provider,context=self.context),[])
        b,p=self.group(); self.links.feedback(b['id'],{'status':'invalid'},source_ref='fixture:provider',invalid_reason='resource_missing')
        self.assertEqual(self.links.experience(b['id'])['action_link_status'],'invalid')

    def test_group_pages_are_bounded_and_read_only(self):
        a,b,p=self.member(); before=self.links.export()
        inspector=SemanticInspector(self.db.path); first=inspector.action_detail(a['action_representation_id'],limit=1)
        self.assertEqual(len(first['members']),1); self.assertEqual(first['next_cursor'],1)
        self.assertEqual(len(inspector.action_detail(a['action_representation_id'],cursor=1,limit=1)['members']),1)
        self.assertIsNotNone(first['next_evidence_cursor'])
        self.assertEqual(inspector.actions(limit=1000)['items'][0]['formulations'],2)
        self.assertEqual(self.links.export(),before)
        with self.assertRaises(KeyError):inspector.action_detail(a['id'])
        with self.assertRaises(KeyError):inspector.reject(self.db,a['action_representation_id'],{'confirmed':True,'claim_id':a['action_representation_id']})

    def test_group_claims_never_enter_regular_memory_retrieval(self):
        a,p=self.group(); runtime=MemoryV2Runtime(self.db,MemoryCompiler(self.db))
        self.assertNotIn(ACTION_SCOPE,runtime._scopes_for_query('Ressource'))
        result=runtime.compiler._retrieve(MemoryNeed(consumer='planner',query='Ressource',scopes=(ACTION_SCOPE,)))
        self.assertNotIn(a['action_representation_id'],str(result))

    def test_formal_similarity_is_order_independent_and_runtime_configurable(self):
        claim = self.learn('Fahre Elenas Rollo herunter')
        self.links.decide(claim['id'], confirmed=True, source_ref='fixture:release')
        query = 'Fahr Elenas Rollo runter'
        for threshold, expected in ((.80, 'hit'), (.85, 'hit'), (.95, 'fallback')):
            with self.subTest(threshold=threshold):
                settings = self.links.configure_similarity(
                    {'enabled': True, 'mode': 'active', 'threshold': threshold})
                result = self.links.similarity_lookup(query, self.context, self.provider)
                self.assertEqual(result['status'], expected)
                self.assertEqual(result['config']['version'], settings['version'])
        reordered = self.links.similarity_lookup(
            'Rollo herunter Elenas Fahre', self.context, self.provider)
        self.assertEqual(reordered['status'], 'hit')
        score = self.links.configure_similarity(
            {'enabled': True, 'mode': 'active', 'threshold': .5})
        measured = self.links.similarity_lookup(query, self.context, self.provider)['hit']['score']
        self.links.configure_similarity({'enabled': True, 'mode': 'active', 'threshold': measured})
        self.assertEqual(self.links.similarity_lookup(query, self.context, self.provider)['status'], 'hit')
        self.assertEqual(character_similarity('licht', 'nicht'), .8)
        self.assertEqual(surface_tokens('Licht, AUS!'), ['licht', 'aus'])

    def test_similarity_ignores_punctuation_only_differences(self):
        claim = self.learn('Licht im Flur aus')
        self.links.decide(claim['id'], confirmed=True, source_ref='fixture:release')

        for query in ('Licht im Flur aus.', 'Licht im Flur aus!', 'Licht, im Flur aus?'):
            with self.subTest(query=query):
                result = self.links.similarity_lookup(query, self.context, self.provider)
                self.assertEqual('hit', result['status'])
                self.assertEqual(1.0, result['hit']['score'])

    def test_similarity_never_averages_away_a_strong_token_substitution(self):
        claim = self.learn('Wie steht das Rollo in Elenas Zimmer?')
        self.links.decide(claim['id'], confirmed=True, source_ref='fixture:release')

        result = self.links.similarity_lookup(
            'Wie steht das Rollo in Sams Zimmer?', self.context, self.provider,
        )

        self.assertEqual('fallback', result['status'])
        self.assertEqual('unsafe_token_substitution', result['reason'])
        self.assertTrue(result['unsafe_token_substitution_present'])

    def test_similarity_rejects_distinct_compounds_with_only_a_shared_suffix(self):
        claim = self.learn('Wie viel Strom verbraucht die Waschmaschine gerade?')
        self.links.decide(claim['id'], confirmed=True, source_ref='fixture:release')

        result = self.links.similarity_lookup(
            'Wie viel Strom verbraucht die Spülmaschine gerade?',
            self.context, self.provider,
        )

        self.assertEqual('fallback', result['status'])
        self.assertEqual('unsafe_token_substitution', result['reason'])
        self.assertFalse(structural_token_variant('waschmaschine', 'spülmaschine'))
        self.assertTrue(structural_token_variant('fahre', 'fahr'))
        self.assertTrue(structural_token_variant('herunter', 'runter'))

    def test_disabled_and_shadow_similarity_never_authorize_a_hit(self):
        claim = self.learn('Fahre Elenas Rollo herunter')
        self.links.decide(claim['id'], confirmed=True, source_ref='fixture:release')
        query = 'Fahr Elenas Rollo runter'
        self.links.configure_similarity({'enabled': False, 'mode': 'active', 'threshold': .8})
        self.assertEqual(self.links.similarity_lookup(query, self.context, self.provider)['status'], 'disabled')
        self.assertIsNotNone(self.links.lookup(claim['utterance'], self.context, self.provider))
        self.links.configure_similarity({'enabled': True, 'mode': 'shadow', 'threshold': .8})
        shadow = self.links.similarity_lookup(query, self.context, self.provider)
        self.assertEqual(shadow['status'], 'shadow_hit')
        self.assertIsNone(shadow['hit']); self.assertIsNotNone(shadow['shadow_candidate'])

    def test_unconfirmed_claims_and_competing_representations_are_not_reused(self):
        self.learn('Fahre Elenas Rollo herunter')
        self.links.configure_similarity({'enabled': True, 'mode': 'active', 'threshold': .8})
        self.assertEqual(self.links.similarity_lookup(
            'Fahr Elenas Rollo runter', self.context, self.provider)['status'], 'fallback')
        first = self.learn('Rollo Elena herunter')
        self.links.decide(first['id'], confirmed=True, source_ref='fixture:first')
        other_actions = [{'type':'call_service','entity_id':'cover.other','service':'cover.open_cover'}]
        second = self.learn('Rollo Elena runteer', self.plan('Rollo Elena runteer', actions=other_actions))
        self.links.decide(second['id'], confirmed=True, source_ref='fixture:second')
        ambiguous = self.links.similarity_lookup('Rollo Elena runter', self.context, self.provider)
        self.assertEqual(ambiguous['status'], 'ambiguous')
        self.assertIsNone(ambiguous['hit']); self.assertEqual(ambiguous['representation_count'], 2)

    def test_learned_negative_relation_blocks_character_trap_and_can_be_retracted(self):
        claim = self.learn('Wohnzimmer Licht aus')
        self.links.decide(claim['id'], confirmed=True, source_ref='fixture:release')
        self.links.configure_similarity({'enabled': True, 'mode': 'active', 'threshold': .85})
        query = 'Wohnzimmer nicht aus'
        self.assertEqual(self.links.similarity_lookup(query, self.context, self.provider)['status'], 'fallback')
        relation = self.links.record_similarity_relation(
            'Licht', 'nicht', 'negative', representation_id=claim['action_representation_id'],
            source_ref='fixture:correction', basis='Explizite Benutzerkorrektur.')
        blocked = self.links.similarity_lookup(query, self.context, self.provider)
        self.assertEqual(blocked['status'], 'fallback')
        self.assertTrue(blocked['negative_relation_present'])
        self.links.retract_similarity_relation(relation, source_ref='fixture:undo')
        self.assertEqual(self.links.similarity_lookup(query, self.context, self.provider)['status'], 'fallback')

    def test_positive_relation_is_versioned_and_opposite_correction_supersedes_it(self):
        claim = self.learn('Fahre Elenas Rollo herunter')
        self.links.decide(claim['id'], confirmed=True, source_ref='fixture:release')
        positive = self.links.record_similarity_relation(
            'herunter', 'runter', 'positive', representation_id=claim['action_representation_id'],
            source_ref='fixture:positive', basis='Explizit gleichbedeutend bestätigt.')
        negative = self.links.record_similarity_relation(
            'herunter', 'runter', 'negative', representation_id=claim['action_representation_id'],
            source_ref='fixture:negative', basis='Spätere explizite Korrektur.')
        with self.db.connect() as connection:
            states = {row['id']: row['lifecycle'] for row in connection.execute(
                'SELECT id,lifecycle FROM memory_claims WHERE id IN (?,?)', (positive, negative))}
        self.assertEqual(states, {positive: 'retired', negative: 'active'})
        undone = self.links.retract_similarity_relation(negative, source_ref='fixture:undo')
        self.assertEqual(undone['restored_relation_id'], positive)

    def test_false_dynamic_action_feedback_blocks_only_recognition_and_undo_restores_it(self):
        claim = self.learn('Fahre Elenas Rollo herunter')
        self.links.decide(claim['id'], confirmed=True, source_ref='fixture:release')
        query = 'Fahr Elenas Rollo runter'
        match = self.links.similarity_lookup(query, self.context, self.provider)
        self.assertEqual(match['status'], 'hit')
        store = ConversationStore(self.db); conversation = store.create('Dynamic feedback')
        turn_id = 'dynamic-feedback-turn'
        user, assistant = store.append_turn(
            conversation['id'], query, 'Ausgeführt.', turn_id=turn_id,
            assistant_metadata={'turn_state': 'operational_resolved', 'turn_state_details': {
                'operational_execution': True, 'semantic_link_id': claim['id'],
                'semantic_similarity': {
                    'semantic_reuse': 'similarity', 'learned_claim_id': claim['id'],
                    'action_representation_id': claim['action_representation_id'],
                    'input_formulation': query, 'similarity': match['hit']['score'],
                    'pairs': match['hit']['pairs'],
                }}})
        self.links.feedback(claim['id'], {'status': 'success'}, source_ref='fixture:dynamic-reuse')
        self.links.attach_turn_provenance('fixture:dynamic-reuse', turn_id, user['id'])
        self.links.execution_feedback(conversation['id'], assistant['id'], 'incorrect')
        preserved = self.links.experience(claim['id'])
        self.assertEqual((preserved['validity'], preserved['confirmation'], preserved['lifecycle']),
                         ('valid', 'confirmed', 'active'))
        blocked = self.links.similarity_lookup(query, self.context, self.provider)
        self.assertEqual(blocked['status'], 'fallback'); self.assertTrue(blocked['negative_relation_present'])
        self.links.execution_feedback(conversation['id'], assistant['id'], 'undo')
        self.assertEqual(self.links.similarity_lookup(query, self.context, self.provider)['status'], 'hit')

    def test_similarity_recognition_correction_persists_after_runtime_restart(self):
        claim = self.learn('Fahre Elenas Rollo herunter')
        self.links.decide(claim['id'], confirmed=True, source_ref='fixture:release')
        query = 'Fahr Elenas Rollo runter'
        relation = self.links.record_similarity_recognition(
            query, claim['id'], 'negative', source_ref='fixture:recognition',
            basis='Explizite Fehlzuordnung.')
        restarted = SemanticLinks(EveDatabase(self.db.path), {'enabled': True, 'mode': 'active', 'threshold': .85})
        self.assertEqual(restarted.similarity_lookup(query, self.context, self.provider)['status'], 'fallback')
        restarted.retract_similarity_relation(relation, source_ref='fixture:recognition-undo')
        self.assertEqual(restarted.similarity_lookup(query, self.context, self.provider)['status'], 'hit')
