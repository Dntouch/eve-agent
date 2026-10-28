import json
import tempfile
import unittest
from pathlib import Path

from eve_agent.semantic_inspector import SemanticInspector, turn_semantics, public
from eve_agent.semantic_links import SemanticLinks
from eve_agent.storage import EveDatabase


class SemanticInspectorTests(unittest.TestCase):
    def test_recent_learning_distinguishes_candidate_rejection_and_partial_success(self):
        from eve_agent.storage import ConversationStore
        store = ConversationStore(self.db); conversation = store.create('Learning outcomes')['id']
        rows = [('candidate', {'kind':'semantic_candidate','release':'candidate','reason':'goal_unverified'}, 'applied'),
                ('rejected', {'kind':'rejected','reason':'semantic_unpublished_action_reference'}, 'failed'),
                ('partial', {'kind':'new_formulation','claim_id':'fixture-claim'}, 'failed'),
                ('skip', {'kind':'not_reusable','reason':'Model declined reuse.'}, 'no_persist')]
        for turn, learning, status in rows:
            store.append_turn(conversation, turn, 'Answer', turn_id=turn,
                assistant_metadata={'turn_state_details':{'semantic_learning':learning,
                    'general_learning':{'status':'failed' if turn=='partial' else 'applied'}}})
            with self.db.connect() as c:
                c.execute('INSERT INTO memory_learning_jobs (turn_id,status,accepted_at,updated_at) VALUES (?,?,?,?)',
                          (turn,status,'2026-10-28', '2026-10-28'))
        outcomes = self.inspector.summary()['recent_learning']
        self.assertEqual({'semantic_candidate','rejected','new_formulation','not_reusable'}, {r['kind'] for r in outcomes})
        self.assertEqual('failed', next(r for r in outcomes if r['utterance']=='partial')['general_learning']['status'])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db = EveDatabase(Path(self.tmp.name)/'eve.db')
        self.links = SemanticLinks(self.db); self.inspector = SemanticInspector(self.db.path)
        self.context = {'conversation_id':'c','history':[], 'focus':[], 'pending':None,'task_active':False}
        self.provider = {'provider':'home_assistant','endpoint':'http://user:secret@ha/path?token=secret'}
        self.plan = {'effect':'write','actions':[{'type':'call_service','entity_id':'light.a','service':'light.turn_on'}]}

    def learn(self, text='Licht an', ref='turn:1'):
        return self.links.learn(text,self.context,self.provider,self.plan,{'status':'success'},source_ref=ref)

    def test_stock_detail_pagination_and_read_only(self):
        first = self.learn(); self.learn('Anderes Licht')
        before = self.links.export()
        page = self.inspector.listing(limit=1)
        self.assertEqual(len(page['items']),1); self.assertIsNotNone(page['next_cursor'])
        self.assertEqual(len(self.inspector.listing(cursor=page['next_cursor'],limit=1)['items']),1)
        self.assertEqual(len(self.inspector.listing(query='Licht an')['items']),1)
        self.assertEqual(len(self.inspector.listing(query='%')['items']),0)
        detail = self.inspector.detail(first,limit=1)
        self.assertEqual(len(detail['evidence']),1); self.assertIsNotNone(detail['next_cursor'])
        self.assertNotIn('secret',json.dumps(detail)); self.assertEqual(detail['item']['provider']['endpoint'],'http://ha')
        summary = self.inspector.summary(); self.assertEqual(summary['stock']['candidates'],2)
        self.assertFalse(summary['historical_telemetry']['available']); self.assertIsNone(summary['historical_telemetry']['planner_fallbacks'])
        self.assertEqual(self.links.export(),before)

    def test_listing_filters_action_link_status_for_metric_navigation(self):
        linked = self.learn('Verknüpft', ref='turn:linked')
        conflict = self.learn('Konflikt', ref='turn:conflict')
        with self.db.connect() as db:
            db.execute("UPDATE memory_claims SET payload_json=json_set(payload_json,'$.action_link_status','linked') WHERE id=?", (linked,))
            db.execute("UPDATE memory_claims SET payload_json=json_set(payload_json,'$.action_link_status','conflict') WHERE id=?", (conflict,))
        self.assertEqual([item['id'] for item in self.inspector.listing(action_link_status='usable')['items']], [linked])
        self.assertEqual([item['id'] for item in self.inspector.listing(action_link_status='conflict')['items']], [conflict])
        with self.assertRaises(ValueError):
            self.inspector.listing(action_link_status='unknown')

    def test_explicit_rejection_preserves_evidence_and_existing_policy(self):
        a=self.learn(); peer=self.learn(ref='turn:2'); unrelated=self.learn('Andere Äußerung')
        with self.assertRaises(ValueError): self.inspector.reject(self.db,a,{'confirmed':False,'claim_id':a})
        self.links.decide(a,confirmed=True,source_ref='user:1')
        self.assertEqual(self.inspector.summary()['stock']['explicit_active'],1)
        result=self.inspector.reject(self.db,a,{'confirmed':True,'claim_id':a})
        self.assertTrue(result['source_ref'].startswith('brainwatch:user:'))
        records={r['id']:r for r in self.links.export()}
        self.assertEqual(records[a]['lifecycle'],'invalid'); self.assertEqual(records[peer]['lifecycle'],'invalid')
        self.assertEqual(records[unrelated]['lifecycle'],'candidate')
        self.assertGreater(len(records[a]['evidence']),2)
        with self.assertRaises(KeyError): self.inspector.detail('not-a-semantic-claim')

    def test_turn_hit_is_not_planner_free_and_missing_is_not_zero(self):
        hit={'component':'semantic_links','operation':'lookup','status':'hit'}
        reuse={'component':'semantic_links','operation':'reuse','status':'without_planner','details':{'outcome':'success'}}
        turn={'status':'success','steps':[hit,reuse],'llm_calls':[], 'duration_ms':12}
        data=turn_semantics(turn); self.assertTrue(data['planner_free_execution']); self.assertEqual(data['prompt_tokens'],0)
        self.assertIn('Vorhandene Erfahrung um Nutzungsevidenz ergänzt', data['learning'])
        turn['llm_calls']=[{'role':'home_assistant_planner','prompt_tokens':5,'completion_tokens':2}]
        self.assertFalse(turn_semantics(turn)['planner_free_execution']); self.assertIn('Fallback',turn_semantics(turn)['route'])
        turn['llm_calls']=[{'role':'presentation_planner','prompt_tokens':1,'completion_tokens':1}]
        extra = turn_semantics(turn)
        self.assertEqual(extra['planner_calls'],1); self.assertEqual(extra['execution_planner_calls'],0)
        self.assertFalse(extra['planner_free_execution']); self.assertNotIn('Fallback',extra['route'])
        turn['llm_calls']=[{'role':'turn_review'}]; self.assertIsNone(turn_semantics(turn)['prompt_tokens'])
        del turn['llm_calls']; self.assertIsNone(turn_semantics(turn)['planner_calls'])
        turn['llm_calls']=[]; reuse['details']['outcome']='error'; self.assertFalse(turn_semantics(turn)['planner_free_execution'])

    def test_invalidation_and_user_learning_are_distinct(self):
        steps=[{'component':'semantic_links','operation':'invalidate','status':'resource_missing'}, {'component':'semantic_links','operation':'automatic_release','status':'usable'}]
        result=turn_semantics({'steps':steps,'llm_calls':[]})
        self.assertIn('Provider',result['route']); self.assertEqual(result['learning'],['Invalidiert','Automatisch freigegeben'])

    def test_automatic_evidence_context_and_versions_visible(self):
        self.plan['semantic_learning'] = {'status':'resolved','context_keys':[], 'user_grounding':'explicit',
            'uncertainties':[], 'utterance_quote':'Licht an',
            'basis':'Explizite aktuelle Nutzerangabe mit Providerziel.',
            'action_link': {'kind':'new', 'meaning':'Licht einschalten',
                            'basis':'Explizite neue Bedeutung.'}}
        a = self.links.learn('Licht an',self.context,self.provider,self.plan,{'status':'success'},source_ref='turn:a',provider_validated=True)
        b = self.links.learn('Licht an',self.context,self.provider,self.plan,{'status':'success'},source_ref='turn:b',provider_validated=True)
        summary = self.inspector.summary()
        self.assertEqual(summary['stock']['automatic_active'],1); self.assertEqual(summary['stock']['explicit_active'],0)
        detail = self.inspector.detail(b)
        self.assertEqual(detail['item']['context'],{})
        self.assertEqual(detail['item']['confirmation'],'corroborated')
        self.assertIn('automatic_release',[e['evidence_type'] for e in detail['evidence']])
        self.assertTrue(detail['relations'])
        self.links.feedback(b,{'status':'error','error':'provider unavailable'},source_ref='turn:c')
        item = next(i for i in self.inspector.listing()['items'] if i['id']==b)
        self.assertIsNotNone(item['last_use']); self.assertEqual(item['last_failure']['result']['status'],'error')
        self.assertIn('provider unavailable',json.dumps(item['last_failure']))
        with self.assertRaises(ValueError): self.inspector.reject(self.db,b,{'confirmed':1,'claim_id':b})

    def test_large_listing_has_hard_server_limit(self):
        for index in range(55): self.learn('Äußerung ' + str(index), ref='turn:' + str(index))
        page = self.inspector.listing(limit=1000)
        self.assertEqual(len(page['items']),50); self.assertEqual(page['next_cursor'],50)
        self.assertEqual(len(self.inspector.listing(cursor=50,limit=1000)['items']),5)
        self.assertNotIn('original_context',page['items'][0])

    def test_public_projection_redacts_nested_credentials_and_url_secrets(self):
        value = public({'basis': 'Quelle https://user:password@host:8123/api?token=private#fragment',
                        'nested': {'refresh_token': 'refresh-secret', 'client_secret': 'client-secret', 'cookie': 'cookie-secret'}})
        self.assertEqual(value['basis'], 'Quelle https://host:8123/api')
        self.assertEqual(set(value['nested'].values()), {'[REDACTED]'})

    def test_measured_bypasses_and_concrete_membership_are_not_inferred(self):
        events = [{'component':'semantic_links','operation':'reuse','status':'without_planner',
                   'details':{'outcome':'success','utterance':'Mach zu','action_representation_id':'group', 'membership_status':'linked', 'evidence_kind':'corroborated'}},
                  {'component':'semantic_links','operation':'planner_bypass','status':'skipped','details':{'planner':'turn_planner'}},
                  {'component':'semantic_links','operation':'planner_bypass','status':'skipped','details':{'planner':'home_assistant_planner'}}]
        turn={'status':'success','steps':events,'llm_calls':[]}
        result=turn_semantics(turn)
        self.assertEqual(result['planner_entrypoints_avoided'],2)
        self.assertEqual(result['formulation'],'Mach zu')
        self.assertEqual(result['action_representation_id'],'group')
        self.assertEqual(result['evidence_kind'],'corroborated')
        events[0]['details']['outcome']='error'
        result=turn_semantics(turn)
        self.assertIsNone(result['planner_entrypoints_avoided'])
        self.assertIn('fehlgeschlagen',result['route'])

    def test_dynamic_semantics_projection_exposes_settings_recognitions_relations_and_provenance(self):
        self.plan['semantic_learning'] = {'status':'resolved','context_keys':[], 'user_grounding':'explicit',
            'uncertainties':[], 'utterance_quote':'Wohnzimmer Licht aus', 'basis':'Explizite Nutzerangabe.',
            'action_link': {'kind':'new','meaning':'Wohnzimmerlicht ausschalten.','basis':'Explizite Aktion.'}}
        claim_id = self.links.learn('Wohnzimmer Licht aus', self.context, self.provider, self.plan,
                                    {'status':'success'}, source_ref='turn:dynamic', provider_validated=True)
        self.links.decide(claim_id, confirmed=True, source_ref='user:release')
        claim = self.links.experience(claim_id)
        relation_id = self.links.record_similarity_relation(
            'Licht', 'nicht', 'negative', representation_id=claim['action_representation_id'],
            source_ref='user:relation', basis='Explizite Korrektur.')
        self.links.feedback(claim_id, {'status': 'success', 'semantic_similarity': {
            'semantic_reuse': 'similarity', 'input_formulation': 'Wohnzimmer nicht aus',
            'learned_claim_id': claim_id, 'learned_utterance': 'Wohnzimmer Licht aus',
            'action_representation_id': claim['action_representation_id'], 'similarity': .933,
            'threshold': .85, 'pairs': []}}, source_ref='turn:reuse')
        result = self.inspector.similarity(self.links.similarity_settings())
        self.assertEqual(result['settings']['threshold'], .85)
        self.assertEqual(result['relations'][0]['id'], relation_id)
        self.assertEqual(result['relations'][0]['evidence'][0]['source_ref'], 'user:relation')
        self.assertEqual(result['recognitions'][0]['user_formulation'], 'Wohnzimmer nicht aus')
        recognition_id = self.links.record_similarity_recognition(
            'Wohnzimmer nicht aus', claim_id, 'negative',
            source_ref='user:recognition', basis='Explizite Bewertung.')
        decided = self.inspector.similarity(self.links.similarity_settings())
        decision = decided['recognitions'][0]['user_decision']
        self.assertEqual(decision['relation_id'], recognition_id)
        self.assertEqual(decision['polarity'], 'negative')
        self.assertTrue(decision['updated_at'])

    def test_similarity_turn_diagnostics_are_explicit(self):
        events = [
            {'component':'semantic_links','operation':'similarity_lookup','status':'ambiguous','details':{
                'threshold':.85,'similarity':.9,'checked_count':7,'candidate_count':2,
                'config_version':'abc','negative_relation_present':False}},
        ]
        result = turn_semantics({'steps': events, 'llm_calls': [], 'status': 'success'})
        self.assertEqual((result['threshold'], result['similarity'], result['checked_count']), (.85, .9, 7))
        self.assertTrue(result['ambiguity_conflict']); self.assertFalse(result['direct_execution'])
