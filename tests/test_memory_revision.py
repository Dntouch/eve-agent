import json
import tempfile
import unittest
from pathlib import Path

from eve_agent.memory_revision import MemoryRevision
from eve_agent.memory_v2 import MemoryV2Runtime
from eve_agent.memory_compiler import MemoryCompiler
from eve_agent.storage import EveDatabase, ConversationStore
from eve_agent.transport_access import transport_access


class MemoryRevisionTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db=EveDatabase(Path(self.tmp.name)/'eve.db')
        self.store=ConversationStore(self.db)
        self.conversation=self.store.create('Revision')['id']
        self.memory=MemoryV2Runtime(self.db,MemoryCompiler(self.db))
        self.service=self.memory.revisions
        self.add_claim('old','Homocysten ohne Emojis')
        self.text='Home Assistant ohne Emojis. Homocysten war ein Erkennungsfehler.'

    def add_claim(self,claim_id,text,scope='user:default',lifecycle='active',payload=None):
        with self.db.connect() as c:
            c.execute("INSERT INTO memory_claims(id,claim_kind,scope,canonical_key,slot_key,display_text,payload_json,lifecycle,verification_policy,created_at,updated_at) VALUES (?,'opaque_fact',?,?,?,?,?,?,'stable','2026-01-01','2026-01-01')",
                      (claim_id,scope,'v2:'+claim_id,'v2:emoji-rule',text,json.dumps(payload or {}),lifecycle))

    def parameters(self,**changes):
        p={'mutation_id':'correction-one','target_id':'old','expected_version':self.service.inspect('old')['version'],
           'source_reference':'request-one','evidence_quote':self.text,'action':'correct',
           'replacement':{'display_text':'Home Assistant ohne Emojis.','payload':{'epistemic_kind':'user_instruction'}},
           'reason':'Explicit correction'}
        p.update(changes);return p

    def revise(self,p=None,**changes):
        return self.service.revise(p or self.parameters(**changes),source_reference='request-one',user_text=self.text,
                                   conversation_id=self.conversation,turn_id='turn-one')

    def counts(self):
        with self.db.connect() as c:
            return tuple(c.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in
                         ('memory_claims','memory_observations','memory_evidence','memory_relations','memory_learning_decisions'))

    def test_atomic_revision_history_evidence_and_immediate_retrieval(self):
        result=self.revise();self.assertEqual(result['status'],'applied')
        old=self.service.inspect('old');new=self.service.inspect(result['claim_id'])
        self.assertEqual(old['claim']['lifecycle'],'retired')
        self.assertEqual(new['claim']['lifecycle'],'active')
        self.assertEqual(new['relations'][0]['relation_type'],'supersedes')
        self.assertEqual(new['relations'][0]['to_claim_id'],'old')
        self.assertEqual(old['evidence'][0]['stance'],'contradicts')
        self.assertEqual(new['evidence'][0]['stance'],'supports')
        hits=self.memory.retrieve('Home Assistant Emojis',None)
        self.assertIn(result['claim_id'],[h.memory_id for h in hits])
        self.assertNotIn('old',[h.memory_id for h in hits])
        self.assertEqual(new['decisions'][0]['method'],'direct_revision')

    def test_identical_retry_is_idempotent_changed_retry_conflicts(self):
        p=self.parameters();one=self.revise(p);before=self.counts()
        self.assertTrue(self.revise(p)['replayed']);self.assertEqual(self.counts(),before)
        self.assertEqual(self.revise({**p,'reason':'different'})['status'],'conflict')
        self.assertEqual(one['decision_id'],self.revise(p)['decision_id'])

    def test_stale_version_and_second_correction_do_not_overwrite(self):
        p=self.parameters()
        with self.db.connect() as c:c.execute("UPDATE memory_claims SET display_text='Concurrent edit' WHERE id='old'")
        before=self.counts();self.assertEqual(self.revise(p)['status'],'conflict');self.assertEqual(before,self.counts())
        self.revise();self.assertEqual(self.revise(self.parameters(mutation_id='second'))['status'],'conflict')

    def test_missing_source_bad_quote_and_paraphrased_instruction_do_not_write(self):
        for patch in ({'source_reference':'invented'}, {'evidence_quote':'Not said'},
                      {'replacement':{'display_text':'A paraphrase','payload':{'epistemic_kind':'user_instruction'}}}):
            before=self.counts();self.assertIn(self.revise(**patch)['status'],{'denied','needs_clarification'});self.assertEqual(before,self.counts())

    def test_failure_after_inserts_rolls_back_entire_revision(self):
        with self.db.connect() as c:
            c.execute("CREATE TRIGGER fail_direct_relation BEFORE INSERT ON memory_relations BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        before=self.counts()
        with self.assertRaises(Exception):self.revise()
        self.assertEqual(before,self.counts());self.assertEqual(self.service.inspect('old')['claim']['lifecycle'],'active')

    def test_retract_refine_contradict_and_temporal_change(self):
        for action in ('retract','refine','contradict','temporal_change'):
            with self.subTest(action=action):
                claim_id=action;self.add_claim(claim_id,action)
                p=self.parameters(target_id=claim_id,expected_version=self.service.inspect(claim_id)['version'],action=action,mutation_id=action)
                if action=='temporal_change':p['effective_at']='2026-10-23T12:00:00+02:00'
                result=self.revise(p);self.assertEqual(result['status'],'applied')
                state=self.service.inspect(claim_id)['claim']['lifecycle']
                self.assertEqual(state,'invalid' if action=='retract' else 'active' if action=='contradict' else 'retired')
        self.assertEqual(self.revise(action='temporal_change')['reason'],'effective_at_with_timezone_required')

    def test_relations_require_exact_version_and_matching_scope(self):
        self.add_claim('other','Related claim')
        p=self.parameters(action='relate',related_id='other',related_version=self.service.inspect('other')['version'],relation_type='refines')
        self.assertEqual(self.revise(p)['status'],'applied')
        self.assertEqual(self.service.inspect('old')['claim']['lifecycle'],'active')
        self.assertEqual(self.revise({**p,'mutation_id':'bad-version','related_version':'stale'})['status'],'conflict')
        self.assertEqual(self.revise({**p,'mutation_id':'bad-relation','relation_type':'supersedes'})['status'],'denied')

    def test_runtime_protection_and_remote_actor_ownership(self):
        self.add_claim('runtime','Protected','provider:runtime',payload={'runtime_self_knowledge':True})
        p=self.parameters(target_id='runtime',expected_version=self.service.inspect('runtime')['version'])
        self.assertEqual(self.revise(p)['reason'],'runtime_owned_memory')
        guest={'transport':'chatto','server_url':'https://chat.example','sender_id':'guest','owner_id':'owner'}
        with transport_access(guest,public=True):
            self.assertEqual(self.revise()['status'],'denied')
        owner={**guest,'sender_id':'owner'}
        with transport_access(owner,public=True):result=self.revise()
        self.assertEqual(result['status'],'applied')

    def test_source_attaches_after_turn_and_reaches_learning_context(self):
        from eve_agent.shadow_learning import ProductiveLearningPipeline
        result=self.revise()
        user,_=self.store.append_turn(self.conversation,self.text,'Korrigiert',turn_id='turn-one')
        self.service.attach_turn('turn-one',user['id'])
        evidence=self.service.inspect(result['claim_id'])['evidence'][0]
        self.assertEqual(evidence['source_message_id'],user['id']);self.assertEqual(evidence['source_turn_id'],'turn-one')
        pipeline=ProductiveLearningPipeline(self.db)
        context=pipeline._model_context(pipeline._snapshot('turn-one'),[])
        self.assertEqual(context['applied_memory_revisions'][0]['result']['decision_id'],result['decision_id'])

    def test_later_learning_does_not_duplicate_same_slot_or_revive_direct_target(self):
        from eve_agent.shadow_learning import ProductiveLearningPipeline
        from test_conversation_learning import proposal
        self.revise()
        user,_=self.store.append_turn(self.conversation,self.text,'Korrigiert',turn_id='turn-one')
        self.service.attach_turn('turn-one',user['id'])
        pipeline=ProductiveLearningPipeline(self.db)
        pipeline.accept_turn('turn-one')
        snapshot=pipeline._snapshot('turn-one')
        context=pipeline._model_context(snapshot,[])
        value=proposal(context,'duplicate')
        value['claim'].update(scope='user:default',slot_key='v2:emoji-rule',lifecycle='active',verification_policy='stable')
        value['evidence'][0]['target_claim_id']='new_claim'
        import time
        result=pipeline._persist(snapshot,value,'llm',{},time.perf_counter())
        self.assertEqual(result['decision_type'],'no_persist')
        self.assertEqual(result['reason_code'],'direct_revision_already_applied')
        self.assertEqual(self.service.inspect('old')['claim']['lifecycle'],'retired')
        with self.db.connect() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM memory_claims WHERE lifecycle='active'").fetchone()[0],1)

    def test_member_cannot_change_subject_or_other_actor(self):
        owner={'transport':'chatto','server_url':'https://chat.example','sender_id':'owner','owner_id':'owner'}
        guest={**owner,'sender_id':'guest'}
        with transport_access(guest,public=True):
            # Seed the original provenance through a local/owner-authorized direct write.
            self.assertEqual(self.revise()['status'],'denied')
        with transport_access(owner,public=True):result=self.revise()
        # The replacement is owned by the actor who supplied its evidence.
        replacement_id=result['claim_id']
        p=self.parameters(target_id=replacement_id,expected_version=self.service.inspect(replacement_id)['version'],mutation_id='guest')
        with transport_access(guest,public=True):self.assertEqual(self.revise(p)['status'],'denied')
        with transport_access(owner,public=True):self.assertEqual(self.revise(p)['status'],'applied')
        self.add_claim('subject','Own preference',payload={'subject':'user:owner'})
        p=self.parameters(target_id='subject',expected_version=self.service.inspect('subject')['version'],mutation_id='subject')
        self.assertEqual(self.revise(p)['reason'],'subject_change_requires_new_claim')

    def test_member_can_revise_own_provenance_and_other_member_cannot(self):
        guest={'transport':'chatto','server_url':'https://chat.example','sender_id':'guest','owner_id':'owner'}
        user,_=self.store.append_turn(self.conversation,'Own statement','OK',turn_id='seed',
                                    user_metadata={'conversation_source':guest})
        with self.db.connect() as c:
            c.execute("INSERT INTO memory_observations(id,source_role,source_type,message_id,observed_at,scope,created_at) "
                      "VALUES ('seed-observation','user','user_message',?,'2026-01-01','user:default','2026-01-01')",(user['id'],))
            c.execute("INSERT INTO memory_evidence(id,claim_id,observation_id,stance,evidence_type,observed_at,created_at) "
                      "VALUES ('seed-evidence','old','seed-observation','supports','user_message','2026-01-01','2026-01-01')")
        p=self.parameters()
        with transport_access({**guest,'sender_id':'other'},public=True):
            self.assertEqual(self.revise(p)['status'],'denied')
        with transport_access(guest,public=True):
            self.assertEqual(self.revise(p)['status'],'applied')

    def test_concurrent_writers_one_wins_other_reports_conflict(self):
        from concurrent.futures import ThreadPoolExecutor
        p=self.parameters()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(self.revise,[{**p,'mutation_id':'a'},{**p,'mutation_id':'b'}]))
        self.assertEqual(sorted(r['status'] for r in results),['applied','conflict'])
        self.assertEqual(self.counts()[0],2)

    def test_brainwatch_graph_and_turn_links_show_direct_revision(self):
        from eve_agent.brainwatch import MemoryExplorerInspector
        result=self.revise()
        user,_=self.store.append_turn(self.conversation,self.text,'Korrigiert',turn_id='turn-one')
        self.service.attach_turn('turn-one',user['id'])
        inspector=MemoryExplorerInspector(Path(self.tmp.name)/'eve.db')
        graph=inspector.memory_graph(anchor_claim_id=result['claim_id'])
        self.assertEqual({n['claim_id'] for n in graph['nodes']},{'old',result['claim_id']})
        self.assertEqual(graph['edges'][0]['relation_type'],'supersedes')
        links=inspector.claim_turns(result['claim_id'])
        self.assertIn('direct_revision',json.dumps(links))
        self.assertIn('turn-one',json.dumps(links))

    def test_provider_bindings_and_future_transitions_are_not_rewritten(self):
        with self.db.connect() as c:
            c.execute("UPDATE memory_claims SET claim_kind='provider_binding' WHERE id='old'")
        before=self.counts()
        self.assertEqual(self.revise()['reason'],'provider_binding_requires_verified_provider_evidence')
        self.assertEqual(self.counts(),before)
        self.assertEqual(self.revise(action='temporal_change',effective_at='2999-01-01T00:00:00Z')['reason'],
                         'future_transition_requires_scheduling')

    def test_payload_credentials_are_redacted_using_existing_storage_rules(self):
        p=self.parameters(replacement={'display_text':'Corrected fact','payload':{'password':'must-not-persist'}})
        result=self.revise(p)
        self.assertEqual(self.service.inspect(result['claim_id'])['claim']['payload']['password'],'[REDACTED]')

if __name__=='__main__':unittest.main()
